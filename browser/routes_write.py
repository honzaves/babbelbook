"""
browser/routes_write.py — all mutating PATCH endpoints.

Blueprint: write_bp
  PATCH /api/books/genres
  PATCH /api/books/title
  PATCH /api/books/author
  PATCH /api/books/language
  PATCH /api/books/directory

Also contains the file-system helpers _sanitize() and _move_book() used
by the author and directory rename operations.
"""

import json
import re
import shutil
from pathlib import Path

from flask import Blueprint, jsonify, request

from .db import _db, ORGANIZED_DIR, MAIN_DIRS

write_bp = Blueprint("write", __name__)


# ── File-system helpers ───────────────────────────────────────────────────────

def _sanitize(name: str) -> str:
    """Strip characters that are illegal in folder/file names."""
    name = (name or "").strip()
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = re.sub(r'\s+', " ", name)
    return name or "Unknown"


def _move_book(current_rel: str, new_rel: str) -> tuple[bool, str]:
    """Move a book file within ORGANIZED_DIR.

    Both paths are relative to ORGANIZED_DIR.
    Creates parent directories, handles duplicate filenames with _(1), _(2) …
    Returns (ok, new_relative_path_or_error_message).
    """
    src  = ORGANIZED_DIR / current_rel
    dest = ORGANIZED_DIR / new_rel
    if not src.exists():
        return False, f"Source file not found: {src}"
    if src == dest:
        return True, ""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        stem, suffix = dest.stem, dest.suffix
        n = 1
        while dest.exists():
            dest = dest.parent / f"{stem}_({n}){suffix}"
            n += 1
    shutil.move(str(src), str(dest))
    # Remove empty parent directories (up to two levels up)
    for parent in [src.parent, src.parent.parent]:
        try:
            if parent != ORGANIZED_DIR and not any(parent.iterdir()):
                parent.rmdir()
        except Exception:
            pass
    return True, str(dest.relative_to(ORGANIZED_DIR))


# ── Routes ────────────────────────────────────────────────────────────────────

@write_bp.route("/api/books", methods=["DELETE"])
def api_delete_book():
    """Delete a book: removes the file from disk and the row from the DB."""
    body = request.get_json(force=True, silent=True) or {}
    original_path = body.get("original_path", "").strip()
    if not original_path:
        return jsonify({"error": "original_path required"}), 400

    con = _db()
    if not con:
        return jsonify({"error": "Database not found"}), 404

    row = con.execute(
        "SELECT relative_path FROM books WHERE original_path = ?", (original_path,)
    ).fetchone()
    if not row:
        con.close()
        return jsonify({"error": "Book not found"}), 404

    rel_path = row["relative_path"]
    file_path = ORGANIZED_DIR / rel_path if rel_path else None

    # Delete file from disk (best-effort — DB row is always removed)
    deleted_file = False
    if file_path and file_path.exists():
        try:
            file_path.unlink()
            deleted_file = True
            # Clean up empty parent directories (up to two levels)
            for parent in [file_path.parent, file_path.parent.parent]:
                try:
                    if parent != ORGANIZED_DIR and not any(parent.iterdir()):
                        parent.rmdir()
                except Exception:
                    pass
        except Exception as e:
            con.close()
            return jsonify({"error": f"Could not delete file: {e}"}), 500

    # Remove from DB
    con.execute("DELETE FROM books WHERE original_path = ?", (original_path,))
    con.commit()
    con.close()
    return jsonify({"ok": True, "deleted_file": deleted_file})


