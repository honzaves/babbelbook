"""
tests/unit/test_browser_helpers.py

Unit tests for the pure helper functions inside the browser package.

Covers:
  browser/routes_write.py
    - _sanitize()         illegal chars stripped, whitespace collapsed
    - _move_book()        normal move, src==dest noop, dest occupied → _(N)

  browser/routes_read.py
    - _normalize_author() lowercase + diacritic stripping
    - _levenshtein()      edit distance correctness
    - _scan_duplicates()  TTL cache behaviour and invalidation
    - invalidate_dup_cache()

  browser/db.py
    - _fmt_ts()           timestamp → human-readable string
    - _row_to_dict()      genres JSON-decoded, ts_fmt added
"""

import json
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


# ---------------------------------------------------------------------------
# _sanitize
# ---------------------------------------------------------------------------

class TestSanitizeWrite(unittest.TestCase):

    def setUp(self):
        from browser.routes_write import _sanitize
        self._sanitize = _sanitize

    def test_strips_colon(self):
        self.assertNotIn(":", self._sanitize("Bad:Name"))

    def test_strips_slash(self):
        self.assertNotIn("/", self._sanitize("Bad/Name"))

    def test_strips_backslash(self):
        self.assertNotIn("\\", self._sanitize("Bad\\Name"))

    def test_collapses_whitespace(self):
        self.assertEqual(self._sanitize("Too   Many  Spaces"), "Too Many Spaces")

    def test_empty_returns_unknown(self):
        self.assertEqual(self._sanitize(""), "Unknown")

    def test_none_returns_unknown(self):
        self.assertEqual(self._sanitize(None), "Unknown")

    def test_normal_name_unchanged(self):
        self.assertEqual(self._sanitize("Stephen King"), "Stephen King")

    def test_strips_angle_brackets(self):
        result = self._sanitize("a<b>c")
        self.assertNotIn("<", result)
        self.assertNotIn(">", result)


# ---------------------------------------------------------------------------
# _move_book
# ---------------------------------------------------------------------------

class TestMoveBook(unittest.TestCase):

    def setUp(self):
        self._td = Path(tempfile.mkdtemp())
        self._org = self._td / "books_organized"
        self._org.mkdir()
        import browser.routes_write as rw
        self._patch = patch.object(rw, "ORGANIZED_DIR", self._org)
        self._patch.start()
        from browser.routes_write import _move_book
        self._move = _move_book

    def tearDown(self):
        self._patch.stop()
        shutil.rmtree(self._td, ignore_errors=True)

    def _make(self, rel: str, content: bytes = b"x" * 200) -> Path:
        p = self._org / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        return p

    def test_basic_move_succeeds(self):
        self._make("reading/OldAuthor/Book.epub")
        ok, result = self._move(
            "reading/OldAuthor/Book.epub",
            "reading/NewAuthor/Book.epub",
        )
        self.assertTrue(ok)
        self.assertTrue((self._org / "reading/NewAuthor/Book.epub").exists())
        self.assertFalse((self._org / "reading/OldAuthor/Book.epub").exists())

    def test_src_equals_dest_is_noop(self):
        self._make("reading/Author/Book.epub")
        ok, result = self._move(
            "reading/Author/Book.epub",
            "reading/Author/Book.epub",
        )
        self.assertTrue(ok)
        self.assertTrue((self._org / "reading/Author/Book.epub").exists())

    def test_missing_source_returns_error(self):
        ok, msg = self._move("nonexistent/Book.epub", "reading/Author/Book.epub")
        self.assertFalse(ok)
        self.assertIn("not found", msg.lower())

    def test_collision_renamed_with_suffix(self):
        self._make("reading/Author/Book.epub",  b"a" * 100)
        self._make("reading/Author2/Book.epub", b"b" * 100)
        ok, result = self._move(
            "reading/Author/Book.epub",
            "reading/Author2/Book.epub",
        )
        self.assertTrue(ok)
        # New file should have _(1) suffix
        self.assertIn("_(1)", result)
        self.assertTrue((self._org / result).exists())

    def test_empty_source_dirs_removed(self):
        self._make("reading/OldAuthor/Book.epub")
        self._move(
            "reading/OldAuthor/Book.epub",
            "reading/NewAuthor/Book.epub",
        )
        self.assertFalse((self._org / "reading/OldAuthor").exists())

    def test_parent_dirs_created_automatically(self):
        self._make("reading/Author/Book.epub")
        ok, result = self._move(
            "reading/Author/Book.epub",
            "cookbooks/BrandNew/SubDir/Book.epub",
        )
        self.assertTrue(ok)
        self.assertTrue((self._org / "cookbooks/BrandNew/SubDir/Book.epub").exists())

    def test_returned_path_is_relative(self):
        self._make("reading/Author/Book.epub")
        ok, result = self._move(
            "reading/Author/Book.epub",
            "reading/NewAuthor/Book.epub",
        )
        self.assertTrue(ok)
        self.assertFalse(Path(result).is_absolute())


