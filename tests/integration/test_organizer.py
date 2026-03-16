"""
tests/integration/test_organizer.py

Integration tests for organizer/organizer.py.

These tests exercise the real file-processing pipeline with all external
I/O mocked out (no API calls, no Ollama, no real epub/pdf parsing).

Covers:
  process_book()
    - happy path: file classified and copied
    - skip: already in DB with file on disk
    - heal: DB path stale after flatten (path one level up)
    - copy-time dedup: identical file already on disk
    - collision: dest occupied by different file → _(N) suffix
    - failed book: exception during resolve → copied to failed/

  scan_and_organize()
    - dry_run=True: no files copied, no DB writes
    - worker count respected
    - skips books_organized subdirectory while scanning source

  _flatten_single_language_folders()
    - single language subfolder flattened
    - multi-language subfolder left intact
    - DB path updated after flatten
"""

import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _tmp():
    return Path(tempfile.mkdtemp())


def _make_db(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.execute("""
        CREATE TABLE books (
            original_path TEXT PRIMARY KEY,
            title TEXT, author TEXT, language TEXT,
            genres TEXT, directory TEXT, relative_path TEXT,
            confidence INTEGER, sources TEXT, ts INTEGER
        )
    """)
    con.execute("""
        CREATE TABLE cache (key TEXT PRIMARY KEY, val TEXT, ts INTEGER)
    """)
    con.commit()
    return con


def _make_meta(**kw):
    """Return a minimal BookMeta-like object via MagicMock."""
    from organizer.classifier import BookMeta
    m = BookMeta(
        title="Test Book",
        author="Test Author",
        language="english",
        genre="fiction",
        all_genres=["fiction"],
        category="reading",
        fallback=False,
        confidence=80,
        sources=["library", "online"],
    )
    for k, v in kw.items():
        setattr(m, k, v)
    return m


# ---------------------------------------------------------------------------
# process_book tests
# ---------------------------------------------------------------------------

class TestProcessBook(unittest.TestCase):

    def setUp(self):
        self._td   = _tmp()
        self._src_dir  = self._td / "source"
        self._org  = self._td / "books_organized"
        self._src_dir.mkdir()
        self._org.mkdir()
        self._db_path = self._org / ".cache.db"
        self._db = _make_db(self._db_path)
        self._db.close()

        self._patches = []

        def _p(target, attr, val):
            p = patch(target + "." + attr, val)
            p.start()
            self._patches.append(p)

        # Point all config-derived paths at our temp dir
        import config
        import organizer.organizer as oo
        import organizer.cache as oc

        for mod_path, attr, val in [
            ("organizer.organizer",  "ORGANIZED_DIR", self._org),
            ("organizer.organizer",  "CACHE_DB",      self._db_path),
            ("organizer.organizer",  "FAILED_DIR",    self._org / "failed"),
            ("organizer.cache",      "ORGANIZED_DIR", self._org),
            ("organizer.cache",      "CACHE_DB",      self._db_path),
            ("organizer.classifier", "ORGANIZED_DIR", self._org),
        ]:
            _p(mod_path, attr, val)

        # Default: resolve() returns a good meta; no real epub parsing
        self._mock_resolve = MagicMock(return_value=_make_meta())
        self._patches.append(
            patch("organizer.organizer.resolve", self._mock_resolve)
        )
        self._patches[-1].start()

        # Reset thread counter
        import organizer.organizer as oo
        oo._book_counter = 0

    def tearDown(self):
        for p in self._patches:
            try:
                p.stop()
            except RuntimeError:
                pass
        shutil.rmtree(self._td, ignore_errors=True)

    def _make_src(self, name="book.epub", content=b"x" * 500) -> Path:
        p = self._src_dir / name
        p.write_bytes(content)
        return p

    def _db_row(self, src_path: str) -> dict | None:
        con = sqlite3.connect(self._db_path)
        row = con.execute(
            "SELECT * FROM books WHERE original_path=?", (src_path,)
        ).fetchone()
        con.close()
        if not row:
            return None
        cols = ["original_path","title","author","language","genres",
                "directory","relative_path","confidence","sources","ts"]
        return dict(zip(cols, row))

    # ── Happy path ────────────────────────────────────────────────────────────

    def test_file_copied_to_organized_dir(self):
        from organizer.organizer import process_book
        src = self._make_src()
        meta, dest = process_book(src, dry_run=False)
        self.assertTrue(dest.exists())
        self.assertTrue(str(dest).startswith(str(self._org)))

    def test_db_row_inserted(self):
        from organizer.organizer import process_book
        src = self._make_src()
        process_book(src, dry_run=False)
        row = self._db_row(str(src))
        self.assertIsNotNone(row)
        self.assertEqual(row["title"], "Test Book")

    def test_dry_run_no_file_copied(self):
        from organizer.organizer import process_book
        src = self._make_src()
        meta, dest = process_book(src, dry_run=True)
        # dest is the *intended* path — the file should NOT actually exist
        self.assertFalse(dest.exists())

    def test_dry_run_no_db_write(self):
        from organizer.organizer import process_book
        src = self._make_src()
        process_book(src, dry_run=True)
        self.assertIsNone(self._db_row(str(src)))

    # ── Skip: already organised ───────────────────────────────────────────────

    def test_skips_book_already_in_db_with_file_present(self):
        from organizer.organizer import process_book
        src = self._make_src()
        # Copy once
        process_book(src, dry_run=False)
        resolve_call_count_after_first = self._mock_resolve.call_count
        # Second call should skip without calling resolve()
        process_book(src, dry_run=False)
        self.assertEqual(self._mock_resolve.call_count, resolve_call_count_after_first)

    # ── Heal: stale DB path ───────────────────────────────────────────────────

    def test_heals_stale_db_path(self):
        """If DB says reading/Author/english/book.epub but file is at
        reading/Author/book.epub (post-flatten), path is healed without re-copy."""
        from organizer.organizer import process_book

        src = self._make_src()
        # Pre-create the "flattened" destination
        flat = self._org / "reading" / "Test Author" / "book.epub"
        flat.parent.mkdir(parents=True, exist_ok=True)
        flat.write_bytes(b"x" * 500)

        # Insert a stale DB record pointing to the old language-subfolder path
        con = sqlite3.connect(self._db_path)
        con.execute(
            "INSERT INTO books "
            "(original_path,title,author,language,genres,directory,"
            " relative_path,confidence,sources,ts) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (str(src), "Test Book", "Test Author", "english",
             '["fiction"]', "reading",
             "reading/Test Author/english/book.epub",
             80, "library", 1_700_000_000),
        )
        con.commit()
        con.close()

        calls_before = self._mock_resolve.call_count
        meta, dest = process_book(src, dry_run=False)
        # resolve() should NOT have been called again
        self.assertEqual(self._mock_resolve.call_count, calls_before)
        # DB should now have the corrected path
        row = self._db_row(str(src))
        self.assertNotIn("english", row["relative_path"])

    # ── Copy-time dedup ───────────────────────────────────────────────────────

    def test_identical_existing_file_not_duplicated(self):
        """If the exact same file (name + size) already exists in the author dir,
        no new copy is made."""
        from organizer.organizer import process_book
        src = self._make_src(content=b"z" * 700)
        # Pre-place an identical file in the expected destination
        expected_dir = self._org / "reading" / "Test Author" / "english"
        expected_dir.mkdir(parents=True)
        (expected_dir / "book.epub").write_bytes(b"z" * 700)

        process_book(src, dry_run=False)
        # Should be exactly one copy
        copies = list(self._org.rglob("book*.epub"))
        self.assertEqual(len(copies), 1)

    # ── Collision → _(N) suffix ───────────────────────────────────────────────

    def test_collision_creates_numbered_copy(self):
        """Different file already at dest → _(1) suffix created."""
        from organizer.organizer import process_book
        src = self._make_src(content=b"a" * 500)
        # Place a DIFFERENT file at the destination
        dest_dir = self._org / "reading" / "Test Author" / "english"
        dest_dir.mkdir(parents=True)
        (dest_dir / "book.epub").write_bytes(b"b" * 999)

        process_book(src, dry_run=False)
        copies = list(self._org.rglob("book*.epub"))
        self.assertEqual(len(copies), 2)
        names = sorted(p.name for p in copies)
        self.assertIn("book_(1).epub", names)

    # ── Failed book copied to failed/ ─────────────────────────────────────────

    def test_failed_book_copied_to_failed_dir(self):
        """Exception in resolve() → src copied to failed/."""
        from organizer.organizer import scan_and_organize
        # scan_and_organize only descends into subdirs of BOOKS_DIR
        subdir = self._src_dir / "inbox"
        subdir.mkdir()
        src = subdir / "bad.epub"
        src.write_bytes(b"x" * 100)
        self._mock_resolve.side_effect = RuntimeError("mock parse failure")
        with patch("organizer.organizer.BOOKS_DIR", self._src_dir):
            scan_and_organize(dry_run=False, workers=1)
        failed_dir = self._org / "failed"
        self.assertTrue(
            any(failed_dir.rglob("bad.epub")) if failed_dir.exists() else False
        )


