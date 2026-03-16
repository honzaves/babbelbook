"""
tests/integration/test_api_write.py

Integration tests for all mutating endpoints in book_browser.

Endpoints covered:
  DELETE /api/books               delete file + DB row
  PATCH  /api/books/genres        replace genre list
  PATCH  /api/books/author        rename author + move file
  PATCH  /api/books/directory     change category + move file
  POST   /api/authors/merge       merge two author folders

Each test verifies both the HTTP response and the side-effects:
  - filesystem changes (file moved / deleted)
  - database changes  (row updated / deleted)
  - cache invalidation (dup cache cleared after write)
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.conftest import TempLibrary, make_flask_client, stop_patches


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class ApiWriteBase(unittest.TestCase):

    def setUp(self):
        self._lib = TempLibrary().__enter__()
        self._client = make_flask_client(self._lib)
        import browser.routes_read as rr
        rr._dup_cache    = None
        rr._dup_cache_ts = 0.0

    def tearDown(self):
        stop_patches(self._client)
        self._lib.__exit__(None, None, None)

    def _seed_book(self, **kw):
        defaults = dict(
            original_path="/src/book.epub",
            title="Test Book",
            author="Test Author",
            language="english",
            genres=json.dumps(["fiction"]),
            directory="reading",
            relative_path="reading/Test Author/book.epub",
            confidence=80,
            sources="library",
            ts=1_700_000_000,
        )
        defaults.update(kw)
        self._lib.db.execute(
            "INSERT OR REPLACE INTO books "
            "(original_path,title,author,language,genres,directory,"
            " relative_path,confidence,sources,ts) "
            "VALUES (:original_path,:title,:author,:language,:genres,:directory,"
            "        :relative_path,:confidence,:sources,:ts)",
            defaults,
        )
        self._lib.db.commit()

    def _book_row(self, original_path="/src/book.epub"):
        row = self._lib.db.execute(
            "SELECT * FROM books WHERE original_path=?", (original_path,)
        ).fetchone()
        return dict(row) if row else None

    def _delete(self, body):
        return self._client.delete(
            "/api/books",
            data=json.dumps(body),
            content_type="application/json",
        )

    def _patch(self, url, body):
        return self._client.patch(
            url,
            data=json.dumps(body),
            content_type="application/json",
        )

    def _post(self, url, body):
        return self._client.post(
            url,
            data=json.dumps(body),
            content_type="application/json",
        )


# ---------------------------------------------------------------------------
# DELETE /api/books
# ---------------------------------------------------------------------------

class TestDeleteBook(ApiWriteBase):

    def test_404_book_not_in_db(self):
        resp = self._delete({"original_path": "/src/nope.epub"})
        self.assertEqual(resp.status_code, 404)

    def test_400_missing_original_path(self):
        resp = self._delete({})
        self.assertEqual(resp.status_code, 400)

    def test_deletes_db_row(self):
        self._seed_book()
        self._delete({"original_path": "/src/book.epub"})
        self.assertIsNone(self._book_row())

    def test_deletes_file_on_disk(self):
        self._lib.add_book_file("reading/Test Author/book.epub")
        self._seed_book()
        self._delete({"original_path": "/src/book.epub"})
        self.assertFalse((self._lib.org / "reading/Test Author/book.epub").exists())

    def test_response_ok_true(self):
        self._seed_book()
        resp = self._delete({"original_path": "/src/book.epub"})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])

    def test_deleted_file_true_when_file_existed(self):
        self._lib.add_book_file("reading/Test Author/book.epub")
        self._seed_book()
        data = self._delete({"original_path": "/src/book.epub"}).get_json()
        self.assertTrue(data["deleted_file"])

    def test_deleted_file_false_when_file_missing(self):
        # DB row exists but file is already gone from disk
        self._seed_book()
        data = self._delete({"original_path": "/src/book.epub"}).get_json()
        self.assertFalse(data["deleted_file"])

    def test_empty_parent_dirs_cleaned_up(self):
        self._lib.add_book_file("reading/OnlyAuthor/book.epub")
        self._seed_book(relative_path="reading/OnlyAuthor/book.epub")
        self._delete({"original_path": "/src/book.epub"})
        self.assertFalse((self._lib.org / "reading/OnlyAuthor").exists())


# ---------------------------------------------------------------------------
# PATCH /api/books/genres
# ---------------------------------------------------------------------------

class TestUpdateGenres(ApiWriteBase):

    def test_400_missing_genres(self):
        self._seed_book()
        resp = self._patch("/api/books/genres", {"original_path": "/src/book.epub"})
        self.assertEqual(resp.status_code, 400)

    def test_400_missing_original_path(self):
        resp = self._patch("/api/books/genres", {"genres": ["thriller"]})
        self.assertEqual(resp.status_code, 400)

    def test_404_book_not_found(self):
        resp = self._patch(
            "/api/books/genres",
            {"original_path": "/src/nope.epub", "genres": ["thriller"]},
        )
        self.assertEqual(resp.status_code, 404)

    def test_updates_genres_in_db(self):
        self._seed_book(genres=json.dumps(["fiction"]))
        self._patch(
            "/api/books/genres",
            {"original_path": "/src/book.epub", "genres": ["thriller", "mystery"]},
        )
        row = self._book_row()
        genres = json.loads(row["genres"])
        self.assertIn("thriller", genres)
        self.assertIn("mystery",  genres)
        self.assertNotIn("fiction", genres)

    def test_response_contains_updated_genres(self):
        self._seed_book()
        resp = self._patch(
            "/api/books/genres",
            {"original_path": "/src/book.epub", "genres": ["sci-fi"]},
        )
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["genres"], ["sci-fi"])

    def test_deduplicates_genres(self):
        self._seed_book()
        self._patch(
            "/api/books/genres",
            {"original_path": "/src/book.epub", "genres": ["thriller", "thriller", "mystery"]},
        )
        row = self._book_row()
        genres = json.loads(row["genres"])
        self.assertEqual(genres.count("thriller"), 1)

    def test_empty_genres_list_accepted(self):
        self._seed_book()
        resp = self._patch(
            "/api/books/genres",
            {"original_path": "/src/book.epub", "genres": []},
        )
        self.assertEqual(resp.status_code, 200)
        row = self._book_row()
        self.assertEqual(json.loads(row["genres"]), [])

    def test_new_tag_accepted(self):
        """A genre that doesn't exist in any other book can be created."""
        self._seed_book()
        resp = self._patch(
            "/api/books/genres",
            {"original_path": "/src/book.epub", "genres": ["my-brand-new-tag"]},
        )
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertIn("my-brand-new-tag", data["genres"])


