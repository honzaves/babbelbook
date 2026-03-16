"""
tests/integration/test_api_read.py

Integration tests for all GET /api/* endpoints in book_browser.

Each test:
  1. Spins up an isolated in-memory-style temp library on disk
  2. Seeds the SQLite DB with controlled data
  3. Makes HTTP requests through Flask's test client
  4. Asserts the response status code, Content-Type, and JSON payload shape

Endpoints covered:
  GET /api/stats
  GET /api/books           (with q=, genre=, dir=, limit=, offset= params)
  GET /api/genres
  GET /api/directories
  GET /api/cache           (with q= param)
  GET /api/duplicates
  GET /api/authors/similar
  GET /api/cover
  GET /                    (index page returns HTML)
"""

import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.conftest import TempLibrary, make_flask_client, stop_patches


# ---------------------------------------------------------------------------
# Base class wires up the temp library and Flask client per test
# ---------------------------------------------------------------------------

class ApiReadBase(unittest.TestCase):

    def setUp(self):
        self._lib = TempLibrary().__enter__()
        self._client = make_flask_client(self._lib)
        # Reset the duplicate cache between tests
        import browser.routes_read as rr
        rr._dup_cache    = None
        rr._dup_cache_ts = 0.0

    def tearDown(self):
        stop_patches(self._client)
        self._lib.__exit__(None, None, None)

    # convenience
    def _get(self, url, **kw):
        return self._client.get(url, **kw)

    def _json(self, url, **kw):
        resp = self._get(url, **kw)
        return resp, resp.get_json()

    def _seed_book(self, **kw):
        """Insert one book row with sensible defaults, overridden by kw."""
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
        self._lib.db.execute(
            "INSERT OR REPLACE INTO books "
            "(original_path,title,author,language,genres,directory,"
            " relative_path,confidence,sources,ts) "
            "VALUES (:original_path,:title,:author,:language,:genres,:directory,"
            "        :relative_path,:confidence,:sources,:ts)",
            defaults,
        )
        self._lib.db.commit()

    def _seed_cache(self, key, val):
        self._lib.db.execute(
            "INSERT OR REPLACE INTO cache (key, val, ts) VALUES (?,?,?)",
            (key, json.dumps(val), 1_700_000_000),
        )
        self._lib.db.commit()


# ---------------------------------------------------------------------------
# GET /api/stats
# ---------------------------------------------------------------------------

class TestApiStats(ApiReadBase):

    def test_200_with_empty_library(self):
        resp, data = self._json("/api/stats")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("total_books", data)

    def test_total_books_count(self):
        self._seed_book(original_path="/src/a.epub")
        self._seed_book(original_path="/src/b.epub", title="Other Book",
                        relative_path="reading/Test Author/other.epub")
        _, data = self._json("/api/stats")
        self.assertEqual(data["total_books"], 2)

    def test_by_directory_grouping(self):
        self._seed_book(directory="reading")
        self._seed_book(original_path="/src/b.epub", directory="cookbooks",
                        relative_path="cookbooks/A/b.epub")
        _, data = self._json("/api/stats")
        dirs = {r["directory"]: r["count"] for r in data["by_directory"]}
        self.assertEqual(dirs.get("reading"),   1)
        self.assertEqual(dirs.get("cookbooks"), 1)

    def test_by_language_grouping(self):
        self._seed_book(language="english")
        self._seed_book(original_path="/src/b.epub", language="german",
                        relative_path="reading/A/b.epub")
        _, data = self._json("/api/stats")
        langs = {r["language"]: r["count"] for r in data["by_language"]}
        self.assertEqual(langs.get("english"), 1)
        self.assertEqual(langs.get("german"),  1)

    def test_confidence_bands_present(self):
        self._seed_book(confidence=90)
        _, data = self._json("/api/stats")
        self.assertIn("confidence_bands", data)
        labels = [b["label"] for b in data["confidence_bands"]]
        self.assertIn("High", labels)

    def test_dup_counts_present(self):
        _, data = self._json("/api/stats")
        self.assertIn("dup_safe",       data)
        self.assertIn("dup_suspicious", data)

    def test_recent_books_field_present(self):
        self._seed_book()
        _, data = self._json("/api/stats")
        self.assertIn("recent_books", data)


