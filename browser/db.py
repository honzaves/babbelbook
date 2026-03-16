"""
browser/db.py — lightweight SQLite helpers for read-only browser access.

All routes import _db(), _fmt_ts(), and _row_to_dict() from here.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

CACHE_DB      = Path.home() / "Documents" / "Books" / "books_organized" / ".cache.db"
ORGANIZED_DIR = CACHE_DB.parent
MAIN_DIRS     = ["cookbooks", "reading", "home_improvement", "sport_workout_yoga_health",
                 "psychology", "leadership", "politics", "history", "textbook", "other"]


def _db() -> sqlite3.Connection | None:
    if not CACHE_DB.exists():
        return None
    con = sqlite3.connect(CACHE_DB)
    con.row_factory = sqlite3.Row
    # Migrate: add file_size_bytes if it doesn't exist yet
    cols = {row[1] for row in con.execute("PRAGMA table_info(books)").fetchall()}
    if "file_size_bytes" not in cols:
        con.execute("ALTER TABLE books ADD COLUMN file_size_bytes INTEGER DEFAULT 0")
        con.commit()
    return con


def _fmt_ts(ts) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "—"


def _row_to_dict(row) -> dict:
    d = dict(row)
    try:
        d["genres"] = json.loads(d.get("genres") or "[]")
    except Exception:
        d["genres"] = []
    if "ts" in d:
        d["ts_fmt"] = _fmt_ts(d["ts"])
    return d