# ---------------------------------------------------------------------------
# PATCH /api/books/author
# ---------------------------------------------------------------------------

class TestUpdateAuthor(ApiWriteBase):

    def test_400_missing_author(self):
        self._seed_book()
        resp = self._patch("/api/books/author", {"original_path": "/src/book.epub"})
        self.assertEqual(resp.status_code, 400)

    def test_404_book_not_found(self):
        resp = self._patch(
            "/api/books/author",
            {"original_path": "/nonexistent.epub", "author": "New Author"},
        )
        self.assertEqual(resp.status_code, 404)

    def test_updates_author_in_db(self):
        self._lib.add_book_file("reading/Test Author/book.epub")
        self._seed_book()
        self._patch(
            "/api/books/author",
            {"original_path": "/src/book.epub", "author": "New Author"},
        )
        row = self._book_row()
        self.assertEqual(row["author"], "New Author")

    def test_moves_file_to_new_author_folder(self):
        self._lib.add_book_file("reading/Test Author/book.epub")
        self._seed_book()
        self._patch(
            "/api/books/author",
            {"original_path": "/src/book.epub", "author": "New Author"},
        )
        self.assertTrue((self._lib.org / "reading/New Author/book.epub").exists())
        self.assertFalse((self._lib.org / "reading/Test Author/book.epub").exists())

    def test_response_contains_new_author_and_path(self):
        self._lib.add_book_file("reading/Test Author/book.epub")
        self._seed_book()
        resp = self._patch(
            "/api/books/author",
            {"original_path": "/src/book.epub", "author": "New Author"},
        )
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["author"], "New Author")
        self.assertIn("New Author", data["relative_path"])

    def test_illegal_chars_sanitized(self):
        self._lib.add_book_file("reading/Test Author/book.epub")
        self._seed_book()
        self._patch(
            "/api/books/author",
            {"original_path": "/src/book.epub", "author": "Author:With/Slashes"},
        )
        row = self._book_row()
        self.assertNotIn("/", row["author"])
        self.assertNotIn(":", row["author"])

    def test_old_empty_author_dir_removed(self):
        self._lib.add_book_file("reading/Lonely Author/book.epub")
        self._seed_book(
            relative_path="reading/Lonely Author/book.epub",
            author="Lonely Author",
        )
        self._patch(
            "/api/books/author",
            {"original_path": "/src/book.epub", "author": "New Author"},
        )
        self.assertFalse((self._lib.org / "reading/Lonely Author").exists())