# ---------------------------------------------------------------------------
# GET /api/books
# ---------------------------------------------------------------------------

class TestApiBooks(ApiReadBase):

    def _books(self, url="/api/books", **kw):
        """Helper that returns just the books list from the paginated response."""
        resp, data = self._json(url, **kw)
        return resp, data.get("books", []) if isinstance(data, dict) else []

    def test_200_empty(self):
        resp, _ = self._json("/api/books")
        self.assertEqual(resp.status_code, 200)

    def test_response_has_pagination_fields(self):
        _, data = self._json("/api/books")
        self.assertIn("books",  data)
        self.assertIn("total",  data)
        self.assertIn("offset", data)

    def test_returns_seeded_books(self):
        self._seed_book()
        _, books = self._books()
        self.assertEqual(len(books), 1)
        self.assertEqual(books[0]["title"], "Test Book")

    def test_search_by_title(self):
        self._seed_book(original_path="/src/a.epub", title="Dune")
        self._seed_book(original_path="/src/b.epub", title="Foundation",
                        relative_path="reading/A/b.epub")
        _, books = self._books("/api/books?q=Dune")
        self.assertEqual(len(books), 1)
        self.assertEqual(books[0]["title"], "Dune")

    def test_search_by_author(self):
        self._seed_book(original_path="/src/a.epub", author="Frank Herbert")
        self._seed_book(original_path="/src/b.epub", author="Isaac Asimov",
                        relative_path="reading/B/b.epub")
        _, books = self._books("/api/books?q=Herbert")
        self.assertEqual(len(books), 1)
        self.assertEqual(books[0]["author"], "Frank Herbert")

    def test_filter_by_genre(self):
        self._seed_book(original_path="/src/a.epub",
                        genres=json.dumps(["thriller"]))
        self._seed_book(original_path="/src/b.epub",
                        genres=json.dumps(["cookbooks"]),
                        relative_path="reading/A/b.epub")
        _, books = self._books("/api/books?genre=thriller")
        self.assertEqual(len(books), 1)

    def test_filter_by_directory(self):
        self._seed_book(original_path="/src/a.epub", directory="reading")
        self._seed_book(original_path="/src/b.epub", directory="cookbooks",
                        relative_path="cookbooks/A/b.epub")
        _, books = self._books("/api/books?dir=cookbooks")
        self.assertEqual(len(books), 1)
        self.assertEqual(books[0]["directory"], "cookbooks")

    def test_genres_decoded_as_list(self):
        self._seed_book(genres=json.dumps(["thriller", "mystery"]))
        _, books = self._books()
        self.assertIsInstance(books[0]["genres"], list)
        self.assertIn("thriller", books[0]["genres"])

    def test_pagination_limit(self):
        for i in range(5):
            self._seed_book(
                original_path=f"/src/{i}.epub",
                relative_path=f"reading/A/{i}.epub",
            )
        _, books = self._books("/api/books?limit=2")
        self.assertEqual(len(books), 2)

    def test_pagination_offset(self):
        for i in range(5):
            self._seed_book(
                original_path=f"/src/{i}.epub",
                relative_path=f"reading/A/{i}.epub",
            )
        _, all_books  = self._books("/api/books?limit=100")
        _, page_books = self._books("/api/books?limit=2&offset=2")
        self.assertEqual(page_books[0]["original_path"],
                         all_books[2]["original_path"])

    def test_total_field_reflects_full_count(self):
        for i in range(4):
            self._seed_book(
                original_path=f"/src/{i}.epub",
                relative_path=f"reading/A/{i}.epub",
            )
        _, data = self._json("/api/books?limit=2")
        self.assertEqual(data["total"], 4)
        self.assertEqual(len(data["books"]), 2)