@write_bp.route("/api/authors/merge", methods=["POST"])
def api_merge_authors():
    """Move all books from source_author into target_author across every category dir."""
    from .routes_read import invalidate_dup_cache

    body = request.get_json(force=True, silent=True) or {}
    source = body.get("source", "").strip()
    target = body.get("target", "").strip()
    if not source or not target or source == target:
        return jsonify({"error": "source and target author names required"}), 400

    con = _db()
    if not con:
        return jsonify({"error": "Database not found"}), 404

    moved = skipped = 0
    errors = []

    # Pre-compute all categories where target already has a folder.
    # Sorted for determinism when target lives in multiple categories.
    tgt_existing = {
        d.name: d / target
        for d in sorted(ORGANIZED_DIR.iterdir())
        if d.is_dir() and (d / target).is_dir()
    }

    # Find every category directory that has a folder for the source author
    for category_dir in sorted(ORGANIZED_DIR.iterdir()):
        if not category_dir.is_dir():
            continue
        src_author_dir = category_dir / source
        if not src_author_dir.is_dir():
            continue

        # Determine destination category (cross-category fix):
        #   1. Target exists in same category  → use it
        #   2. Target exists elsewhere         → use its established home
        #   3. Target doesn't exist yet        → create in same category as source
        if category_dir.name in tgt_existing:
            tgt_author_dir = tgt_existing[category_dir.name]
        elif tgt_existing:
            tgt_author_dir = next(iter(tgt_existing.values()))
        else:
            tgt_author_dir = category_dir / target

        tgt_author_dir.mkdir(parents=True, exist_ok=True)

        for book in sorted(src_author_dir.rglob("*")):
            if not book.is_file():
                continue

            dest = tgt_author_dir / book.name
            old_rel = str(book.relative_to(ORGANIZED_DIR))

            # Skip if an identical file (same size) already exists at dest
            if dest.exists() and dest.stat().st_size == book.stat().st_size:
                try:
                    book.unlink()
                    con.execute(
                        "DELETE FROM books WHERE relative_path = ?", (old_rel,)
                    )
                except Exception as e:
                    errors.append(str(e))
                skipped += 1
                continue

            # Different file with same name — find a free slot
            if dest.exists():
                counter = 1
                while dest.exists():
                    dest = tgt_author_dir / f"{book.stem}_({counter}){book.suffix}"
                    counter += 1

            try:
                shutil.move(str(book), dest)
                new_rel = str(dest.relative_to(ORGANIZED_DIR))
                con.execute(
                    "UPDATE books SET author = ?, relative_path = ?"
                    " WHERE relative_path = ?",
                    (target, new_rel, old_rel),
                )
                moved += 1
            except Exception as e:
                errors.append(f"{book.name}: {e}")

        # Commit all changes for this author dir in one transaction
        con.commit()

        # Remove the source author dir and any now-empty parents
        for d in sorted(src_author_dir.rglob("*"), reverse=True):
            try:
                if d.is_dir() and not any(d.iterdir()):
                    d.rmdir()
            except Exception:
                pass
        try:
            if src_author_dir.exists() and not any(src_author_dir.rglob("*")):
                src_author_dir.rmdir()
        except Exception:
            pass

    con.close()
    invalidate_dup_cache()

    if errors:
        return jsonify({
            "ok": False,
            "error": "; ".join(errors[:3]),
            "moved": moved,
            "skipped": skipped,
        }), 500
    return jsonify({"ok": True, "moved": moved, "skipped": skipped})


@write_bp.route("/api/books/genres", methods=["PATCH"])
def api_update_genres():
    """Replace the genre list for a book (identified by original_path)."""
    body = request.get_json(force=True, silent=True) or {}
    original_path = body.get("original_path", "").strip()
    genres = body.get("genres")
    if not original_path or not isinstance(genres, list):
        return jsonify({"error": "original_path and genres list required"}), 400

    genres = list(dict.fromkeys(
        g.strip() for g in genres if isinstance(g, str) and g.strip()
    ))
    con = _db()
    if not con:
        return jsonify({"error": "Database not found"}), 404
    try:
        con.execute(
            "UPDATE books SET genres = ? WHERE original_path = ?",
            (json.dumps(genres), original_path),
        )
        con.commit()
        updated = con.execute(
            "SELECT genres FROM books WHERE original_path = ?", (original_path,)
        ).fetchone()
        con.close()
        if not updated:
            return jsonify({"error": "Book not found"}), 404
        return jsonify({"ok": True, "genres": json.loads(updated[0])})
    except Exception as e:
        con.close()
        return jsonify({"error": str(e)}), 500