# ---------------------------------------------------------------------------
# _normalize_author
# ---------------------------------------------------------------------------

class TestNormalizeAuthorRead(unittest.TestCase):

    def setUp(self):
        from browser.routes_read import _normalize_author
        self._norm = _normalize_author

    def test_lowercase(self):
        self.assertEqual(self._norm("KING"), "king")

    def test_strips_spaces_and_punctuation(self):
        result = self._norm("T. R. Napper")
        self.assertEqual(result, "trnapper")

    def test_same_as_dotted_variant(self):
        self.assertEqual(self._norm("T. R. Napper"), self._norm("T.R. Napper"))

    def test_diacritic_stripping_nfd(self):
        # é → e via NFD decomposition
        self.assertEqual(self._norm("André"), self._norm("Andre"))

    def test_special_char_l_stroke(self):
        # ł has no NFD decomposition — must be handled by _DIACRITIC_EXTRA
        result_special = self._norm("Stanisław")
        result_plain   = self._norm("Stanislaw")
        self.assertEqual(result_special, result_plain)

    def test_o_stroke(self):
        self.assertEqual(self._norm("Søren"), self._norm("Soren"))

    def test_empty_string(self):
        self.assertEqual(self._norm(""), "")

    def test_numbers_stripped(self):
        # Only alpha chars should remain
        result = self._norm("Author123")
        self.assertNotIn("1", result)


# ---------------------------------------------------------------------------
# _levenshtein
# ---------------------------------------------------------------------------

class TestLevenshtein(unittest.TestCase):

    def setUp(self):
        from browser.routes_read import _levenshtein
        self._lev = _levenshtein

    def test_identical_strings_zero(self):
        self.assertEqual(self._lev("abc", "abc"), 0)

    def test_empty_a_returns_len_b(self):
        self.assertEqual(self._lev("", "hello"), 5)

    def test_empty_b_returns_len_a(self):
        self.assertEqual(self._lev("hello", ""), 5)

    def test_both_empty_zero(self):
        self.assertEqual(self._lev("", ""), 0)

    def test_single_insertion(self):
        self.assertEqual(self._lev("abc", "abcd"), 1)

    def test_single_deletion(self):
        self.assertEqual(self._lev("abcd", "abc"), 1)

    def test_single_substitution(self):
        self.assertEqual(self._lev("abc", "axc"), 1)

    def test_completely_different(self):
        self.assertEqual(self._lev("abc", "xyz"), 3)

    def test_known_pair_kitten_sitting(self):
        self.assertEqual(self._lev("kitten", "sitting"), 3)

    def test_symmetric(self):
        self.assertEqual(self._lev("hello", "world"),
                         self._lev("world", "hello"))


# ---------------------------------------------------------------------------
# _scan_duplicates TTL cache + invalidation
# ---------------------------------------------------------------------------

