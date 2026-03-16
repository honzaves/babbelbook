"""
cache.py — SQLite-backed storage for two purposes:
  1. API result cache  (table: cache)  — Google Books, Open Library, isbnlib, Ollama lookups
  2. Book records      (table: books)  — final processing result for every book

Thread-safe: all writes are serialised via _db_lock.
"""

import json
import sqlite3
import threading
import time

from config import CACHE_DB, ORGANIZED_DIR

_db_lock = threading.Lock()


def _db() -> sqlite3.Connection:
    ORGANIZED_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(CACHE_DB)
    con.execute("""
        CREATE TABLE IF NOT EXISTS cache (
            key  TEXT PRIMARY KEY,
            val  TEXT,
            ts   INTEGER
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS books (
            original_path  TEXT PRIMARY KEY,
            title          TEXT,
            author         TEXT,
            language       TEXT,
            genres         TEXT,   -- JSON array: all genres found across all sources
            directory      TEXT,   -- top-level folder: cookbooks / reading / etc.
            relative_path  TEXT,   -- path relative to books_organized/
            confidence     INTEGER,
            sources        TEXT,   -- pipe-separated list
            file_size_bytes INTEGER,
            ts             INTEGER
        )
    """)
    con.commit()
    return con


# -- API result cache ---------------------------------------------------------

def cache_get(key: str):
    con = _db()
    try:
        row = con.execute("SELECT val FROM cache WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None
    except Exception:
        return None
    finally:
        con.close()


def cache_set(key: str, val):
    try:
        with _db_lock:
            con = _db()
            try:
                con.execute(
                    "INSERT OR REPLACE INTO cache (key, val, ts) VALUES (?,?,?)",
                    (key, json.dumps(val), int(time.time()))
                )
                con.commit()
            finally:
                con.close()
    except Exception:
        pass


# -- Book records -------------------------------------------------------------

def book_upsert(
    original_path: str,
    title: str,
    author: str,
    language: str,
    all_genres: list,
    directory: str,
    relative_path: str,
    confidence: int,
    sources: list,
    file_size_bytes: int = 0,
):
    """Insert or update the processed result for a book."""
    try:
        with _db_lock:
            con = _db()
            try:
                con.execute(
                    """
                    INSERT OR REPLACE INTO books
                      (original_path, title, author, language, genres,
                       directory, relative_path, confidence, sources, file_size_bytes, ts)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        original_path,
                        title,
                        author,
                        language,
                        json.dumps(all_genres),
                        directory,
                        relative_path,
                        confidence,
                        "|".join(sources),
                        file_size_bytes,
                        int(time.time()),
                    ),
                )
                con.commit()
            finally:
                con.close()
    except Exception as e:
        print(f"  [cache] book_upsert error: {e}")


def book_get(original_path: str) -> dict | None:
    con = _db()
    try:
        row = con.execute(
            "SELECT * FROM books WHERE original_path=?", (original_path,)
        ).fetchone()
        if not row:
            return None
        cols = [
            "original_path", "title", "author", "language", "genres",
            "directory", "relative_path", "confidence", "sources", "file_size_bytes", "ts",
        ]
        d = dict(zip(cols, row))
        d["genres"] = json.loads(d["genres"])
        return d
    except Exception:
        return None
    finally:
        con.close()