# ---------------------------------------------------------------------------
# PATCH /api/books/directory
# ---------------------------------------------------------------------------

class TestUpdateDirectory(ApiWriteBase):

    def test_400_invalid_directory(self):
        self._seed_book()
        resp = self._patch(
            "/api/books/directory",
            {"original_path": "/src/book.epub", "directory": "invalid_dir"},
        )
        self.assertEqual(resp.status_code, 400)

    def test_404_book_not_found(self):
        resp = self._patch(
            "/api/books/directory",
            {"original_path": "/nonexistent.epub", "directory": "cookbooks"},
        )
        self.assertEqual(resp.status_code, 404)

    def test_updates_directory_in_db(self):
        self._lib.add_book_file("reading/Test Author/book.epub")
        self._seed_book()
        self._patch(
            "/api/books/directory",
            {"original_path": "/src/book.epub", "directory": "cookbooks"},
        )
        row = self._book_row()
        self.assertEqual(row["directory"], "cookbooks")

    def test_moves_file_to_new_directory(self):
        self._lib.add_book_file("reading/Test Author/book.epub")
        self._seed_book()
        self._patch(
            "/api/books/directory",
            {"original_path": "/src/book.epub", "directory": "cookbooks"},
        )
        self.assertTrue((self._lib.org / "cookbooks/Test Author/book.epub").exists())
        self.assertFalse((self._lib.org / "reading/Test Author/book.epub").exists())

    def test_response_ok_true(self):
        self._lib.add_book_file("reading/Test Author/book.epub")
        self._seed_book()
        resp = self._patch(
            "/api/books/directory",
            {"original_path": "/src/book.epub", "directory": "cookbooks"},
        )
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["directory"], "cookbooks")

    def test_all_valid_directories_accepted(self):
        valid_dirs = [
            "cookbooks", "reading", "home_improvement",
            "sport_workout_yoga_health", "other",
        ]
        for i, d in enumerate(valid_dirs):
            src = f"/src/book{i}.epub"
            rel = f"reading/Author/book{i}.epub"
            self._lib.add_book_file(f"reading/Author/book{i}.epub")
            self._seed_book(original_path=src, relative_path=rel)
            resp = self._patch(
                "/api/books/directory",
                {"original_path": src, "directory": d},
            )
            self.assertEqual(resp.status_code, 200,
                             f"directory '{d}' rejected: {resp.get_json()}")


# ---------------------------------------------------------------------------
# POST /api/authors/merge
# ---------------------------------------------------------------------------