class TestScanDuplicatesCache(unittest.TestCase):

    def setUp(self):
        self._td = Path(tempfile.mkdtemp())
        self._org = self._td / "books_organized"
        self._org.mkdir()
        import browser.routes_read as rr
        self._rr = rr
        self._patch = patch.object(rr, "ORGANIZED_DIR", self._org)
        self._patch.start()
        # Reset cache state
        rr._dup_cache    = None
        rr._dup_cache_ts = 0.0

    def tearDown(self):
        self._patch.stop()
        shutil.rmtree(self._td, ignore_errors=True)

    def _make(self, rel: str, content: bytes = b"x" * 100):
        p = self._org / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)

    def test_empty_library_zero_dups(self):
        result = self._rr._scan_duplicates()
        self.assertEqual(result["dup_safe"],       0)
        self.assertEqual(result["dup_suspicious"], 0)
        self.assertEqual(result["items"],         [])

    def test_detects_safe_duplicate(self):
        self._make("reading/Author/Book.epub",    b"x" * 100)
        self._make("reading/Author/Book_(1).epub", b"x" * 100)
        result = self._rr._scan_duplicates()
        self.assertEqual(result["dup_safe"], 1)

    def test_detects_suspicious_duplicate(self):
        self._make("reading/Author/Book.epub",    b"x" * 100)
        self._make("reading/Author/Book_(1).epub", b"y" * 200)
        result = self._rr._scan_duplicates()
        self.assertEqual(result["dup_suspicious"], 1)

    def test_cache_hit_returns_same_object(self):
        first  = self._rr._scan_duplicates()
        second = self._rr._scan_duplicates()
        self.assertIs(first, second)

    def test_invalidate_clears_cache(self):
        from browser.routes_read import invalidate_dup_cache
        first = self._rr._scan_duplicates()
        invalidate_dup_cache()
        second = self._rr._scan_duplicates()
        self.assertIsNot(first, second)

    def test_cache_expires_after_ttl(self):
        with patch.object(self._rr, "_DUP_CACHE_TTL", 0):
            first  = self._rr._scan_duplicates()
            second = self._rr._scan_duplicates()
            self.assertIsNot(first, second)


# ---------------------------------------------------------------------------
# _fmt_ts / _row_to_dict
# ---------------------------------------------------------------------------

class TestDbHelpers(unittest.TestCase):

    def test_fmt_ts_valid_timestamp(self):
        from browser.db import _fmt_ts
        ts  = 1_700_000_000
        fmt = _fmt_ts(ts)
        self.assertIsInstance(fmt, str)
        self.assertGreater(len(fmt), 5)
        self.assertNotEqual(fmt, "\u2014")

    def test_fmt_ts_invalid_returns_dash(self):
        from browser.db import _fmt_ts
        self.assertEqual(_fmt_ts(None), "\u2014")
        self.assertEqual(_fmt_ts("not_a_ts"), "\u2014")

    def test_row_to_dict_decodes_genres(self):
        from browser.db import _row_to_dict
        td  = Path(tempfile.mkdtemp())
        db  = td / "t.db"
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        con.execute(
            "CREATE TABLE t (genres TEXT, ts INTEGER)"
        )
        con.execute(
            "INSERT INTO t VALUES (?, ?)",
            (json.dumps(["thriller", "mystery"]), 1_700_000_000),
        )
        con.commit()
        row = con.execute("SELECT * FROM t").fetchone()
        d   = _row_to_dict(row)
        con.close()
        shutil.rmtree(td, ignore_errors=True)
        self.assertIsInstance(d["genres"], list)
        self.assertIn("thriller", d["genres"])
        self.assertIn("ts_fmt",   d)

    def test_row_to_dict_bad_genres_json_returns_empty(self):
        from browser.db import _row_to_dict
        td  = Path(tempfile.mkdtemp())
        db  = td / "t.db"
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        con.execute("CREATE TABLE t (genres TEXT, ts INTEGER)")
        con.execute("INSERT INTO t VALUES (?, ?)", ("NOT JSON", 0))
        con.commit()
        row = con.execute("SELECT * FROM t").fetchone()
        d   = _row_to_dict(row)
        con.close()
        shutil.rmtree(td, ignore_errors=True)
        self.assertEqual(d["genres"], [])


if __name__ == "__main__":
    unittest.main()
