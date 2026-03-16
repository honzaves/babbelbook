"""
tests/unit/test_deduplicator.py

Unit tests for deduplicate_books.py.

Covers:
  - find_duplicates()     safe / suspicious / orphan classification
  - db_lookup_by_rel()    row lookup by relative path
  - delete_from_db()      DB row deletion and commit
  - _yn()                 yes/no formatting helper
  - print_report()        smoke-test output generation (no crash)
"""

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import deduplicate_books as dedup


def _tmp_dir():
    return tempfile.mkdtemp()


def _create_db(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
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
    return con


def _insert_book(con, rel_path, title="T", author="A"):
    con.execute(
        "INSERT INTO books (original_path, title, author, relative_path) VALUES (?,?,?,?)",
        (f"/src/{rel_path}", title, author, rel_path),
    )
    con.commit()


# ---------------------------------------------------------------------------
# find_duplicates
# ---------------------------------------------------------------------------

class TestFindDuplicates(unittest.TestCase):

    def setUp(self):
        import shutil
        self._td = Path(_tmp_dir())
        self._org = self._td / "books_organized"
        self._org.mkdir()
        # Monkey-patch the module's ORGANIZED_DIR so relative paths work
        self._orig_org = dedup.ORGANIZED_DIR
        dedup.ORGANIZED_DIR = self._org

    def tearDown(self):
        dedup.ORGANIZED_DIR = self._orig_org
        import shutil
        shutil.rmtree(self._td, ignore_errors=True)

    def _make(self, rel_path: str, content: bytes = b"x" * 500) -> Path:
        p = self._org / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        return p

    def test_no_files_returns_empty(self):
        result = dedup.find_duplicates(self._org)
        self.assertEqual(result, [])

    def test_canonical_only_not_detected(self):
        self._make("reading/Author/Dune.epub")
        result = dedup.find_duplicates(self._org)
        self.assertEqual(result, [])

    def test_safe_duplicate_same_size(self):
        self._make("reading/Author/Dune.epub",    b"x" * 500)
        self._make("reading/Author/Dune_(1).epub", b"x" * 500)
        result = dedup.find_duplicates(self._org)
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0]["safe"])
        self.assertTrue(result[0]["has_canon"])
        self.assertTrue(result[0]["same_size"])

    def test_suspicious_duplicate_different_size(self):
        self._make("reading/Author/Dune.epub",    b"x" * 500)
        self._make("reading/Author/Dune_(1).epub", b"y" * 999)
        result = dedup.find_duplicates(self._org)
        self.assertEqual(len(result), 1)
        self.assertFalse(result[0]["safe"])
        self.assertTrue(result[0]["has_canon"])
        self.assertFalse(result[0]["same_size"])

    def test_orphan_duplicate_no_canonical(self):
        self._make("reading/Author/Ghost_(1).epub", b"z" * 300)
        result = dedup.find_duplicates(self._org)
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0]["safe"])     # orphan = safe to delete
        self.assertFalse(result[0]["has_canon"])

    def test_multiple_duplicates_all_found(self):
        self._make("reading/Author/Book.epub",    b"a" * 100)
        self._make("reading/Author/Book_(1).epub", b"a" * 100)
        self._make("reading/Author/Book_(2).epub", b"b" * 200)  # suspicious
        result = dedup.find_duplicates(self._org)
        self.assertEqual(len(result), 2)
        safe_count       = sum(1 for d in result if d["safe"])
        suspicious_count = sum(1 for d in result if not d["safe"])
        self.assertEqual(safe_count, 1)
        self.assertEqual(suspicious_count, 1)

    def test_non_book_files_ignored(self):
        self._make("reading/Author/notes_(1).txt")
        result = dedup.find_duplicates(self._org)
        self.assertEqual(result, [])

    def test_n_field_correct(self):
        self._make("reading/Author/Dune.epub",    b"x" * 100)
        self._make("reading/Author/Dune_(3).epub", b"x" * 100)
        result = dedup.find_duplicates(self._org)
        self.assertEqual(result[0]["n"], 3)

    def test_relative_paths_correct(self):
        self._make("reading/Author/Book.epub",    b"x" * 100)
        self._make("reading/Author/Book_(1).epub", b"x" * 100)
        result = dedup.find_duplicates(self._org)
        self.assertIn("Book_(1).epub", result[0]["rel"])
        self.assertIn("Book.epub",     result[0]["canon_rel"])

    def test_supported_formats_all_detected(self):
        for ext in [".epub", ".pdf", ".mobi", ".azw3", ".cbz"]:
            self._make(f"dir/Author/Book{ext}",    b"x" * 100)
            self._make(f"dir/Author/Book_(1){ext}", b"x" * 100)
        result = dedup.find_duplicates(self._org)
        self.assertEqual(len(result), 5)