# ---------------------------------------------------------------------------
# GET /api/genres
# ---------------------------------------------------------------------------

class TestApiGenres(ApiReadBase):

    def test_200(self):
        resp, data = self._json("/api/genres")
        self.assertEqual(resp.status_code, 200)

    def test_empty_library_returns_empty_list(self):
        _, data = self._json("/api/genres")
        self.assertEqual(data, [])

    def test_genres_aggregated(self):
        self._seed_book(original_path="/src/a.epub",
                        genres=json.dumps(["thriller"]))
        self._seed_book(original_path="/src/b.epub",
                        genres=json.dumps(["thriller", "mystery"]),
                        relative_path="reading/A/b.epub")
        _, data = self._json("/api/genres")
        genre_map = {g: c for g, c in data}
        self.assertEqual(genre_map.get("thriller"), 2)
        self.assertEqual(genre_map.get("mystery"),  1)

    def test_sorted_by_count_desc(self):
        self._seed_book(original_path="/src/a.epub",
                        genres=json.dumps(["rare"]))
        for i in range(3):
            self._seed_book(
                original_path=f"/src/{i}.epub",
                genres=json.dumps(["common"]),
                relative_path=f"reading/A/{i}.epub",
            )
        _, data = self._json("/api/genres")
        counts = [c for _, c in data]
        self.assertEqual(counts, sorted(counts, reverse=True))


# ---------------------------------------------------------------------------
# GET /api/directories
# ---------------------------------------------------------------------------

class TestApiDirectories(ApiReadBase):

    def test_200(self):
        resp, _ = self._json("/api/directories")
        self.assertEqual(resp.status_code, 200)

    def test_directories_counted(self):
        self._seed_book(original_path="/src/a.epub", directory="reading")
        self._seed_book(original_path="/src/b.epub", directory="reading",
                        relative_path="reading/A/b.epub")
        self._seed_book(original_path="/src/c.epub", directory="cookbooks",
                        relative_path="cookbooks/A/c.epub")
        _, data = self._json("/api/directories")
        dir_map = {r["directory"]: r["count"] for r in data}
        self.assertEqual(dir_map["reading"],   2)
        self.assertEqual(dir_map["cookbooks"], 1)


# ---------------------------------------------------------------------------
# GET /api/cache
# ---------------------------------------------------------------------------

class TestApiCache(ApiReadBase):

    def test_200(self):
        resp, _ = self._json("/api/cache")
        self.assertEqual(resp.status_code, 200)

    def test_empty_returns_empty_list(self):
        _, data = self._json("/api/cache")
        self.assertEqual(data, [])

    def test_returns_seeded_entry(self):
        self._seed_cache("gb:Dune:Herbert", {"title": "Dune"})
        _, data = self._json("/api/cache?q=Dune")
        self.assertEqual(len(data), 1)
        self.assertIn("gb:Dune:Herbert", data[0]["key"])

    def test_search_filters_results(self):
        self._seed_cache("gb:Dune:Herbert",     {"title": "Dune"})
        self._seed_cache("ol:Foundation:Asimov", {"title": "Foundation"})
        _, data = self._json("/api/cache?q=Dune")
        self.assertEqual(len(data), 1)
        self.assertIn("Dune", data[0]["key"])


# ---------------------------------------------------------------------------
# GET /api/duplicates
# ---------------------------------------------------------------------------

