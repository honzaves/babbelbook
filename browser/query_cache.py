#!/usr/bin/env python3
"""
query_cache.py — interactive tool to inspect the Babbelbook's .cache.db

The database has two tables:
  books  — one row per processed book (title, author, genres, directory, path, ...)
  cache  — API lookup results (Google Books, Open Library, isbnlib, Ollama)

Usage:
  python query_cache.py                      # interactive menu
  python query_cache.py stats                # summary statistics
  python query_cache.py search "King"        # search books by any field
  python query_cache.py genre "thriller"     # list books by genre
  python query_cache.py dir "reading"        # list books in a directory
  python query_cache.py dump                 # dump books table as JSON
  python query_cache.py cache-search "King"  # search raw API cache entries
"""

import json
import sys
from datetime import datetime
from pathlib import Path

CACHE_DB = Path.home() / "Documents" / "Books" / "books_organized" / ".cache.db"

try:
    import sqlite3
except ImportError:
    print("sqlite3 not available")
    sys.exit(1)


# -- Connection ---------------------------------------------------------------

def _connect():
    if not CACHE_DB.exists():
        print(f"ERROR: Cache not found at {CACHE_DB}")
        print("Run organize_books.py first to generate the cache.")
        sys.exit(1)
    return sqlite3.connect(CACHE_DB)


def _fmt_ts(ts):
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "—"


# -- Books table helpers ------------------------------------------------------

def _book_rows(con, where="", params=()):
    sql = f"""
        SELECT original_path, title, author, language, genres,
               directory, relative_path, confidence, sources, ts
        FROM books {where}
        ORDER BY ts DESC
    """
    return con.execute(sql, params).fetchall()


def _print_book(row, wide=False):
    (orig, title, author, language, genres_json,
     directory, rel_path, confidence, sources, ts) = row
    try:
        genres = json.loads(genres_json) if genres_json else []
    except Exception:
        genres = []

    print(f"\n  Title      : {title or '—'}")
    print(f"  Author     : {author or '—'}")
    print(f"  Language   : {language or '—'}")
    print(f"  Genres     : {', '.join(genres) if genres else '—'}")
    print(f"  Directory  : {directory or '—'}")
    print(f"  Path       : {rel_path or '—'}")
    print(f"  Confidence : {confidence}/100")
    print(f"  Sources    : {sources or '—'}")
    print(f"  Cached     : {_fmt_ts(ts)}")
    if wide:
        print(f"  Original   : {orig}")


# -- Commands — books table ---------------------------------------------------

def cmd_stats(con):
    total = con.execute("SELECT COUNT(*) FROM books").fetchone()[0]
    cache_total = con.execute("SELECT COUNT(*) FROM cache").fetchone()[0]

    print(f"\n  Cache file : {CACHE_DB}")
    print(f"\n  {'─'*40}")
    print(f"  BOOKS TABLE  ({total} books processed)")
    print(f"  {'─'*40}")

    # By directory
    rows = con.execute(
        "SELECT directory, COUNT(*) as n FROM books GROUP BY directory ORDER BY n DESC"
    ).fetchall()
    print(f"\n  {'Directory':<30}  {'Books':>6}")
    print(f"  {'─'*30}  {'─'*6}")
    for d, n in rows:
        print(f"  {(d or '—'):<30}  {n:>6}")

    # By language
    rows = con.execute(
        "SELECT language, COUNT(*) as n FROM books GROUP BY language ORDER BY n DESC"
    ).fetchall()
    print(f"\n  {'Language':<30}  {'Books':>6}")
    print(f"  {'─'*30}  {'─'*6}")
    for lang, n in rows:
        print(f"  {(lang or '—'):<30}  {n:>6}")

    # Top genres (explode JSON arrays)
    all_rows = con.execute("SELECT genres FROM books WHERE genres IS NOT NULL").fetchall()
    genre_counts = {}
    for (g_json,) in all_rows:
        try:
            for g in json.loads(g_json):
                genre_counts[g] = genre_counts.get(g, 0) + 1
        except Exception:
            pass
    if genre_counts:
        top = sorted(genre_counts.items(), key=lambda x: -x[1])[:15]
        print(f"\n  {'Genre (top 15)':<30}  {'Count':>6}")
        print(f"  {'─'*30}  {'─'*6}")
        for g, n in top:
            print(f"  {g:<30}  {n:>6}")

    # Confidence distribution
    print(f"\n  Confidence distribution:")
    for lo, hi, label in [(80, 100, "High (80-100)"),
                           (55, 79,  "Medium (55-79)"),
                           (35, 54,  "Low (35-54)"),
                           (0,  34,  "Very low (0-34)")]:
        n = con.execute(
            "SELECT COUNT(*) FROM books WHERE confidence BETWEEN ? AND ?", (lo, hi)
        ).fetchone()[0]
        print(f"    {label:<20} : {n}")

    print(f"\n  {'─'*40}")
    print(f"  API CACHE TABLE  ({cache_total} lookup entries)")
    for prefix, label in [("gb", "Google Books"), ("ol", "Open Library"),
                           ("isbn", "isbnlib"), ("ollama", "Ollama")]:
        n = con.execute(
            "SELECT COUNT(*) FROM cache WHERE key LIKE ?", (f"{prefix}:%",)
        ).fetchone()[0]
        print(f"    {label:<20} : {n}")


