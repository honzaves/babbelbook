"""
tests/conftest.py — shared test helpers and fixture factories.

Written for stdlib unittest; also compatible with pytest if installed later.

Usage in tests:
    from tests.conftest import make_library, make_flask_client
"""

import json
import shutil
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

# ---------------------------------------------------------------------------
# DB schema helpers
# ---------------------------------------------------------------------------

_CREATE_BOOKS = """
CREATE TABLE IF NOT EXISTS books (
    original_path  TEXT PRIMARY KEY,
    title          TEXT,
    author         TEXT,
    language       TEXT,
    genres         TEXT,
    directory      TEXT,
    relative_path  TEXT,
    confidence     INTEGER,
    sources        TEXT,
    ts             INTEGER
)
"""

_CREATE_CACHE = """
CREATE TABLE IF NOT EXISTS cache (
    key  TEXT PRIMARY KEY,
    val  TEXT,
    ts   INTEGER
)
"""


def create_db(path: Path) -> sqlite3.Connection:
    """Create the two-table schema and return an open connection."""
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute(_CREATE_BOOKS)
    con.execute(_CREATE_CACHE)
    con.commit()
    return con


def insert_book(con: sqlite3.Connection, **kw) -> None:
    """Insert one book row; all fields have sensible defaults."""
    defaults = dict(
        original_path="/src/book.epub",
        title="Test Book",
        author="Test Author",
        language="english",
        genres=json.dumps(["fiction"]),
        directory="reading",
        relative_path="reading/Test Author/book.epub",
        confidence=80,
        sources="library|online",
        ts=1_700_000_000,
    )
    defaults.update(kw)
    con.execute(
        "INSERT OR REPLACE INTO books "
        "(original_path, title, author, language, genres, directory, "
        " relative_path, confidence, sources, ts) "
        "VALUES (:original_path,:title,:author,:language,:genres,:directory,"
        "        :relative_path,:confidence,:sources,:ts)",
        defaults,
    )
    con.commit()


# ---------------------------------------------------------------------------
# Temporary library builder
# ---------------------------------------------------------------------------

class TempLibrary:
    """
    Context manager that creates a self-contained temporary library on disk.

    Attributes
    ----------
    root        — the tmp directory (pathlib.Path)
    org         — root/books_organized
    db_path     — root/books_organized/.cache.db
    db          — open sqlite3 connection (row_factory = sqlite3.Row)
    """

    def __init__(self):
        self._td = None

    def __enter__(self):
        self._td = tempfile.mkdtemp()
        self.root = Path(self._td)
        self.org = self.root / "books_organized"
        self.org.mkdir()
        self.db_path = self.org / ".cache.db"
        self.db = create_db(self.db_path)
        return self

    def __exit__(self, *_):
        self.db.close()
        shutil.rmtree(self._td, ignore_errors=True)

    # convenience helpers ------------------------------------------------

    def add_book_file(self, rel_path: str, content: bytes = b"x" * 500) -> Path:
        """Create a real file inside org/ and return its absolute path."""
        p = self.org / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        return p

    def add_book_record(self, **kw) -> None:
        insert_book(self.db, **kw)


def make_library():
    """Return a new TempLibrary context manager."""
    return TempLibrary()


# ---------------------------------------------------------------------------
# Flask test client factory
# ---------------------------------------------------------------------------

def make_flask_client(lib: TempLibrary):
    """
    Return a Flask test client whose routes are wired to *lib*.

    Patches CACHE_DB and ORGANIZED_DIR in both browser.db and the route
    modules so every DB access and filesystem walk hits the tmp library.
    """
    import browser.db as bdb
    import browser.routes_read as rr
    import browser.routes_write as rw
    from flask import Flask
    from browser.routes_read import read_bp
    from browser.routes_write import write_bp
    from browser.ui.layout import build_html

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(read_bp)
    app.register_blueprint(write_bp)

    # Register a minimal index route matching book_browser.py
    @app.route("/")
    def index():
        html = build_html()
        html = html.replace("{{ db_path }}", str(lib.db_path))
        return html

    patches = [
        patch.object(bdb,  "CACHE_DB",      lib.db_path),
        patch.object(bdb,  "ORGANIZED_DIR", lib.org),
        patch.object(rr,   "ORGANIZED_DIR", lib.org),
        patch.object(rw,   "ORGANIZED_DIR", lib.org),
    ]
    for p in patches:
        p.start()

    client = app.test_client()
    client._test_patches = patches  # keep references alive
    return client


def stop_patches(client) -> None:
    """Call after each integration test to clean up mock patches."""
    for p in getattr(client, "_test_patches", []):
        p.stop()