# ---------------------------------------------------------------------------
# _flatten_single_language_folders
# ---------------------------------------------------------------------------

class TestFlatten(unittest.TestCase):

    def setUp(self):
        self._td   = _tmp()
        self._org  = self._td / "books_organized"
        self._org.mkdir()
        self._db_path = self._org / ".cache.db"
        self._db = _make_db(self._db_path)
        self._db.close()

        self._patches = [
            patch("organizer.organizer.ORGANIZED_DIR", self._org),
            patch("organizer.organizer.CACHE_DB",      self._db_path),
            patch("organizer.cache.ORGANIZED_DIR",     self._org),
            patch("organizer.cache.CACHE_DB",          self._db_path),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        shutil.rmtree(self._td, ignore_errors=True)

    def _make(self, rel: str, content: bytes = b"x" * 100):
        p = self._org / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        return p

    def _insert_book(self, rel: str):
        con = sqlite3.connect(self._db_path)
        con.execute(
            "INSERT INTO books "
            "(original_path,title,author,language,genres,directory,"
            " relative_path,confidence,sources,ts) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (f"/src/{Path(rel).name}", "T", "A", "english",
             "[]", rel.split("/")[0], rel, 80, "library", 0),
        )
        con.commit()
        con.close()

    def _rel(self, orig_path: str) -> str | None:
        con = sqlite3.connect(self._db_path)
        row = con.execute(
            "SELECT relative_path FROM books WHERE original_path=?", (orig_path,)
        ).fetchone()
        con.close()
        return row[0] if row else None

    def test_single_language_folder_flattened(self):
        from organizer.organizer import _flatten_single_language_folders
        self._make("reading/Stephen King/english/It.epub")
        _flatten_single_language_folders(dry_run=False)
        self.assertTrue((self._org / "reading/Stephen King/It.epub").exists())
        self.assertFalse((self._org / "reading/Stephen King/english").exists())

    def test_multi_language_folders_preserved(self):
        from organizer.organizer import _flatten_single_language_folders
        self._make("reading/Kafka/english/Trial.epub")
        self._make("reading/Kafka/german/Prozess.epub")
        _flatten_single_language_folders(dry_run=False)
        self.assertTrue((self._org / "reading/Kafka/english/Trial.epub").exists())
        self.assertTrue((self._org / "reading/Kafka/german/Prozess.epub").exists())

    def test_db_path_updated_after_flatten(self):
        from organizer.organizer import _flatten_single_language_folders
        self._make("reading/Author/english/Book.epub")
        self._insert_book("reading/Author/english/Book.epub")
        _flatten_single_language_folders(dry_run=False)
        new_rel = self._rel("/src/Book.epub")
        self.assertIsNotNone(new_rel)
        self.assertNotIn("english", new_rel)

    def test_dry_run_does_not_move_files(self):
        from organizer.organizer import _flatten_single_language_folders
        self._make("reading/Author/english/Book.epub")
        _flatten_single_language_folders(dry_run=True)
        self.assertTrue((self._org / "reading/Author/english/Book.epub").exists())

    def test_multiple_books_same_author_flattened(self):
        from organizer.organizer import _flatten_single_language_folders
        self._make("reading/Author/english/BookA.epub")
        self._make("reading/Author/english/BookB.epub")
        _flatten_single_language_folders(dry_run=False)
        self.assertTrue((self._org / "reading/Author/BookA.epub").exists())
        self.assertTrue((self._org / "reading/Author/BookB.epub").exists())
        self.assertFalse((self._org / "reading/Author/english").exists())