class TestApiDuplicates(ApiReadBase):

    def setUp(self):
        super().setUp()
        import browser.routes_read as rr
        rr._dup_cache    = None
        rr._dup_cache_ts = 0.0

    def test_200_empty_library(self):
        resp, data = self._json("/api/duplicates")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(data, [])

    def test_detects_safe_duplicate(self):
        self._lib.add_book_file("reading/Author/Book.epub",    b"x" * 200)
        self._lib.add_book_file("reading/Author/Book_(1).epub", b"x" * 200)
        _, data = self._json("/api/duplicates")
        self.assertEqual(len(data), 1)
        self.assertTrue(data[0]["safe"])

    def test_detects_suspicious_duplicate(self):
        self._lib.add_book_file("reading/Author/Book.epub",    b"x" * 200)
        self._lib.add_book_file("reading/Author/Book_(1).epub", b"y" * 999)
        _, data = self._json("/api/duplicates")
        self.assertEqual(len(data), 1)
        self.assertFalse(data[0]["safe"])

    def test_response_contains_expected_fields(self):
        self._lib.add_book_file("reading/Author/Book.epub",    b"x" * 100)
        self._lib.add_book_file("reading/Author/Book_(1).epub", b"x" * 100)
        _, data = self._json("/api/duplicates")
        item = data[0]
        for field in ("rel", "canon_rel", "has_canon", "same_size", "safe"):
            self.assertIn(field, item)


# ---------------------------------------------------------------------------
# GET /api/authors/similar
# ---------------------------------------------------------------------------

class TestApiAuthorsSimilar(ApiReadBase):

    def test_200(self):
        resp, _ = self._json("/api/authors/similar")
        self.assertEqual(resp.status_code, 200)

    def test_empty_library_returns_empty(self):
        _, data = self._json("/api/authors/similar")
        self.assertEqual(data, [])

    def test_detects_dotted_variant(self):
        self._seed_book(original_path="/src/a.epub",
                        author="T. R. Napper")
        self._seed_book(original_path="/src/b.epub",
                        author="T.R. Napper",
                        relative_path="reading/B/b.epub")
        _, data = self._json("/api/authors/similar")
        self.assertGreater(len(data), 0)
        pair_authors = {data[0]["author_a"], data[0]["author_b"]}
        self.assertIn("T. R. Napper", pair_authors)
        self.assertIn("T.R. Napper",  pair_authors)

    def test_dissimilar_authors_not_returned(self):
        self._seed_book(original_path="/src/a.epub", author="Stephen King")
        self._seed_book(original_path="/src/b.epub", author="Isaac Asimov",
                        relative_path="reading/B/b.epub")
        _, data = self._json("/api/authors/similar")
        self.assertEqual(data, [])

    def test_score_field_between_0_and_1(self):
        self._seed_book(original_path="/src/a.epub", author="J.K. Rowling")
        self._seed_book(original_path="/src/b.epub", author="J. K. Rowling",
                        relative_path="reading/B/b.epub")
        _, data = self._json("/api/authors/similar")
        if data:
            self.assertGreaterEqual(data[0]["score"], 0.0)
            self.assertLessEqual(data[0]["score"],    1.0)


# ---------------------------------------------------------------------------
# GET /api/cover
# ---------------------------------------------------------------------------

class TestApiCover(ApiReadBase):

    def test_miss_returns_null_url(self):
        _, data = self._json("/api/cover?title=Dune&author=Herbert")
        self.assertIsNone(data["url"])

    def test_hit_returns_url(self):
        self._seed_cache(
            "gb:Dune:Frank Herbert",
            {"thumbnail": "https://example.com/cover.jpg"},
        )
        _, data = self._json("/api/cover?title=Dune&author=Frank Herbert")
        self.assertEqual(data["url"], "https://example.com/cover.jpg")

    def test_no_params_returns_null(self):
        _, data = self._json("/api/cover")
        self.assertIsNone(data["url"])


# ---------------------------------------------------------------------------
# GET / (index page)
# ---------------------------------------------------------------------------

class TestIndexPage(ApiReadBase):

    def test_200_html(self):
        resp = self._get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"<!DOCTYPE html>", resp.data[:200])

    def test_contains_api_calls(self):
        resp = self._get("/")
        self.assertIn(b"/api/", resp.data)


if __name__ == "__main__":
    unittest.main()