def cmd_search_books(con, query):
    q = f"%{query}%"
    rows = con.execute("""
        SELECT original_path, title, author, language, genres,
               directory, relative_path, confidence, sources, ts
        FROM books
        WHERE title LIKE ? OR author LIKE ? OR genres LIKE ?
           OR directory LIKE ? OR relative_path LIKE ? OR language LIKE ?
        ORDER BY ts DESC
    """, (q, q, q, q, q, q)).fetchall()

    print(f"\n  Found {len(rows)} book(s) matching '{query}'")
    for row in rows[:30]:
        _print_book(row)
    if len(rows) > 30:
        print(f"\n  ... and {len(rows)-30} more. Refine your search.")


def cmd_genre(con, genre):
    q = f'%"{genre}"%'
    rows = _book_rows(con, "WHERE genres LIKE ?", (q,))
    print(f"\n  Books with genre '{genre}' : {len(rows)}")
    for row in rows[:30]:
        _print_book(row)
    if len(rows) > 30:
        print(f"\n  ... and {len(rows)-30} more.")


def cmd_directory(con, directory):
    rows = _book_rows(con, "WHERE directory = ?", (directory,))
    print(f"\n  Books in directory '{directory}' : {len(rows)}")
    for row in rows[:30]:
        _print_book(row)
    if len(rows) > 30:
        print(f"\n  ... and {len(rows)-30} more.")


def cmd_dump_books(con):
    rows = _book_rows(con)
    out  = []
    for (orig, title, author, language, genres_json,
         directory, rel_path, confidence, sources, ts) in rows:
        out.append({
            "original_path": orig,
            "title":         title,
            "author":        author,
            "language":      language,
            "genres":        json.loads(genres_json) if genres_json else [],
            "directory":     directory,
            "relative_path": rel_path,
            "confidence":    confidence,
            "sources":       sources,
            "cached":        _fmt_ts(ts),
        })
    print(json.dumps(out, indent=2, ensure_ascii=False))


# -- Commands — API cache table -----------------------------------------------

def cmd_cache_search(con, query):
    q = f"%{query}%"
    rows = con.execute(
        "SELECT key, val, ts FROM cache WHERE key LIKE ? OR val LIKE ? ORDER BY ts DESC",
        (q, q)
    ).fetchall()
    print(f"\n  Found {len(rows)} API cache entry(ies) matching '{query}'")
    for key, val, ts in rows[:20]:
        try:
            data = json.loads(val)
        except Exception:
            data = val
        print(f"\n  Key    : {key}")
        print(f"  Cached : {_fmt_ts(ts)}")
        print(f"  Data   : {json.dumps(data, ensure_ascii=False)[:200]}")


# -- Interactive menu ---------------------------------------------------------

def interactive(con):
    while True:
        print("\n" + "=" * 55)
        print("  Babbelbook — Cache Explorer")
        print("=" * 55)
        print("  ── Books ──────────────────────────────────────")
        print("  1. Statistics & overview")
        print("  2. Search books (title / author / genre / path)")
        print("  3. Browse by genre")
        print("  4. Browse by directory (cookbooks / reading / …)")
        print("  5. List all books (newest first)")
        print("  6. Dump books table as JSON")
        print("  ── API Cache ───────────────────────────────────")
        print("  7. Search raw API cache entries")
        print("  ────────────────────────────────────────────────")
        print("  0. Exit")
        print("-" * 55)
        choice = input("  Choice: ").strip()

        if choice == "0":
            break
        elif choice == "1":
            cmd_stats(con)
        elif choice == "2":
            q = input("  Search term: ").strip()
            if q:
                cmd_search_books(con, q)
        elif choice == "3":
            q = input("  Genre (e.g. thriller, yoga, biography): ").strip()
            if q:
                cmd_genre(con, q)
        elif choice == "4":
            print("  Directories: cookbooks / reading / home_improvement / "
                  "sport_workout_yoga_health / other / pdf / unknown / failed")
            q = input("  Directory: ").strip()
            if q:
                cmd_directory(con, q)
        elif choice == "5":
            rows = _book_rows(con)
            print(f"\n  {len(rows)} total books (showing newest 20):")
            for row in rows[:20]:
                _print_book(row)
            if len(rows) > 20:
                print(f"\n  ... {len(rows)-20} more. Use Search to filter.")
        elif choice == "6":
            cmd_dump_books(con)
        elif choice == "7":
            q = input("  Search term: ").strip()
            if q:
                cmd_cache_search(con, q)
        else:
            print("  Unknown option.")

        input("\n  Press Enter to continue...")


# -- Entry point --------------------------------------------------------------

if __name__ == "__main__":
    con = _connect()

    if len(sys.argv) < 2:
        interactive(con)
    elif sys.argv[1] == "stats":
        cmd_stats(con)
    elif sys.argv[1] == "search" and len(sys.argv) > 2:
        cmd_search_books(con, " ".join(sys.argv[2:]))
    elif sys.argv[1] == "genre" and len(sys.argv) > 2:
        cmd_genre(con, sys.argv[2])
    elif sys.argv[1] == "dir" and len(sys.argv) > 2:
        cmd_directory(con, sys.argv[2])
    elif sys.argv[1] == "dump":
        cmd_dump_books(con)
    elif sys.argv[1] == "cache-search" and len(sys.argv) > 2:
        cmd_cache_search(con, " ".join(sys.argv[2:]))
    else:
        print(__doc__)

    con.close()