@write_bp.route("/api/books/author", methods=["PATCH"])
def api_update_author():
    """Rename the author: moves file to new author folder and updates DB."""
    body = request.get_json(force=True, silent=True) or {}
    original_path = body.get("original_path", "").strip()
    raw_author = body.get("author", "").strip()
    if not original_path or not raw_author:
        return jsonify({"error": "original_path and author required"}), 400
    new_author = _sanitize(raw_author)

    con = _db()
    if not con:
        return jsonify({"error": "Database not found"}), 404

    row = con.execute(
        "SELECT relative_path, directory FROM books WHERE original_path = ?",
        (original_path,),
    ).fetchone()
    if not row:
        con.close()
        return jsonify({"error": "Book not found"}), 404

    old_rel   = row["relative_path"]
    directory = row["directory"] or "other"
    new_rel   = str(Path(directory) / new_author / Path(old_rel).name)

    ok, result = _move_book(old_rel, new_rel)
    if not ok:
        con.close()
        return jsonify({"error": result}), 500

    final_rel = result if result else new_rel
    con.execute(
        "UPDATE books SET author = ?, relative_path = ? WHERE original_path = ?",
        (new_author, final_rel, original_path),
    )
    con.commit()
    con.close()
    return jsonify({"ok": True, "author": new_author, "relative_path": final_rel})


@write_bp.route("/api/books/directory", methods=["PATCH"])
def api_update_directory():
    """Change the top-level directory: moves file and updates DB."""
    body = request.get_json(force=True, silent=True) or {}
    original_path = body.get("original_path", "").strip()
    new_dir = body.get("directory", "").strip()
    if not original_path or new_dir not in MAIN_DIRS:
        return jsonify({"error": f"original_path and directory (one of {MAIN_DIRS}) required"}), 400

    con = _db()
    if not con:
        return jsonify({"error": "Database not found"}), 404

    row = con.execute(
        "SELECT relative_path, author FROM books WHERE original_path = ?",
        (original_path,),
    ).fetchone()
    if not row:
        con.close()
        return jsonify({"error": "Book not found"}), 404

    old_rel  = row["relative_path"]
    author   = row["author"] or "Unknown Author"
    new_rel  = str(Path(new_dir) / author / Path(old_rel).name)

    ok, result = _move_book(old_rel, new_rel)
    if not ok:
        con.close()
        return jsonify({"error": result}), 500

    final_rel = result if result else new_rel
    con.execute(
        "UPDATE books SET directory = ?, relative_path = ? WHERE original_path = ?",
        (new_dir, final_rel, original_path),
    )
    con.commit()
    con.close()
    return jsonify({"ok": True, "directory": new_dir, "relative_path": final_rel})


@write_bp.route("/api/books/title", methods=["PATCH"])
def api_update_title():
    """Update the book title (DB-only — title is not part of the file path)."""
    body = request.get_json(force=True, silent=True) or {}
    original_path = body.get("original_path", "").strip()
    new_title = (body.get("title", "") or "").strip()
    if not original_path or not new_title:
        return jsonify({"error": "original_path and title required"}), 400

    con = _db()
    if not con:
        return jsonify({"error": "Database not found"}), 404

    row = con.execute(
        "SELECT original_path FROM books WHERE original_path = ?",
        (original_path,),
    ).fetchone()
    if not row:
        con.close()
        return jsonify({"error": "Book not found"}), 404

    con.execute(
        "UPDATE books SET title = ? WHERE original_path = ?",
        (new_title, original_path),
    )
    con.commit()
    con.close()
    return jsonify({"ok": True, "title": new_title})


@write_bp.route("/api/books/language", methods=["PATCH"])
def api_update_language():
    """Update the book language (DB-only — language is metadata, not part of the path)."""
    body = request.get_json(force=True, silent=True) or {}
    original_path = body.get("original_path", "").strip()
    new_language = (body.get("language", "") or "").strip()
    if not original_path or not new_language:
        return jsonify({"error": "original_path and language required"}), 400

    con = _db()
    if not con:
        return jsonify({"error": "Database not found"}), 404

    row = con.execute(
        "SELECT original_path FROM books WHERE original_path = ?",
        (original_path,),
    ).fetchone()
    if not row:
        con.close()
        return jsonify({"error": "Book not found"}), 404

    con.execute(
        "UPDATE books SET language = ? WHERE original_path = ?",
        (new_language, original_path),
    )
    con.commit()
    con.close()
    return jsonify({"ok": True, "language": new_language})
