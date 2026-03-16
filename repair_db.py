#!/usr/bin/env python3
"""
repair_db.py — reconcile the Babbelbook database against the filesystem.

Two classes of inconsistency are detected and reported:

  STALE   — DB rows whose relative_path no longer exists on disk.
             Live fix: delete the row from the database.

  ORPHAN  — Files on disk (inside ORGANIZED_DIR) that have no DB row.
             Live fix: move the file to REPROCESS_DIR so it can be
             re-ingested by organize_books.py.

REPROCESS_DIR is created automatically when needed.  Files moved there
keep their original filename; a _(N) suffix is appended if a name clash
would occur.

Usage:
    python repair_db.py               # dry-run — report only, change nothing
    python repair_db.py --fix         # live run — apply all fixes
    python repair_db.py --help
"""

import argparse
import sqlite3
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Import settings from config.py
# ---------------------------------------------------------------------------
try:
    from config import (
        BOOKS_DIR,
        ORGANIZED_DIR,
        CACHE_DB,
        SUPPORTED_EXTS,
        REPROCESS_DIR,
    )
except ImportError as exc:
    print(f"ERROR: could not import from config.py — {exc}")
    print("Run this script from the babbelbook project root.")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Filesystem scan
# ---------------------------------------------------------------------------

#: Subdirectories of ORGANIZED_DIR that are never book-storage folders and
#: should be excluded from the orphan scan to avoid false positives.
_SKIP_DIRS = {"___to_reprocess"}


def _all_db_relative_paths(con: sqlite3.Connection) -> set[str]:
    """Return every relative_path value stored in the books table."""
    rows = con.execute("SELECT relative_path FROM books").fetchall()
    return {r[0] for r in rows if r[0]}


def _all_fs_relative_paths(root: Path) -> set[str]:
    """
    Walk *root* and return the relative path (as str) of every supported
    e-book file found, excluding the _SKIP_DIRS subtrees.
    """
    found: list[str] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() not in SUPPORTED_EXTS:
            continue
        # Skip excluded subdirectories
        try:
            relative = p.relative_to(root)
        except ValueError:
            continue
        if relative.parts[0] in _SKIP_DIRS:
            continue
        found.append(str(relative))
    return set(found)


# ---------------------------------------------------------------------------
# Stale-row helpers
# ---------------------------------------------------------------------------

def find_stale(db_paths: set[str], fs_paths: set[str]) -> list[str]:
    """DB rows whose file is missing from the filesystem."""
    return sorted(db_paths - fs_paths)


def delete_stale_rows(con: sqlite3.Connection, stale: list[str]) -> int:
    """Delete all stale rows and return the number removed."""
    removed = 0
    for rel in stale:
        cur = con.execute("DELETE FROM books WHERE relative_path = ?", (rel,))
        removed += cur.rowcount
    con.commit()
    return removed


# ---------------------------------------------------------------------------
# Orphan helpers
# ---------------------------------------------------------------------------

def find_orphans(db_paths: set[str], fs_paths: set[str]) -> list[str]:
    """Files on disk that have no corresponding DB row."""
    return sorted(fs_paths - db_paths)


def _safe_dest(dest_dir: Path, filename: str) -> Path:
    """
    Return a path inside dest_dir for a file named *filename* that does not
    collide with any existing file.  Appends _(1), _(2) … to the stem when
    a collision is detected.
    """
    candidate = dest_dir / filename
    if not candidate.exists():
        return candidate
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    n = 1
    while True:
        candidate = dest_dir / f"{stem}_({n}){suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def move_orphans(orphans: list[str], organized_dir: Path,
                 reprocess_dir: Path) -> tuple[int, list[str]]:
    """
    Move each orphan file to *reprocess_dir*.

    Returns (moved_count, error_messages).
    """
    reprocess_dir.mkdir(parents=True, exist_ok=True)
    moved = 0
    errors: list[str] = []
    for rel in orphans:
        src = organized_dir / rel
        if not src.exists():
            errors.append(f"vanished before move: {rel}")
            continue
        dest = _safe_dest(reprocess_dir, src.name)
        try:
            src.rename(dest)
            moved += 1
        except Exception as exc:
            errors.append(f"{rel}: {exc}")
    return moved, errors


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------

_COL = 68


def _truncate(s: str, width: int = _COL) -> str:
    return s if len(s) <= width else "…" + s[-(width - 1):]


