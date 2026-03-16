"""
organizer.py — file copying, CSV logging, progress output,
and the main scan_and_organize() entry function.
"""

import csv
import os
import shutil
import sqlite3 as _sqlite3
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from config import (
    BOOKS_DIR, ORGANIZED_DIR, CACHE_DB, UNCERTAIN_CSV, FAILED_DIR, SUPPORTED_EXTS,
    UNCERTAIN_THRESHOLD, CSV_LOG_THRESHOLD, OLLAMA_MODEL, DEFAULT_WORKERS,
)
from .cache import book_upsert, book_get
from .classifier import BookMeta, resolve, destination

# -- Thread-safety locks ------------------------------------------------------
_print_lock   = threading.Lock()
_csv_lock     = threading.Lock()
_copy_lock    = threading.Lock()
_book_counter = 0

# -- CSV log ------------------------------------------------------------------
_csv_writer = None
_csv_file   = None


def _init_csv(dry_run: bool):
    global _csv_writer, _csv_file
    if dry_run:
        return
    _csv_file   = open(UNCERTAIN_CSV, "w", newline="", encoding="utf-8")
    _csv_writer = csv.writer(_csv_file)
    _csv_writer.writerow([
        "original_file", "detected_author", "detected_language",
        "detected_genre", "detected_category", "confidence",
        "destination", "sources"
    ])


def _log_uncertain(src: Path, meta: BookMeta, dest: Path):
    if _csv_writer is None:
        return
    with _csv_lock:
        _csv_writer.writerow([
            str(src), meta.author, meta.language, meta.genre,
            meta.category, meta.confidence, str(dest),
            "|".join(meta.sources),
        ])
        _csv_file.flush()


def _close_csv():
    global _csv_file
    if _csv_file:
        _csv_file.close()


# -- Book processing ----------------------------------------------------------

def process_book(src: Path, dry_run: bool = False, total: int = 0):
    global _book_counter

    # Skip books already in the DB whose destination file still exists on disk.
    # API metadata is already cached, so there is nothing to reprocess or recopy.
    if not dry_run:
        existing = book_get(str(src))
        if existing:
            dest_on_disk = ORGANIZED_DIR / existing["relative_path"]
            if dest_on_disk.exists():
                with _print_lock:
                    _book_counter += 1
                    progress = f"[{_book_counter}/{total}]" if total else f"[{_book_counter}]"
                    print(f"\n  {progress} [SKIPPED — already organised] {src.name}")
                meta = BookMeta(
                    title=existing.get("title", "Unknown"),
                    author=existing.get("author", "Unknown Author"),
                    language=existing.get("language", "unknown"),
                    all_genres=existing.get("genres") or [],
                    category=existing.get("directory", "other"),
                    confidence=existing.get("confidence", 0),
                    sources=(existing.get("sources") or "").split("|"),
                )
                return meta, dest_on_disk

            # Stale DB path — the file was likely moved by flatten but the DB
            # update failed. Try the flattened location (one level up, no lang
            # subdir) before giving up and re-copying.
            p = Path(existing["relative_path"])
            if len(p.parts) >= 3:
                # e.g. reading/Author/english/book.epub → reading/Author/book.epub
                flat_candidate = ORGANIZED_DIR / p.parts[0] / p.parts[1] / p.name
                if flat_candidate.exists():
                    new_rel = str(flat_candidate.relative_to(ORGANIZED_DIR))
                    try:
                        con = _sqlite3.connect(CACHE_DB)
                        con.execute(
                            "UPDATE books SET relative_path = ? WHERE original_path = ?",
                            (new_rel, str(src)),
                        )
                        con.commit()
                        con.close()
                    except Exception:
                        pass
                    with _print_lock:
                        _book_counter += 1
                        progress = f"[{_book_counter}/{total}]" if total else f"[{_book_counter}]"
                        print(f"\n  {progress} [SKIPPED — healed path] {src.name}")
                    meta = BookMeta(
                        title=existing.get("title", "Unknown"),
                        author=existing.get("author", "Unknown Author"),
                        language=existing.get("language", "unknown"),
                        all_genres=existing.get("genres") or [],
                        category=existing.get("directory", "other"),
                        confidence=existing.get("confidence", 0),
                        sources=(existing.get("sources") or "").split("|"),
                    )
                    return meta, flat_candidate

    meta = resolve(src)

    with _copy_lock:
        dest = destination(src, meta)
        # Before touching the filesystem, check whether this exact file (by
        # name + size) already exists anywhere under the author's directory.
        # This catches books that were flattened out of a language subfolder
        # so their on-disk path no longer matches what destination() returns.
        author_dir = dest.parent.parent if not meta.fallback else dest.parent
        existing_copy = None
        if author_dir.exists():
            for candidate in author_dir.rglob(src.name):
                if candidate.is_file() and candidate.stat().st_size == src.stat().st_size:
                    existing_copy = candidate
                    break
        if existing_copy is not None:
            # Already on disk — use the existing path as dest so the DB
            # record is updated to the correct location below.
            dest = existing_copy
        elif dest.exists():
            # Different file occupying the same destination name — find a
            # free slot rather than silently overwriting.
            counter = 1
            while dest.exists():
                dest = dest.parent / f"{src.stem}_({counter}){src.suffix}"
                counter += 1
            if not dry_run:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
        else:
            if not dry_run:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)

    uncertain = meta.confidence < UNCERTAIN_THRESHOLD
    # Only write to CSV if confidence is very low AND the book couldn't be
    # placed into a meaningful category (fallback folder or 'other')
    truly_stuck = (
        meta.confidence < CSV_LOG_THRESHOLD and
        (meta.fallback or meta.category == "other")
    )
    status = "DRY-RUN" if dry_run else "COPYING"
    flag = " WARNING LOW CONFIDENCE" if uncertain else ""
    fb = " [FALLBACK]" if meta.fallback else ""
    ollama = " [Ollama]" if "ollama" in meta.sources else ""

    with _print_lock:
        _book_counter += 1
        progress = f"[{_book_counter}/{total}]" if total else f"[{_book_counter}]"
        print(f"\n  {progress} [{status}]{fb}{flag}{ollama} {src.name}")
        print(f"           Author     : {meta.author}")
        print(f"           Language   : {meta.language}  |  Genre : {meta.genre}  ->  {meta.category}")
        print(f"           Confidence : {meta.confidence}/100  |  Sources : {', '.join(meta.sources) or 'none'}")
        print(f"           -> {dest.relative_to(ORGANIZED_DIR)}")

    if truly_stuck:
        _log_uncertain(src, meta, dest)

    # Record the final result in the books table
    if not dry_run:
        rel       = dest.relative_to(ORGANIZED_DIR)
        directory = rel.parts[0] if rel.parts else meta.category
        book_upsert(
            original_path    = str(src),
            title            = meta.title,
            author           = meta.author,
            language         = meta.language,
            all_genres       = meta.all_genres,
            directory        = directory,
            relative_path    = str(rel),
            confidence       = meta.confidence,
            sources          = meta.sources,
            file_size_bytes  = dest.stat().st_size if dest.exists() else src.stat().st_size,
        )

    return meta, dest


