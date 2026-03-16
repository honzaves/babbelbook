"""
tests/unit/test_merge_authors.py

Tests for the author-merge logic in both implementations:
  - babbelbook_flet._merge_authors()       (Flet desktop app)
  - browser/routes_write.api_merge_authors  (Flask API endpoint)

Both share identical logic, so the same scenario matrix is run against both.

Cases covered
─────────────
1.  Main bug: source and target in DIFFERENT top-level category dirs
2.  Normal same-category merge
3.  Source spans multiple categories, target in one of them
4.  Source spans multiple categories, target in a DIFFERENT one
5.  Source spans multiple categories, target doesn't exist yet
6.  Identical file at destination → skipped (source deleted, DB row removed)
7.  Name collision at destination → renamed _(N), both files kept
8.  Source author doesn't exist → no-op, no error
9.  Source folder has subdirectories (language subfolders) → cleaned up after merge
10. Single-quote in author/file name → handled correctly
"""

import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Make sure the project root is on the path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.conftest import TempLibrary, make_flask_client, stop_patches


# ---------------------------------------------------------------------------
# Helpers shared by both test suites
# ---------------------------------------------------------------------------

def _add(lib: TempLibrary, rel: str, author: str, directory: str,
         content: bytes = b"x" * 500) -> None:
    """Create a file on disk and a matching DB row."""
    lib.add_book_file(rel, content)
    lib.add_book_record(
        original_path=f"/src/{Path(rel).name}",
        title=Path(rel).stem,
        author=author,
        language="english",
        genres=json.dumps(["fiction"]),
        directory=directory,
        relative_path=rel,
        confidence=80,
        sources="test",
        ts=1_700_000_000,
    )


def _db_row(lib: TempLibrary, rel: str) -> dict | None:
    row = lib.db.execute(
        "SELECT * FROM books WHERE relative_path=?", (rel,)
    ).fetchone()
    return dict(row) if row else None


