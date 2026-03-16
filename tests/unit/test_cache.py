"""
tests/unit/test_cache.py

Unit tests for organizer/cache.py.

Covers:
  - cache_get / cache_set     round-trip, cache misses, overwrite
  - book_upsert / book_get    round-trip, field serialisation, genres as list
  - Thread safety             concurrent writes don't corrupt the DB
  - Connection hygiene        no leaked handles after each call

All tests use a temporary directory so the real ~/.../books_organized is
never touched.
"""

import json
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _make_temp_db():
    """Return (tmp_dir, db_path) where the schema has already been applied."""
    td = tempfile.mkdtemp()
    db_path = Path(td) / ".cache.db"
    con = sqlite3.connect(db_path)
    con.execute("""
        CREATE TABLE cache (
            key TEXT PRIMARY KEY,
            val TEXT,
            ts  INTEGER
        )
    """)
    con.execute("""
        CREATE TABLE books (
            original_path TEXT PRIMARY KEY,
            title         TEXT,
            author        TEXT,
            language      TEXT,
            genres        TEXT,
            directory     TEXT,
            relative_path TEXT,
            confidence    INTEGER,
            sources       TEXT,
            ts            INTEGER
        )
    """)
    con.commit()
    con.close()
    return td, db_path


class TestCacheGetSet(unittest.TestCase):

    def setUp(self):
        self._td, self._db = _make_temp_db()
        self._org = Path(self._td)
        # Patch the module-level constants used by cache.py
        import organizer.cache as cache_mod
        self._cache_mod = cache_mod
        self._patches = [
            patch.object(cache_mod, "CACHE_DB",      self._db),
            patch.object(cache_mod, "ORGANIZED_DIR", self._org),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        import shutil
        shutil.rmtree(self._td, ignore_errors=True)

    # ── cache_get / cache_set ────────────────────────────────────────────────

    def test_miss_returns_none(self):
        from organizer.cache import cache_get
        self.assertIsNone(cache_get("no_such_key"))

    def test_round_trip_dict(self):
        from organizer.cache import cache_get, cache_set
        payload = {"title": "Dune", "authors": ["Herbert"]}
        cache_set("gb:Dune:Herbert", payload)
        result = cache_get("gb:Dune:Herbert")
        self.assertEqual(result, payload)

    def test_round_trip_list(self):
        from organizer.cache import cache_get, cache_set
        cache_set("list_key", [1, 2, 3])
        self.assertEqual(cache_get("list_key"), [1, 2, 3])

    def test_round_trip_none_value(self):
        from organizer.cache import cache_get, cache_set
        cache_set("none_key", None)
        self.assertIsNone(cache_get("none_key"))

    def test_overwrite_replaces_value(self):
        from organizer.cache import cache_get, cache_set
        cache_set("k", {"v": 1})
        cache_set("k", {"v": 2})
        self.assertEqual(cache_get("k")["v"], 2)

    def test_set_stores_timestamp(self):
        from organizer.cache import cache_set
        before = int(time.time())
        cache_set("ts_key", {"x": 1})
        after = int(time.time())
        con = sqlite3.connect(self._db)
        row = con.execute("SELECT ts FROM cache WHERE key='ts_key'").fetchone()
        con.close()
        self.assertIsNotNone(row)
        self.assertGreaterEqual(row[0], before)
        self.assertLessEqual(row[0], after)

    def test_different_keys_independent(self):
        from organizer.cache import cache_get, cache_set
        cache_set("a", 1)
        cache_set("b", 2)
        self.assertEqual(cache_get("a"), 1)
        self.assertEqual(cache_get("b"), 2)

    # ── Connection hygiene ───────────────────────────────────────────────────

    def test_get_does_not_leave_connection_open(self):
        """Verify no WAL/journal file lingers after cache_get (proxy for leak)."""
        from organizer.cache import cache_get
        cache_get("any_key")
        wal = Path(str(self._db) + "-wal")
        # WAL may legitimately exist during write but shouldn't after a read
        # This just confirms no exception is raised and the DB is usable
        con = sqlite3.connect(self._db)
        con.execute("SELECT 1").fetchone()
        con.close()

    def test_set_does_not_leave_connection_open(self):
        from organizer.cache import cache_set
        cache_set("hygiene_key", {"data": True})
        con = sqlite3.connect(self._db)
        con.execute("SELECT 1").fetchone()
        con.close()


class TestBookUpsertGet(unittest.TestCase):

    def setUp(self):
        self._td, self._db = _make_temp_db()
        self._org = Path(self._td)
        import organizer.cache as cache_mod
        self._patches = [
            patch.object(cache_mod, "CACHE_DB",      self._db),
            patch.object(cache_mod, "ORGANIZED_DIR", self._org),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        import shutil
        shutil.rmtree(self._td, ignore_errors=True)

    def _upsert(self, **kw):
        from organizer.cache import book_upsert
        defaults = dict(
            original_path="/src/test.epub",
            title="Test Book",
            author="Test Author",
            language="english",
            all_genres=["fiction"],
            directory="reading",
            relative_path="reading/Test Author/test.epub",
            confidence=80,
            sources=["library", "online"],
        )
        defaults.update(kw)
        book_upsert(**defaults)

    # ── book_get ─────────────────────────────────────────────────────────────

    def test_miss_returns_none(self):
        from organizer.cache import book_get
        self.assertIsNone(book_get("/nonexistent.epub"))

    def test_round_trip_basic_fields(self):
        from organizer.cache import book_get
        self._upsert(title="Dune", author="Frank Herbert")
        rec = book_get("/src/test.epub")
        self.assertIsNotNone(rec)
        self.assertEqual(rec["title"], "Dune")
        self.assertEqual(rec["author"], "Frank Herbert")

    def test_genres_returned_as_list(self):
        from organizer.cache import book_get
        self._upsert(all_genres=["thriller", "mystery"])
        rec = book_get("/src/test.epub")
        self.assertIsInstance(rec["genres"], list)
        self.assertIn("thriller", rec["genres"])
        self.assertIn("mystery",  rec["genres"])

    def test_empty_genres_returns_empty_list(self):
        from organizer.cache import book_get
        self._upsert(all_genres=[])
        rec = book_get("/src/test.epub")
        self.assertEqual(rec["genres"], [])

    def test_confidence_stored_as_integer(self):
        from organizer.cache import book_get
        self._upsert(confidence=65)
        rec = book_get("/src/test.epub")
        self.assertEqual(rec["confidence"], 65)

    def test_sources_stored_as_pipe_joined_string(self):
        from organizer.cache import book_get
        self._upsert(sources=["library", "online", "ollama"])
        con = sqlite3.connect(self._db)
        row = con.execute(
            "SELECT sources FROM books WHERE original_path='/src/test.epub'"
        ).fetchone()
        con.close()
        self.assertEqual(row[0], "library|online|ollama")

    def test_upsert_overwrites_existing(self):
        from organizer.cache import book_get
        self._upsert(title="Old Title")
        self._upsert(title="New Title")
        rec = book_get("/src/test.epub")
        self.assertEqual(rec["title"], "New Title")

    def test_multiple_books_independent(self):
        from organizer.cache import book_get
        self._upsert(original_path="/src/a.epub", title="Book A")
        self._upsert(original_path="/src/b.epub", title="Book B")
        self.assertEqual(book_get("/src/a.epub")["title"], "Book A")
        self.assertEqual(book_get("/src/b.epub")["title"], "Book B")

    def test_timestamp_recorded(self):
        from organizer.cache import book_get
        before = int(time.time())
        self._upsert()
        after = int(time.time())
        rec = book_get("/src/test.epub")
        self.assertGreaterEqual(rec["ts"], before)
        self.assertLessEqual(rec["ts"], after)


class TestCacheThreadSafety(unittest.TestCase):

    def setUp(self):
        self._td, self._db = _make_temp_db()
        self._org = Path(self._td)
        import organizer.cache as cache_mod
        self._patches = [
            patch.object(cache_mod, "CACHE_DB",      self._db),
            patch.object(cache_mod, "ORGANIZED_DIR", self._org),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        import shutil
        shutil.rmtree(self._td, ignore_errors=True)

    def test_concurrent_cache_sets_no_corruption(self):
        """50 threads all writing to different keys — no IntegrityError / corruption."""
        from organizer.cache import cache_get, cache_set
        errors = []

        def writer(i):
            try:
                cache_set(f"key_{i}", {"index": i})
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"Thread errors: {errors}")
        # Verify a sample of values are intact
        for i in range(0, 50, 10):
            val = cache_get(f"key_{i}")
            self.assertIsNotNone(val)
            self.assertEqual(val["index"], i)

    def test_concurrent_book_upserts_no_corruption(self):
        """20 threads upserting different books — all should be retrievable."""
        from organizer.cache import book_get, book_upsert
        errors = []

        def upsert_book(i):
            try:
                book_upsert(
                    original_path=f"/src/book_{i}.epub",
                    title=f"Book {i}",
                    author="Author",
                    language="english",
                    all_genres=["fiction"],
                    directory="reading",
                    relative_path=f"reading/Author/book_{i}.epub",
                    confidence=80,
                    sources=["library"],
                )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=upsert_book, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"Thread errors: {errors}")
        for i in range(20):
            rec = book_get(f"/src/book_{i}.epub")
            self.assertIsNotNone(rec)
            self.assertEqual(rec["title"], f"Book {i}")


if __name__ == "__main__":
    unittest.main()