# -- Main scanner -------------------------------------------------------------

def scan_and_organize(dry_run: bool = False, workers: int = DEFAULT_WORKERS):
    if not BOOKS_DIR.exists():
        print(f"ERROR: Books directory not found: {BOOKS_DIR}")
        sys.exit(1)

    ORGANIZED_DIR.mkdir(parents=True, exist_ok=True)
    _init_csv(dry_run)

    # Collect all book paths up front so we know the total
    all_books = []
    for subdir in sorted(BOOKS_DIR.iterdir()):
        if not subdir.is_dir() or subdir.name == "books_organized":
            continue
        for root, _, files in os.walk(subdir):
            for fname in sorted(files):
                src = Path(root) / fname
                if src.suffix.lower() in SUPPORTED_EXTS:
                    all_books.append(src)

    total = len(all_books)
    print(f"\n  Found {total} books — processing with {workers} concurrent workers ...\n")

    global _book_counter
    _book_counter = 0

    copied = failed = uncertain_count = ollama_count = 0
    failed_books = []
    uncertain_books = []

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(process_book, src, dry_run, total): src
                   for src in all_books}

        for future in as_completed(futures):
            src = futures[future]
            try:
                meta, dest = future.result()
                copied += 1
                if "ollama" in meta.sources:
                    ollama_count += 1
                if meta.confidence < UNCERTAIN_THRESHOLD:
                    uncertain_count += 1
                    uncertain_books.append((src, meta))
            except Exception as e:
                failed += 1
                failed_books.append((src, str(e)))
                with _print_lock:
                    print(f"  [FAILED] {src.name}: {e}")
                # Copy to failed/ so no book is ever lost, but skip if an
                # identical copy is already there from a previous run.
                if not dry_run:
                    try:
                        FAILED_DIR.mkdir(parents=True, exist_ok=True)
                        fail_dest = FAILED_DIR / src.name
                        if fail_dest.exists() and fail_dest.stat().st_size == src.stat().st_size:
                            pass  # already there — don't create _(1)
                        else:
                            counter = 1
                            while fail_dest.exists():
                                fail_dest = FAILED_DIR / f"{src.stem}_({counter}){src.suffix}"
                                counter  += 1
                            shutil.copy2(src, fail_dest)
                    except Exception as copy_err:
                        with _print_lock:
                            print(f"  [FAILED COPY] could not copy to failed/: {copy_err}")

    _close_csv()
    _flatten_single_language_folders(dry_run)
    _print_summary(total, copied, ollama_count, failed, uncertain_count,
                   workers, dry_run, failed_books, uncertain_books)


# -- Post-processing: flatten single-language author folders ------------------