def _author_rows(lib: TempLibrary, author: str) -> list[dict]:
    rows = lib.db.execute(
        "SELECT * FROM books WHERE author=?", (author,)
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Flet implementation tests
# ---------------------------------------------------------------------------

class TestFletMergeAuthors(unittest.TestCase):
    """Drive babbelbook_flet._merge_authors() directly (no Flet UI involved)."""

    def _merge(self, lib, src, tgt):
        """Import and call _merge_authors with the tmp library patched in."""
        import babbelbook_flet as bf
        with patch.object(bf, "ORGANIZED_DIR", lib.org), \
             patch.object(bf, "DB_PATH", lib.db_path):
            # Close the fixture's connection so _merge_authors can open its own
            lib.db.close()
            moved, skipped, errors = bf._merge_authors(src, tgt, organized_dir=lib.org)
            # Re-open for assertions
            lib.db = sqlite3.connect(lib.db_path)
            lib.db.row_factory = sqlite3.Row
        return moved, skipped, errors

    # 1. Main bug ─────────────────────────────────────────────────────────────
    def test_cross_category_merge(self):
        """Source in reading/, target already established in psychology/."""
        with TempLibrary() as lib:
            _add(lib, "reading/Stephen King/Carrie.epub",     "Stephen King",  "reading")
            _add(lib, "psychology/S. King/Shining.epub",      "S. King",       "psychology")

            moved, skipped, errors = self._merge(lib, "Stephen King", "S. King")

            self.assertEqual(errors, [])
            self.assertEqual(moved, 1)
            # Book must land in target's established category
            self.assertTrue((lib.org / "psychology/S. King/Carrie.epub").exists())
            # Wrong-category folder must NOT have been created
            self.assertFalse((lib.org / "reading/S. King").exists())
            # Source folder cleaned up
            self.assertFalse((lib.org / "reading/Stephen King").exists())
            # DB reflects new location and author name
            row = _db_row(lib, "psychology/S. King/Carrie.epub")
            self.assertIsNotNone(row)
            self.assertEqual(row["author"], "S. King")
            self.assertEqual(row["relative_path"], "psychology/S. King/Carrie.epub")

    # 2. Normal same-category merge ───────────────────────────────────────────
    def test_same_category_merge(self):
        """Both source and target already in reading/ — unchanged behaviour."""
        with TempLibrary() as lib:
            _add(lib, "reading/T. R. Napper/Book1.epub", "T. R. Napper", "reading")
            _add(lib, "reading/T.R. Napper/Book2.epub",  "T.R. Napper",  "reading")

            moved, skipped, errors = self._merge(lib, "T. R. Napper", "T.R. Napper")

            self.assertEqual(errors, [])
            self.assertEqual(moved, 1)
            self.assertTrue((lib.org / "reading/T.R. Napper/Book1.epub").exists())
            self.assertFalse((lib.org / "reading/T. R. Napper").exists())

    # 3. Source in multiple categories, target in ONE of them ─────────────────
    def test_multi_source_target_in_one_matching_category(self):
        """Source in reading + cookbooks; target already in reading → cookbooks
        source goes to reading too."""
        with TempLibrary() as lib:
            _add(lib, "reading/Old/Novel.epub",   "Old", "reading")
            _add(lib, "cookbooks/Old/Recipes.epub", "Old", "cookbooks")
            _add(lib, "reading/New/Existing.epub", "New", "reading")

            moved, skipped, errors = self._merge(lib, "Old", "New")

            self.assertEqual(errors, [])
            self.assertEqual(moved, 2)
            # reading source → reading target (same category match)
            self.assertTrue((lib.org / "reading/New/Novel.epub").exists())
            # cookbooks source → reading target (target's established home)
            self.assertTrue((lib.org / "reading/New/Recipes.epub").exists())
            self.assertFalse((lib.org / "reading/Old").exists())
            self.assertFalse((lib.org / "cookbooks/Old").exists())
            # cookbooks/New should NOT have been created
            self.assertFalse((lib.org / "cookbooks/New").exists())

    # 4. Source in multiple categories, target in a DIFFERENT one ─────────────
    def test_multi_source_target_in_different_category(self):
        """Source in reading + cookbooks; target only in psychology."""
        with TempLibrary() as lib:
            _add(lib, "reading/Old/Novel.epub",       "Old", "reading")
            _add(lib, "cookbooks/Old/Recipes.epub",   "Old", "cookbooks")
            _add(lib, "psychology/New/MindBook.epub", "New", "psychology")

            moved, skipped, errors = self._merge(lib, "Old", "New")

            self.assertEqual(errors, [])
            self.assertEqual(moved, 2)
            self.assertTrue((lib.org / "psychology/New/Novel.epub").exists())
            self.assertTrue((lib.org / "psychology/New/Recipes.epub").exists())
            self.assertFalse((lib.org / "reading/Old").exists())
            self.assertFalse((lib.org / "cookbooks/Old").exists())
            self.assertFalse((lib.org / "reading/New").exists())
            self.assertFalse((lib.org / "cookbooks/New").exists())

    # 5. Target doesn't exist yet → create in same category as source ─────────
    def test_target_does_not_exist_yet(self):
        """Target has no folder anywhere — books stay in same category."""
        with TempLibrary() as lib:
            _add(lib, "reading/OldName/Book.epub", "OldName", "reading")

            moved, skipped, errors = self._merge(lib, "OldName", "NewName")

            self.assertEqual(errors, [])
            self.assertEqual(moved, 1)
            self.assertTrue((lib.org / "reading/NewName/Book.epub").exists())
            self.assertFalse((lib.org / "reading/OldName").exists())

    # 6. Identical file at destination → skipped ──────────────────────────────
    def test_identical_file_skipped(self):
        with TempLibrary() as lib:
            content = b"same" * 100
            _add(lib, "reading/Old/Book.epub", "Old", "reading", content)
            _add(lib, "reading/New/Book.epub", "New", "reading", content)

            moved, skipped, errors = self._merge(lib, "Old", "New")

            self.assertEqual(errors, [])
            self.assertEqual(moved, 0)
            self.assertEqual(skipped, 1)
            self.assertFalse((lib.org / "reading/Old/Book.epub").exists())
            self.assertTrue((lib.org / "reading/New/Book.epub").exists())
            # DB row for old path removed
            self.assertIsNone(_db_row(lib, "reading/Old/Book.epub"))

    # 7. Name collision at destination → renamed _(N) ─────────────────────────
    def test_name_collision_renamed(self):
        with TempLibrary() as lib:
            _add(lib, "reading/Old/Book.epub", "Old", "reading", b"a" * 100)
            _add(lib, "reading/New/Book.epub", "New", "reading", b"b" * 200)

            moved, skipped, errors = self._merge(lib, "Old", "New")

            self.assertEqual(errors, [])
            self.assertEqual(moved, 1)
            self.assertTrue((lib.org / "reading/New/Book.epub").exists())
            variants = list((lib.org / "reading/New").glob("Book_*.epub"))
            self.assertEqual(len(variants), 1)

    # 8. Source doesn't exist → no-op ─────────────────────────────────────────
    def test_nonexistent_source_is_noop(self):
        with TempLibrary() as lib:
            moved, skipped, errors = self._merge(lib, "Ghost", "Real")
            self.assertEqual(moved, 0)
            self.assertEqual(skipped, 0)
            self.assertEqual(errors, [])

    # 9. Source has language subdirectories → cleaned up ──────────────────────
    def test_subdirectory_cleanup(self):
        """Source has a language subdir that should be removed after merge."""
        with TempLibrary() as lib:
            _add(lib, "reading/Old/english/Book.epub", "Old", "reading")

            moved, skipped, errors = self._merge(lib, "Old", "New")

            self.assertEqual(errors, [])
            self.assertEqual(moved, 1)
            # Source dir and its english/ subdir must both be gone
            self.assertFalse((lib.org / "reading/Old/english").exists())
            self.assertFalse((lib.org / "reading/Old").exists())

    # 10. Single-quote in author/filename ─────────────────────────────────────
    def test_single_quote_in_author_name(self):
        with TempLibrary() as lib:
            _add(lib, "reading/O'Brien/Kafka.epub",  "O'Brien",  "reading")
            _add(lib, "reading/O'Brian/Aubrey.epub", "O'Brian", "reading")

            moved, skipped, errors = self._merge(lib, "O'Brien", "O'Brian")

            self.assertEqual(errors, [])
            self.assertEqual(moved, 1)
            self.assertTrue((lib.org / "reading/O'Brian/Kafka.epub").exists())
            self.assertFalse((lib.org / "reading/O'Brien").exists())
            row = _db_row(lib, "reading/O'Brian/Kafka.epub")
            self.assertEqual(row["author"], "O'Brian")

    def test_single_quote_in_filename(self):
        with TempLibrary() as lib:
            _add(lib, "reading/Old/It's Complicated.epub", "Old", "reading")

            moved, skipped, errors = self._merge(lib, "Old", "New")

            self.assertEqual(errors, [])
            self.assertEqual(moved, 1)
            self.assertTrue((lib.org / "reading/New/It's Complicated.epub").exists())


# ---------------------------------------------------------------------------
# Browser (Flask) implementation tests — same scenario matrix
# ---------------------------------------------------------------------------

class TestBrowserMergeAuthors(unittest.TestCase):

    def setUp(self):
        self._lib = TempLibrary().__enter__()
        self._client = make_flask_client(self._lib)

    def tearDown(self):
        stop_patches(self._client)
        self._lib.__exit__(None, None, None)

    def _merge(self, src, tgt):
        return self._client.post(
            "/api/authors/merge",
            json={"source": src, "target": tgt},
        )

    # 1. Main bug ─────────────────────────────────────────────────────────────
    def test_cross_category_merge(self):
        _add(self._lib, "reading/Stephen King/Carrie.epub",  "Stephen King", "reading")
        _add(self._lib, "psychology/S. King/Shining.epub",   "S. King",      "psychology")

        resp = self._merge("Stephen King", "S. King")
        data = resp.get_json()

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["moved"], 1)
        self.assertTrue((self._lib.org / "psychology/S. King/Carrie.epub").exists())
        self.assertFalse((self._lib.org / "reading/S. King").exists())
        self.assertFalse((self._lib.org / "reading/Stephen King").exists())
        row = _db_row(self._lib, "psychology/S. King/Carrie.epub")
        self.assertIsNotNone(row)
        self.assertEqual(row["author"], "S. King")

    # 2. Normal same-category merge ───────────────────────────────────────────
    def test_same_category_merge(self):
        _add(self._lib, "reading/T. R. Napper/Book1.epub", "T. R. Napper", "reading")
        _add(self._lib, "reading/T.R. Napper/Book2.epub",  "T.R. Napper",  "reading")

        resp = self._merge("T. R. Napper", "T.R. Napper")
        data = resp.get_json()

        self.assertTrue(data["ok"])
        self.assertEqual(data["moved"], 1)
        self.assertTrue((self._lib.org / "reading/T.R. Napper/Book1.epub").exists())
        self.assertFalse((self._lib.org / "reading/T. R. Napper").exists())

    # 3. Source in multiple categories, target in ONE of them ─────────────────
    def test_multi_source_target_in_one_matching_category(self):
        _add(self._lib, "reading/Old/Novel.epub",    "Old", "reading")
        _add(self._lib, "cookbooks/Old/Recipes.epub","Old", "cookbooks")
        _add(self._lib, "reading/New/Existing.epub", "New", "reading")

        resp = self._merge("Old", "New")
        data = resp.get_json()

        self.assertTrue(data["ok"])
        self.assertEqual(data["moved"], 2)
        self.assertTrue((self._lib.org / "reading/New/Novel.epub").exists())
        self.assertTrue((self._lib.org / "reading/New/Recipes.epub").exists())
        self.assertFalse((self._lib.org / "cookbooks/New").exists())

    # 4. Source in multiple categories, target in a DIFFERENT one ─────────────
    def test_multi_source_target_in_different_category(self):
        _add(self._lib, "reading/Old/Novel.epub",       "Old", "reading")
        _add(self._lib, "cookbooks/Old/Recipes.epub",   "Old", "cookbooks")
        _add(self._lib, "psychology/New/MindBook.epub", "New", "psychology")

        resp = self._merge("Old", "New")
        data = resp.get_json()

        self.assertTrue(data["ok"])
        self.assertEqual(data["moved"], 2)
        self.assertTrue((self._lib.org / "psychology/New/Novel.epub").exists())
        self.assertTrue((self._lib.org / "psychology/New/Recipes.epub").exists())
        self.assertFalse((self._lib.org / "reading/New").exists())
        self.assertFalse((self._lib.org / "cookbooks/New").exists())

    # 5. Target doesn't exist yet ─────────────────────────────────────────────
    def test_target_does_not_exist_yet(self):
        _add(self._lib, "reading/OldName/Book.epub", "OldName", "reading")

        resp = self._merge("OldName", "NewName")
        data = resp.get_json()

        self.assertTrue(data["ok"])
        self.assertEqual(data["moved"], 1)
        self.assertTrue((self._lib.org / "reading/NewName/Book.epub").exists())
        self.assertFalse((self._lib.org / "reading/OldName").exists())

    # 6. Identical file at destination → skipped ──────────────────────────────
    def test_identical_file_skipped(self):
        content = b"same" * 100
        _add(self._lib, "reading/Old/Book.epub", "Old", "reading", content)
        _add(self._lib, "reading/New/Book.epub", "New", "reading", content)

        resp = self._merge("Old", "New")
        data = resp.get_json()

        self.assertTrue(data["ok"])
        self.assertEqual(data["skipped"], 1)
        self.assertFalse((self._lib.org / "reading/Old/Book.epub").exists())

    # 7. Name collision at destination → renamed _(N) ─────────────────────────
    def test_name_collision_renamed(self):
        _add(self._lib, "reading/Old/Book.epub", "Old", "reading", b"a" * 100)
        _add(self._lib, "reading/New/Book.epub", "New", "reading", b"b" * 200)

        self._merge("Old", "New")

        self.assertTrue((self._lib.org / "reading/New/Book.epub").exists())
        variants = list((self._lib.org / "reading/New").glob("Book_*.epub"))
        self.assertEqual(len(variants), 1)

    # 8. Source doesn't exist → no-op ─────────────────────────────────────────
    def test_nonexistent_source_is_noop(self):
        resp = self._merge("Ghost", "Real")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["moved"], 0)

    # 9. Subdirectory cleanup ─────────────────────────────────────────────────
    def test_subdirectory_cleanup(self):
        _add(self._lib, "reading/Old/english/Book.epub", "Old", "reading")

        self._merge("Old", "New")

        self.assertFalse((self._lib.org / "reading/Old/english").exists())
        self.assertFalse((self._lib.org / "reading/Old").exists())

    # 10. Single-quote in author/filename ─────────────────────────────────────
    def test_single_quote_in_author_name(self):
        _add(self._lib, "reading/O'Brien/Kafka.epub",  "O'Brien",  "reading")
        _add(self._lib, "reading/O'Brian/Aubrey.epub", "O'Brian", "reading")

        resp = self._merge("O'Brien", "O'Brian")
        data = resp.get_json()

        self.assertTrue(data["ok"])
        self.assertEqual(data["moved"], 1)
        self.assertTrue((self._lib.org / "reading/O'Brian/Kafka.epub").exists())
        row = _db_row(self._lib, "reading/O'Brian/Kafka.epub")
        self.assertEqual(row["author"], "O'Brian")

    def test_single_quote_in_filename(self):
        _add(self._lib, "reading/Old/It's Complicated.epub", "Old", "reading")

        resp = self._merge("Old", "New")
        data = resp.get_json()

        self.assertTrue(data["ok"])
        self.assertEqual(data["moved"], 1)
        self.assertTrue((self._lib.org / "reading/New/It's Complicated.epub").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
