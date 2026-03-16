#!/usr/bin/env python3
"""
deduplicate_books.py — remove duplicate book files from the organised library.

Duplicates are files whose stem ends with _(1), _(2), _(3) … — the suffix
appended automatically by the organiser when a destination path was already
taken.  Examples:

    The Great Gatsby_(1).epub
    Dune_(2).epub
    Sapiens_(1).pdf

For each duplicate the script checks whether a canonical copy (the same name
without the suffix) exists in the same folder AND whether it has the same file
size.

  same name + same size  → safe to delete  (shown normally)
  same name + diff size  → WARNING only    (never deleted — may be a different
                           edition; shown with a ⚠ warning for manual review)
  no canonical on disk   → treated as safe to delete (orphaned duplicate)

Usage:
    python deduplicate_books.py              # dry-run — shows what would happen
    python deduplicate_books.py --delete     # live run — actually deletes safe duplicates
    python deduplicate_books.py --help
"""

import argparse
import re
import sqlite3
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Path / DB constants (mirrors config.py — no dependency on the package)
# ---------------------------------------------------------------------------
BOOKS_DIR     = Path.home() / "Documents" / "Books"
ORGANIZED_DIR = BOOKS_DIR / "books_organized"
CACHE_DB      = ORGANIZED_DIR / ".cache.db"

SUPPORTED_EXTS = {".epub", ".pdf", ".mobi", ".azw", ".azw3", ".cbz", ".cbr", ".fb2"}