# ---------------------------------------------------------------------------
# db_lookup_by_rel / delete_from_db
# ---------------------------------------------------------------------------

class TestDbHelpers(unittest.TestCase):

    def setUp(self):
        import shutil
        self._td = Path(_tmp_dir())
        db_path = self._td / ".cache.db"
        self._con = _create_db(db_path)

    def tearDown(self):
        self._con.close()
        import shutil
        shutil.rmtree(self._td, ignore_errors=True)

    def test_lookup_hit(self):
        _insert_book(self._con, "reading/Author/Book.epub", title="Dune")
        row = dedup.db_lookup_by_rel(self._con, "reading/Author/Book.epub")
        self.assertIsNotNone(row)
        self.assertEqual(row["title"], "Dune")

    def test_lookup_miss_returns_none(self):
        row = dedup.db_lookup_by_rel(self._con, "nonexistent/path.epub")
        self.assertIsNone(row)

    def test_delete_removes_row(self):
        _insert_book(self._con, "reading/Author/Book.epub")
        deleted = dedup.delete_from_db(self._con, "reading/Author/Book.epub")
        self.assertTrue(deleted)
        row = dedup.db_lookup_by_rel(self._con, "reading/Author/Book.epub")
        self.assertIsNone(row)

    def test_delete_returns_false_for_missing_row(self):
        result = dedup.delete_from_db(self._con, "does/not/exist.epub")
        self.assertFalse(result)

    def test_delete_only_removes_matching_row(self):
        _insert_book(self._con, "reading/Author/BookA.epub")
        _insert_book(self._con, "reading/Author/BookB.epub")
        dedup.delete_from_db(self._con, "reading/Author/BookA.epub")
        self.assertIsNotNone(
            dedup.db_lookup_by_rel(self._con, "reading/Author/BookB.epub")
        )


# ---------------------------------------------------------------------------
# _yn helper
# ---------------------------------------------------------------------------

class TestYnHelper(unittest.TestCase):

    def test_true_returns_yes(self):
        self.assertEqual(dedup._yn(True), "yes")

    def test_false_returns_no(self):
        self.assertEqual(dedup._yn(False), "no")


# ---------------------------------------------------------------------------
# print_report smoke test
# ---------------------------------------------------------------------------

class TestPrintReport(unittest.TestCase):

    def _make_dup(self, rel, safe=True, has_canon=True):
        return {
            "rel":      rel,
            "canon_rel": rel.replace("_(1)", ""),
            "has_canon": has_canon,
            "same_size": safe,
            "safe":      safe,
            "n":         1,
        }

    def test_empty_no_crash(self):
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            dedup.print_report([], {})
        self.assertIn("No duplicates", buf.getvalue())

    def test_safe_and_suspicious_no_crash(self):
        import io, contextlib
        dups = [
            self._make_dup("reading/A/Book_(1).epub", safe=True),
            self._make_dup("reading/A/Other_(1).epub", safe=False),
        ]
        db_records = {d["rel"]: True for d in dups}
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            dedup.print_report(dups, db_records)
        output = buf.getvalue()
        self.assertIn("SAFE TO DELETE", output)
        self.assertIn("DIFFERENT SIZE", output)


if __name__ == "__main__":
    unittest.main()
