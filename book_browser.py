#!/usr/bin/env python3
"""
book_browser.py — browser-based UI for the book organiser cache.

Usage:
  pip install flask
  python book_browser.py
  open http://localhost:5000

Structure:
  book_browser.py          ← this file (entry point)
  browser/
    db.py                  ← SQLite helpers + path constants
    routes_read.py         ← Blueprint: all GET /api/* endpoints
    routes_write.py        ← Blueprint: all PATCH /api/* endpoints
    ui/
      style.py             ← CSS
      script.py            ← JavaScript
      layout.py            ← HTML shell, assembles the full page
    query_cache.py         ← standalone CLI cache inspector
"""

try:
    from flask import Flask, render_template_string
except ImportError:
    print("Flask not installed. Run:  pip install flask")
    raise SystemExit(1)

from browser.db           import CACHE_DB
from browser.routes_read  import read_bp
from browser.routes_write import write_bp
from browser.ui.layout    import build_html

app = Flask(__name__)
app.register_blueprint(read_bp)
app.register_blueprint(write_bp)

_PAGE = build_html()   # assemble once at startup


@app.route("/")
def index():
    return render_template_string(_PAGE, db_path=str(CACHE_DB))


if __name__ == "__main__":
    if not CACHE_DB.exists():
        print(f"WARNING: Cache not found at {CACHE_DB}")
        print("Run organize_books.py first.\n")
    print("=" * 45)
    print("  Book Library Browser")
    print(f"  DB : {CACHE_DB}")
    print("  →  http://localhost:5000")
    print("=" * 45)
    app.run(debug=False, port=5000)