# Matches:  anything_(1)  anything_(42)  — right before the file extension
_DUP_RE = re.compile(r"^(.+)_\((\d+)\)$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def find_duplicates(root: Path) -> list[dict]:
    """
    Walk *root* recursively and return one dict per duplicate-pattern file found.

    Each dict contains:
        path        — absolute Path of the duplicate
        rel         — path relative to ORGANIZED_DIR (for DB lookup)
        canonical   — absolute Path of the expected canonical copy
        canon_rel   — relative path of the canonical (may not exist)
        has_canon   — True if the canonical file actually exists on disk
        same_size   — True if canonical exists AND sizes match (safe to delete)
                      False if canonical exists but sizes differ (suspicious)
                      True if canonical does NOT exist (orphaned — safe to delete)
        safe        — True if this entry should be deleted in live mode
        n           — the duplicate number  (1, 2, 3 …)
    """
    results = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() not in SUPPORTED_EXTS:
            continue
        m = _DUP_RE.match(p.stem)
        if not m:
            continue
        canonical  = p.parent / f"{m.group(1)}{p.suffix}"
        has_canon  = canonical.exists()
        if has_canon:
            same_size = canonical.stat().st_size == p.stat().st_size
        else:
            same_size = True   # no canonical to compare — treat as safe orphan
        results.append({
            "path":      p,
            "rel":       str(p.relative_to(ORGANIZED_DIR)),
            "canonical": canonical,
            "canon_rel": str(canonical.relative_to(ORGANIZED_DIR)),
            "has_canon": has_canon,
            "same_size": same_size,
            "safe":      same_size,   # only delete when sizes match (or no canon)
            "n":         int(m.group(2)),
        })
    return results


def db_lookup_by_rel(con: sqlite3.Connection, rel_path: str) -> sqlite3.Row | None:
    return con.execute(
        "SELECT original_path, title, author FROM books WHERE relative_path = ?",
        (rel_path,),
    ).fetchone()


def delete_from_db(con: sqlite3.Connection, rel_path: str) -> bool:
    cur = con.execute("DELETE FROM books WHERE relative_path = ?", (rel_path,))
    con.commit()
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _yn(val: bool) -> str:
    return "yes" if val else "no"


def print_report(duplicates: list[dict], db_records: dict[str, bool]) -> None:
    """Pretty-print the duplicates table, safe and suspicious separately."""
    if not duplicates:
        print("  No duplicates found.")
        return

    safe       = [d for d in duplicates if d["safe"]]
    suspicious = [d for d in duplicates if not d["safe"]]
    col = 62

    if safe:
        print(f"\n  {'SAFE TO DELETE':<{col}}  CANON EXISTS  IN DB")
        print(f"  {'-'*col}  ------------  -----")
        for d in safe:
            short = d["rel"]
            if len(short) > col:
                short = "…" + short[-(col - 1):]
            in_db = _yn(db_records.get(d["rel"], False))
            print(f"  {short:<{col}}  {_yn(d['has_canon']):<12}  {in_db}")

    if suspicious:
        print(f"\n  {'⚠  DIFFERENT SIZE — MANUAL REVIEW REQUIRED (never auto-deleted)':<{col}}")
        print(f"  {'SUSPICIOUS FILE':<{col}}  CANON EXISTS  IN DB")
        print(f"  {'-'*col}  ------------  -----")
        for d in suspicious:
            short = d["rel"]
            if len(short) > col:
                short = "…" + short[-(col - 1):]
            in_db = _yn(db_records.get(d["rel"], False))
            print(f"  ⚠ {short:<{col-2}}  {_yn(d['has_canon']):<12}  {in_db}")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remove duplicate book files (and DB records) from the organised library.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Actually delete safe duplicates. Without this flag the script is a dry-run.",
    )
    args = parser.parse_args()
    dry_run = not args.delete

    print("=" * 60)
    print("  Book Deduplicator")
    print(f"  Library : {ORGANIZED_DIR}")
    print(f"  DB      : {CACHE_DB}")
    print(f"  Mode    : {'DRY-RUN (pass --delete to apply)' if dry_run else 'LIVE — will delete safe duplicates'}")
    print("=" * 60)

    if not ORGANIZED_DIR.exists():
        print(f"\n  ERROR: Organised library not found at {ORGANIZED_DIR}")
        print("  Run organize_books.py first.")
        sys.exit(1)

    # ------------------------------------------------------------------
    print("\n  Scanning for duplicates …")
    duplicates = find_duplicates(ORGANIZED_DIR)

    if not duplicates:
        print("  Nothing to do — no duplicate files found.\n")
        sys.exit(0)

    safe       = [d for d in duplicates if d["safe"]]
    suspicious = [d for d in duplicates if not d["safe"]]

    # ------------------------------------------------------------------
    # Open DB (optional — library might exist without DB)
    con = None
    if CACHE_DB.exists():
        con = sqlite3.connect(CACHE_DB)
        con.row_factory = sqlite3.Row
    else:
        print("  WARNING: Cache DB not found — will only delete files, not DB records.\n")

    # Pre-fetch which duplicates have a DB record (for the report)
    db_records: dict[str, bool] = {}
    if con:
        for d in duplicates:
            db_records[d["rel"]] = db_lookup_by_rel(con, d["rel"]) is not None

    # ------------------------------------------------------------------
    print(f"\n  Found {len(duplicates)} duplicate-pattern file(s): "
          f"{len(safe)} safe to delete, {len(suspicious)} suspicious.")
    print_report(duplicates, db_records)

    orphans = [d for d in safe if not d["has_canon"]]
    if orphans:
        print(f"  NOTE: {len(orphans)} safe duplicate(s) have no canonical copy on disk")
        print("  (the canonical may have been moved or renamed — safe to remove).\n")

    if suspicious:
        print(f"  ⚠  {len(suspicious)} file(s) match the duplicate pattern but have a")
        print("  DIFFERENT FILE SIZE than their canonical copy.")
        print("  These are NEVER auto-deleted — please review them manually.\n")

    if dry_run:
        print("  DRY-RUN complete — nothing was changed.")
        print("  Re-run with --delete to delete the safe duplicates.\n")
        if con:
            con.close()
        sys.exit(0)

    # ------------------------------------------------------------------
    # Live run — only process safe duplicates
    # ------------------------------------------------------------------
    if not safe:
        print("  Nothing to delete — all duplicates are suspicious (different size).\n")
        if con:
            con.close()
        sys.exit(0)

    print(f"  Deleting {len(safe)} safe duplicate(s) …\n")
    deleted_files = 0
    deleted_db    = 0
    errors        = 0

    for d in safe:
        path = d["path"]
        rel  = d["rel"]

        try:
            path.unlink()
            deleted_files += 1
            print(f"  [DELETED]  {rel}")
        except Exception as e:
            errors += 1
            print(f"  [ERROR]    {rel}  —  {e}")
            continue

        if con and db_records.get(rel):
            if delete_from_db(con, rel):
                deleted_db += 1
                print(f"             └─ removed from DB")

        for parent in [path.parent, path.parent.parent]:
            try:
                if parent != ORGANIZED_DIR and not any(parent.iterdir()):
                    parent.rmdir()
                    print(f"             └─ removed empty dir: {parent.relative_to(ORGANIZED_DIR)}")
            except Exception:
                pass

    if con:
        con.close()

    print(f"\n  ── Summary ──────────────────────────────────")
    print(f"  Files deleted    : {deleted_files}")
    print(f"  DB rows removed  : {deleted_db}")
    if suspicious:
        print(f"  Skipped (⚠ diff size) : {len(suspicious)}  — review manually")
    if errors:
        print(f"  Errors           : {errors}")
    print()


if __name__ == "__main__":
    main()