def _print_section(title: str, items: list[str], prefix: str = "  ") -> None:
    print(f"\n{prefix}{title}")
    print(f"{prefix}{'-' * len(title)}")
    if items:
        for item in items:
            print(f"{prefix}  {_truncate(item)}")
    else:
        print(f"{prefix}  (none)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reconcile the Babbelbook database against the filesystem.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help=(
            "Apply fixes: delete stale DB rows and move orphan files to "
            "REPROCESS_DIR.  Without this flag the script is a dry-run."
        ),
    )
    args = parser.parse_args()
    dry_run = not args.fix

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------
    print("=" * 64)
    print("  Babbelbook — DB / Filesystem Repair")
    print(f"  Library     : {ORGANIZED_DIR}")
    print(f"  Database    : {CACHE_DB}")
    print(f"  Reprocess   : {REPROCESS_DIR}")
    print(f"  Mode        : {'DRY-RUN  (pass --fix to apply changes)' if dry_run else 'LIVE — changes will be applied'}")
    print("=" * 64)

    # ------------------------------------------------------------------
    # Pre-flight checks
    # ------------------------------------------------------------------
    if not ORGANIZED_DIR.exists():
        print(f"\n  ERROR: organised library not found at {ORGANIZED_DIR}")
        print("  Run organize_books.py first.\n")
        sys.exit(1)

    if not CACHE_DB.exists():
        print(f"\n  ERROR: database not found at {CACHE_DB}")
        print("  Run organize_books.py first.\n")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Gather data
    # ------------------------------------------------------------------
    print("\n  Scanning database …")
    con = sqlite3.connect(CACHE_DB)
    con.row_factory = sqlite3.Row

    db_paths = _all_db_relative_paths(con)
    print(f"  {len(db_paths)} row(s) in books table.")

    print("  Scanning filesystem …")
    fs_paths = _all_fs_relative_paths(ORGANIZED_DIR)
    print(f"  {len(fs_paths)} supported file(s) on disk.")

    # ------------------------------------------------------------------
    # Classify
    # ------------------------------------------------------------------
    stale   = find_stale(db_paths, fs_paths)
    orphans = find_orphans(db_paths, fs_paths)

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------
    print(f"\n  {'─' * 60}")
    print(f"  Stale DB rows (file missing from disk) : {len(stale)}")
    print(f"  Orphan files  (file not in database)   : {len(orphans)}")
    print(f"  {'─' * 60}")

    _print_section(
        "STALE — in DB but not on disk (rows will be deleted):",
        stale,
    )
    _print_section(
        f"ORPHAN — on disk but not in DB (files will be moved to {REPROCESS_DIR.name}/):",
        orphans,
    )

    if not stale and not orphans:
        print("\n  ✓  Database and filesystem are in sync — nothing to do.\n")
        con.close()
        sys.exit(0)

    # ------------------------------------------------------------------
    # Dry-run exit
    # ------------------------------------------------------------------
    if dry_run:
        print("\n  DRY-RUN complete — nothing was changed.")
        print("  Re-run with --fix to apply the changes shown above.\n")
        con.close()
        sys.exit(0)

    # ------------------------------------------------------------------
    # Live run
    # ------------------------------------------------------------------
    print("\n  Applying fixes …\n")
    total_errors: list[str] = []

    # 1. Remove stale DB rows
    if stale:
        removed = delete_stale_rows(con, stale)
        print(f"  [DB]  Deleted {removed} stale row(s).")

    # 2. Move orphan files to REPROCESS_DIR
    if orphans:
        moved, errors = move_orphans(orphans, ORGANIZED_DIR, REPROCESS_DIR)
        print(f"  [FS]  Moved {moved} orphan file(s) → {REPROCESS_DIR}")
        for err in errors:
            print(f"  [ERR] {err}")
        total_errors.extend(errors)

    con.close()

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print(f"\n  {'─' * 60}")
    print(f"  Stale rows deleted      : {len(stale)}")
    print(f"  Orphan files moved      : {len(orphans) - len(total_errors)}")
    if total_errors:
        print(f"  Errors                  : {len(total_errors)}")
    print(f"  {'─' * 60}")
    if orphans:
        print(f"\n  Orphan files are waiting in:\n    {REPROCESS_DIR}")
        print("  Run organize_books.py to re-ingest them into the library.\n")
    else:
        print()

    sys.exit(1 if total_errors else 0)


if __name__ == "__main__":
    main()