class TestMergeAuthors(ApiWriteBase):

    def test_400_missing_source_or_target(self):
        resp = self._post("/api/authors/merge", {"source": "A"})
        self.assertEqual(resp.status_code, 400)

    def test_400_source_equals_target(self):
        resp = self._post("/api/authors/merge", {"source": "A", "target": "A"})
        self.assertEqual(resp.status_code, 400)

    def test_moves_files_to_target_author_folder(self):
        # Two books by slightly different author name spellings
        self._lib.add_book_file("reading/T. R. Napper/Book1.epub", b"a" * 100)
        self._lib.add_book_file("reading/T. R. Napper/Book2.epub", b"b" * 200)
        self._seed_book(
            original_path="/src/1.epub",
            author="T. R. Napper",
            relative_path="reading/T. R. Napper/Book1.epub",
        )
        self._seed_book(
            original_path="/src/2.epub",
            author="T. R. Napper",
            relative_path="reading/T. R. Napper/Book2.epub",
        )
        resp = self._post(
            "/api/authors/merge",
            {"source": "T. R. Napper", "target": "T.R. Napper"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["moved"], 2)
        self.assertTrue((self._lib.org / "reading/T.R. Napper/Book1.epub").exists())
        self.assertTrue((self._lib.org / "reading/T.R. Napper/Book2.epub").exists())
        self.assertFalse((self._lib.org / "reading/T. R. Napper").exists())

    def test_db_updated_to_target_author(self):
        self._lib.add_book_file("reading/OldName/Book.epub", b"x" * 100)
        self._seed_book(
            author="OldName",
            relative_path="reading/OldName/Book.epub",
        )
        self._post("/api/authors/merge", {"source": "OldName", "target": "NewName"})
        row = self._book_row()
        self.assertEqual(row["author"], "NewName")

    def test_identical_file_in_target_skipped_not_duplicated(self):
        """If identical file (same size) already exists at target, source is removed."""
        self._lib.add_book_file("reading/OldName/Book.epub",  b"x" * 100)
        self._lib.add_book_file("reading/NewName/Book.epub",  b"x" * 100)
        self._seed_book(
            original_path="/src/old.epub",
            author="OldName",
            relative_path="reading/OldName/Book.epub",
        )
        resp = self._post("/api/authors/merge", {"source": "OldName", "target": "NewName"})
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["skipped"], 1)
        self.assertFalse((self._lib.org / "reading/OldName/Book.epub").exists())

    def test_different_sized_file_at_target_renamed(self):
        """Same filename but different content → dest should be renamed _(N), not overwritten."""
        self._lib.add_book_file("reading/OldName/Book.epub",  b"a" * 100)
        self._lib.add_book_file("reading/NewName/Book.epub",  b"b" * 200)
        self._seed_book(
            original_path="/src/old.epub",
            author="OldName",
            relative_path="reading/OldName/Book.epub",
        )
        self._post("/api/authors/merge", {"source": "OldName", "target": "NewName"})
        # Original at NewName still there
        self.assertTrue((self._lib.org / "reading/NewName/Book.epub").exists())
        # Moved book should have a _(N) variant name
        variants = list((self._lib.org / "reading/NewName").glob("Book_*.epub"))
        self.assertEqual(len(variants), 1)

    def test_merge_across_multiple_category_dirs(self):
        """Author appears in both reading/ and cookbooks/ — both are merged."""
        self._lib.add_book_file("reading/OldName/Novel.epub",  b"a" * 100)
        self._lib.add_book_file("cookbooks/OldName/Recipes.epub", b"b" * 100)
        self._seed_book(
            original_path="/src/novel.epub",
            author="OldName",
            directory="reading",
            relative_path="reading/OldName/Novel.epub",
        )
        self._seed_book(
            original_path="/src/recipes.epub",
            author="OldName",
            directory="cookbooks",
            relative_path="cookbooks/OldName/Recipes.epub",
        )
        self._post("/api/authors/merge", {"source": "OldName", "target": "NewName"})
        self.assertTrue((self._lib.org / "reading/NewName/Novel.epub").exists())
        self.assertTrue((self._lib.org / "cookbooks/NewName/Recipes.epub").exists())
        self.assertFalse((self._lib.org / "reading/OldName").exists())
        self.assertFalse((self._lib.org / "cookbooks/OldName").exists())

    def test_dup_cache_invalidated_after_merge(self):
        import browser.routes_read as rr
        rr._dup_cache    = {"stale": True}
        rr._dup_cache_ts = 9_999_999_999.0
        self._lib.add_book_file("reading/OldName/Book.epub", b"x" * 100)
        self._seed_book(author="OldName", relative_path="reading/OldName/Book.epub")
        self._post("/api/authors/merge", {"source": "OldName", "target": "NewName"})
        self.assertIsNone(rr._dup_cache)

    def test_nonexistent_source_returns_200_zero_moved(self):
        """Merging a source that has no folders is a no-op, not an error."""
        resp = self._post(
            "/api/authors/merge",
            {"source": "Ghost Author", "target": "Real Author"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["moved"], 0)


# ---------------------------------------------------------------------------
# PATCH /api/books/title
# ---------------------------------------------------------------------------

class TestUpdateTitle(ApiWriteBase):

    def setUp(self):
        super().setUp()
        self._seed_book(title="Old Title")

    def test_400_missing_title(self):
        resp = self._patch("/api/books/title", {"original_path": "/src/book.epub"})
        self.assertEqual(resp.status_code, 400)

    def test_400_missing_original_path(self):
        resp = self._patch("/api/books/title", {"title": "New Title"})
        self.assertEqual(resp.status_code, 400)

    def test_404_book_not_in_db(self):
        resp = self._patch("/api/books/title", {"original_path": "/missing.epub", "title": "X"})
        self.assertEqual(resp.status_code, 404)

    def test_updates_title_in_db(self):
        self._patch("/api/books/title", {"original_path": "/src/book.epub", "title": "New Title"})
        self.assertEqual(self._book_row()["title"], "New Title")

    def test_response_contains_new_title(self):
        resp = self._patch("/api/books/title", {"original_path": "/src/book.epub", "title": "New Title"})
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["title"], "New Title")

    def test_whitespace_trimmed(self):
        self._patch("/api/books/title", {"original_path": "/src/book.epub", "title": "  Trimmed  "})
        self.assertEqual(self._book_row()["title"], "Trimmed")

    def test_file_not_moved(self):
        original_rel = self._book_row()["relative_path"]
        self._patch("/api/books/title", {"original_path": "/src/book.epub", "title": "New Title"})
        self.assertEqual(self._book_row()["relative_path"], original_rel)

    def test_empty_title_rejected(self):
        resp = self._patch("/api/books/title", {"original_path": "/src/book.epub", "title": "   "})
        self.assertEqual(resp.status_code, 400)