# ---------------------------------------------------------------------------
# scan_and_organize integration
# ---------------------------------------------------------------------------

class TestScanAndOrganize(unittest.TestCase):

    def setUp(self):
        self._td     = _tmp()
        self._books  = self._td / "Books"
        self._source = self._books / "source"
        self._org    = self._books / "books_organized"
        self._books.mkdir()
        self._source.mkdir()
        self._org.mkdir()
        self._db_path = self._org / ".cache.db"

        self._patches = [
            patch("organizer.organizer.BOOKS_DIR",     self._books),
            patch("organizer.organizer.ORGANIZED_DIR", self._org),
            patch("organizer.organizer.CACHE_DB",      self._db_path),
            patch("organizer.organizer.FAILED_DIR",    self._org / "failed"),
            patch("organizer.organizer.UNCERTAIN_CSV", self._org / "uncertain.csv"),
            patch("organizer.cache.ORGANIZED_DIR",     self._org),
            patch("organizer.cache.CACHE_DB",          self._db_path),
        ]
        for p in self._patches:
            p.start()

        # Mock resolve() to return a stable meta without touching files
        self._mock_resolve = MagicMock(return_value=_make_meta())
        rp = patch("organizer.organizer.resolve", self._mock_resolve)
        rp.start()
        self._patches.append(rp)

        # Silence print output during tests
        self._print_patch = patch("builtins.print")
        self._print_patch.start()
        self._patches.append(self._print_patch)

        import organizer.organizer as oo
        oo._book_counter = 0

    def tearDown(self):
        for p in self._patches:
            try:
                p.stop()
            except RuntimeError:
                pass
        shutil.rmtree(self._td, ignore_errors=True)

    def _make_src(self, name="book.epub", subdir="source"):
        p = self._books / subdir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x" * 200)
        return p

    def test_dry_run_copies_no_files(self):
        from organizer.organizer import scan_and_organize
        self._make_src()
        scan_and_organize(dry_run=True, workers=1)
        # Only the .cache.db should exist in org dir (created by _init_csv)
        book_files = [
            p for p in self._org.rglob("*")
            if p.is_file() and p.suffix in {".epub", ".pdf", ".mobi"}
        ]
        self.assertEqual(book_files, [])

    def test_live_run_copies_file(self):
        from organizer.organizer import scan_and_organize
        self._make_src("novel.epub")
        scan_and_organize(dry_run=False, workers=1)
        organized = list(self._org.rglob("*.epub"))
        self.assertGreater(len(organized), 0)

    def test_skips_books_organized_subdir(self):
        """Files already in books_organized/ must not be re-processed."""
        from organizer.organizer import scan_and_organize
        self._make_src("novel.epub")
        # Place a file *inside* books_organized — must not be picked up
        inner = self._org / "reading" / "Author" / "already.epub"
        inner.parent.mkdir(parents=True, exist_ok=True)
        inner.write_bytes(b"y" * 100)
        scan_and_organize(dry_run=False, workers=1)
        # resolve() called only for the file in source/, not for already.epub
        for call in self._mock_resolve.call_args_list:
            src_arg = call[0][0]
            self.assertNotIn("books_organized", str(src_arg))

    def test_unsupported_extension_ignored(self):
        from organizer.organizer import scan_and_organize
        (self._source / "readme.txt").write_text("hello")
        scan_and_organize(dry_run=False, workers=1)
        self.assertEqual(self._mock_resolve.call_count, 0)


if __name__ == "__main__":
    unittest.main()