def _flatten_single_language_folders(dry_run: bool = False):
    """
    For every author folder that contains exactly one language subfolder,
    move all books up to the author level and delete the empty language folder.

    Before:  reading/Stephen King/english/book.epub
    After:   reading/Stephen King/book.epub
    """
    print("\n  Post-processing: flattening single-language author folders ...")
    flattened = 0
    skipped = 0

    # One DB connection for the entire pass (not one per file).
    db_con = None
    if not dry_run:
        try:
            db_con = _sqlite3.connect(CACHE_DB)
        except Exception as db_err:
            print(f"  [WARNING] could not open DB for flatten: {db_err}")

    # Walk category dirs (cookbooks, reading, etc.)
    for category_dir in sorted(ORGANIZED_DIR.iterdir()):
        if not category_dir.is_dir():
            continue
        if category_dir.name in ("failed", "pdf", "unknown"):
            continue

        # Walk author dirs inside each category
        for author_dir in sorted(category_dir.iterdir()):
            if not author_dir.is_dir():
                continue

            # Collect immediate subdirs that look like language folders
            lang_dirs = [d for d in author_dir.iterdir() if d.is_dir()]

            if len(lang_dirs) != 1:
                skipped += 1
                continue  # multiple languages — keep structure as-is

            lang_dir = lang_dirs[0]
            books = list(lang_dir.iterdir())

            if not books:
                # Empty language folder — just remove it
                if not dry_run:
                    lang_dir.rmdir()
                continue

            action = "DRY-RUN" if dry_run else "FLATTENING"
            print(
                f"    [{action}] {category_dir.name}/{author_dir.name}/{lang_dir.name}/ "
                f"→ {category_dir.name}/{author_dir.name}/  ({len(books)} book(s))"
            )

            if not dry_run:
                for book in books:
                    dest = author_dir / book.name
                    old_rel = str(book.relative_to(ORGANIZED_DIR))

                    if dest.exists():
                        # Same file already in place — just remove the copy
                        # in the language subfolder; no _(1) needed.
                        if dest.stat().st_size == book.stat().st_size:
                            book.unlink()
                            if db_con:
                                try:
                                    db_con.execute(
                                        "UPDATE books SET relative_path = ?"
                                        " WHERE relative_path = ?",
                                        (str(dest.relative_to(ORGANIZED_DIR)), old_rel),
                                    )
                                    db_con.commit()
                                except Exception as db_err:
                                    print(
                                        f"    [WARNING] DB update failed"
                                        f" for {book.name}: {db_err}"
                                    )
                            print(f"    [DEDUPED]  removed redundant copy: {old_rel}")
                            continue
                        # Genuinely different file — find a free slot.
                        counter = 1
                        while dest.exists():
                            dest = author_dir / f"{book.stem}_({counter}){book.suffix}"
                            counter += 1

                    shutil.move(str(book), dest)
                    new_rel = str(dest.relative_to(ORGANIZED_DIR))
                    if db_con:
                        try:
                            db_con.execute(
                                "UPDATE books SET relative_path = ?"
                                " WHERE relative_path = ?",
                                (new_rel, old_rel),
                            )
                            db_con.commit()
                        except Exception as db_err:
                            print(
                                f"    [WARNING] could not update DB path"
                                f" for {book.name}: {db_err}"
                            )

                # Remove now-empty language folder
                try:
                    lang_dir.rmdir()
                except OSError:
                    print(f"    [WARNING] could not remove {lang_dir} (not empty?)")

            flattened += 1

    if db_con:
        db_con.close()

    print(f"  Flattened : {flattened} author folder(s)  |  Kept multi-language : {skipped}")


def _print_summary(total, copied, ollama_count, failed, uncertain_count,
                   workers, dry_run, failed_books, uncertain_books):
    sep = "=" * 65
    print(f"\n{sep}")
    print(f"  SUMMARY")
    print(sep)
    print(f"  Total books found       : {total}")
    print(f"  Successfully copied     : {copied}")
    print(f"  Classified by Ollama    : {ollama_count}  (model: {OLLAMA_MODEL})")
    print(f"  Failed (errors)         : {failed}")
    print(f"  Low confidence (report)  : {uncertain_count}  (threshold: {UNCERTAIN_THRESHOLD}/100)")
    print(f"  Written to CSV           : books with confidence < {CSV_LOG_THRESHOLD} in other/fallback")
    print(f"  Concurrent workers       : {workers}")
    if dry_run:
        print("  Mode                    : DRY-RUN -- no files were copied")

    if failed_books:
        print(f"\n{'-'*65}")
        print(f"  FAILED TO ANALYZE / COPY  ({len(failed_books)} books)")
        print(f"  (copied to {FAILED_DIR})")
        print(f"{'-'*65}")
        for path, err in failed_books:
            print(f"  [FAIL] {path}")
            print(f"         Reason: {err}")

    if uncertain_books:
        print(f"\n{'-'*65}")
        print(f"  LOW CONFIDENCE PLACEMENTS  ({len(uncertain_books)} books)")
        print(f"{'-'*65}")
        for path, meta in uncertain_books:
            print(f"  [UNCERTAIN] {path}")
            print(f"    -> category: {meta.category}  |  author: {meta.author}"
                  f"  |  lang: {meta.language}  |  confidence: {meta.confidence}/100")

    if UNCERTAIN_CSV.exists() and uncertain_count > 0 and not dry_run:
        print(f"\n  Uncertain books also saved to:\n  {UNCERTAIN_CSV}")

    print(sep)