# ---------------------------------------------------------------------------
# PATCH /api/books/language
# ---------------------------------------------------------------------------

class TestUpdateLanguage(ApiWriteBase):

    def setUp(self):
        super().setUp()
        self._seed_book(language="english")

    def test_400_missing_language(self):
        resp = self._patch("/api/books/language", {"original_path": "/src/book.epub"})
        self.assertEqual(resp.status_code, 400)

    def test_400_missing_original_path(self):
        resp = self._patch("/api/books/language", {"language": "french"})
        self.assertEqual(resp.status_code, 400)

    def test_404_book_not_in_db(self):
        resp = self._patch("/api/books/language", {"original_path": "/missing.epub", "language": "french"})
        self.assertEqual(resp.status_code, 404)

    def test_updates_language_in_db(self):
        self._patch("/api/books/language", {"original_path": "/src/book.epub", "language": "french"})
        self.assertEqual(self._book_row()["language"], "french")

    def test_response_ok_and_new_language(self):
        resp = self._patch("/api/books/language", {"original_path": "/src/book.epub", "language": "french"})
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["language"], "french")

    def test_new_language_accepted(self):
        """A language not yet in the DB (brand-new) must be accepted."""
        resp = self._patch("/api/books/language", {
            "original_path": "/src/book.epub", "language": "klingon"
        })
        self.assertTrue(resp.get_json()["ok"])
        self.assertEqual(self._book_row()["language"], "klingon")

    def test_whitespace_trimmed(self):
        self._patch("/api/books/language", {"original_path": "/src/book.epub", "language": "  german  "})
        self.assertEqual(self._book_row()["language"], "german")

    def test_empty_language_rejected(self):
        resp = self._patch("/api/books/language", {"original_path": "/src/book.epub", "language": "  "})
        self.assertEqual(resp.status_code, 400)

    def test_file_not_moved(self):
        original_rel = self._book_row()["relative_path"]
        self._patch("/api/books/language", {"original_path": "/src/book.epub", "language": "spanish"})
        self.assertEqual(self._book_row()["relative_path"], original_rel)


# ---------------------------------------------------------------------------
# GET /api/books?language= (language filter)
# ---------------------------------------------------------------------------

class TestBooksLanguageFilter(ApiWriteBase):

    def setUp(self):
        super().setUp()
        self._seed_book(original_path="/en.epub",  language="english", title="English Book")
        self._seed_book(original_path="/fr.epub",  language="french",  title="French Book",
                        relative_path="reading/Auth/fr.epub")
        self._seed_book(original_path="/nl.epub",  language=None,      title="No Language Book",
                        relative_path="reading/Auth/nl.epub")

    def _get_books(self, **params):
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        return self._client.get(f"/api/books?{qs}").get_json()

    def test_filter_exact_english(self):
        data = self._get_books(language="english")
        titles = [b["title"] for b in data["books"]]
        self.assertIn("English Book", titles)
        self.assertNotIn("French Book", titles)
        self.assertNotIn("No Language Book", titles)

    def test_filter_exact_french(self):
        data = self._get_books(language="french")
        titles = [b["title"] for b in data["books"]]
        self.assertIn("French Book", titles)
        self.assertNotIn("English Book", titles)

    def test_filter_empty_string_returns_null_language_books(self):
        """language= (empty) must return books where language IS NULL."""
        data = self._get_books(language="")
        titles = [b["title"] for b in data["books"]]
        self.assertIn("No Language Book", titles)
        self.assertNotIn("English Book", titles)
        self.assertNotIn("French Book", titles)

    def test_no_language_param_returns_all(self):
        data = self._get_books()
        self.assertEqual(data["total"], 3)

    def test_unknown_language_returns_empty(self):
        data = self._get_books(language="klingon")
        self.assertEqual(data["total"], 0)

    def test_language_filter_combines_with_q(self):
        """language= and q= filters must AND together."""
        data = self._get_books(language="english", q="English")
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["books"][0]["title"], "English Book")

    def test_language_filter_not_a_fulltext_search(self):
        """language=english must NOT match books whose title contains 'english'."""
        # Seed a book with title containing "english" but a different language
        self._seed_book(original_path="/trick.epub", language="french",
                        title="An English history book",
                        relative_path="reading/Auth/trick.epub")
        data = self._get_books(language="english")
        titles = [b["title"] for b in data["books"]]
        self.assertNotIn("An English history book", titles)


if __name__ == "__main__":
    unittest.main()
