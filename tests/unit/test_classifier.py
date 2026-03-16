"""
tests/unit/test_classifier.py

Unit tests for organizer/classifier.py.

Covers:
  - normalize_author()      author name flipping and suffix handling
  - sanitize()              illegal-character stripping
  - first_author()          picks and sanitizes the first name in a list
  - guess_from_filename()   heuristic title/author extraction from stems
  - detect_language()       word-frequency fallback (langdetect mocked out)
  - genre_from_subjects()   subject-tag → genre mapping
  - genre_from_text()       keyword scanning over title + sample text
  - genre_to_main_category() genre → top-level folder
  - _score()                confidence scoring logic
  - destination()           path construction for normal and fallback books
  - BookMeta dataclass      default field values
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure the project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from organizer.classifier import (
    BookMeta,
    _add_genre,
    _score,
    destination,
    detect_language,
    first_author,
    genre_from_subjects,
    genre_from_text,
    genre_to_main_category,
    guess_from_filename,
    normalize_author,
    sanitize,
)


# ---------------------------------------------------------------------------
# normalize_author
# ---------------------------------------------------------------------------

class TestNormalizeAuthor(unittest.TestCase):

    def test_lastname_firstname_flipped(self):
        self.assertEqual(normalize_author("King, Stephen"), "Stephen King")

    def test_no_comma_unchanged(self):
        self.assertEqual(normalize_author("Stephen King"), "Stephen King")

    def test_empty_string(self):
        self.assertEqual(normalize_author(""), "")

    def test_none_like_empty(self):
        self.assertEqual(normalize_author(None), "")

    def test_with_jr_suffix(self):
        # The regex \b(Jr\.?)\b matches "Jr" (word-boundary before the dot),
        # so the suffix is stored without the trailing dot.
        result = normalize_author("King, Stephen Jr.")
        self.assertIn("Jr", result)
        self.assertTrue(result.startswith("Stephen"))

    def test_with_sr_suffix(self):
        result = normalize_author("Smith, John Sr.")
        self.assertIn("Sr", result)

    def test_strips_surrounding_whitespace(self):
        self.assertEqual(normalize_author("  King, Stephen  "), "Stephen King")

    def test_multiple_word_firstname(self):
        result = normalize_author("Tolkien, J. R. R.")
        self.assertEqual(result, "J. R. R. Tolkien")

    def test_single_name_no_comma(self):
        self.assertEqual(normalize_author("Plato"), "Plato")


# ---------------------------------------------------------------------------
# sanitize
# ---------------------------------------------------------------------------

class TestSanitize(unittest.TestCase):

    def test_removes_illegal_chars(self):
        self.assertEqual(sanitize('My: Book/Title'), "My_ Book_Title")

    def test_collapses_whitespace(self):
        self.assertEqual(sanitize("Too   Many   Spaces"), "Too Many Spaces")

    def test_empty_becomes_unknown(self):
        self.assertEqual(sanitize(""), "Unknown")

    def test_none_becomes_unknown(self):
        self.assertEqual(sanitize(None), "Unknown")

    def test_backslash_replaced(self):
        self.assertNotIn("\\", sanitize("Win\\Path"))

    def test_angle_brackets_replaced(self):
        result = sanitize("a<b>c")
        self.assertNotIn("<", result)
        self.assertNotIn(">", result)

    def test_normal_name_unchanged(self):
        self.assertEqual(sanitize("Stephen King"), "Stephen King")


# ---------------------------------------------------------------------------
# first_author
# ---------------------------------------------------------------------------

class TestFirstAuthor(unittest.TestCase):

    def test_empty_list(self):
        self.assertEqual(first_author([]), "Unknown Author")

    def test_single_author(self):
        self.assertEqual(first_author(["King, Stephen"]), "Stephen King")

    def test_multiple_authors_takes_first(self):
        result = first_author(["Tolkien, J. R. R.", "Another, Author"])
        self.assertEqual(result, "J. R. R. Tolkien")

    def test_author_with_illegal_chars(self):
        result = first_author(["Author/With:Slash"])
        self.assertNotIn("/", result)


# ---------------------------------------------------------------------------
# guess_from_filename
# ---------------------------------------------------------------------------

class TestGuessFromFilename(unittest.TestCase):

    def test_dash_separated(self):
        title, authors = guess_from_filename(Path("Stephen King - It.epub"))
        self.assertIn("It", title)
        self.assertIn("Stephen King", authors)

    def test_em_dash_separated(self):
        title, authors = guess_from_filename(Path("Author \u2013 Title.epub"))
        self.assertIn("Title", title)

    def test_no_separator_returns_stem_as_title(self):
        title, authors = guess_from_filename(Path("SomeTitleNoAuthor.epub"))
        self.assertIn("SomeTitleNoAuthor", title)
        self.assertEqual(authors, [])

    def test_underscores_treated_as_spaces(self):
        title, authors = guess_from_filename(Path("Author_Name - Book_Title.epub"))
        self.assertIn("Book Title", title)


# ---------------------------------------------------------------------------
# detect_language  (word-frequency fallback, no langdetect)
# ---------------------------------------------------------------------------

class TestDetectLanguage(unittest.TestCase):

    def setUp(self):
        # Force the word-frequency branch by pretending langdetect is absent
        import organizer.classifier as clf
        self._orig = clf.LANGDETECT_OK
        clf.LANGDETECT_OK = False

    def tearDown(self):
        import organizer.classifier as clf
        clf.LANGDETECT_OK = self._orig

    def test_english_text(self):
        text = "the and of is in the cat sat on the mat and the dog ran"
        lang = detect_language(text)
        self.assertEqual(lang, "english")

    def test_german_text(self):
        text = "der die das und ist der Mann die Frau das Kind und ist"
        lang = detect_language(text)
        self.assertEqual(lang, "german")

    def test_empty_returns_unknown(self):
        self.assertEqual(detect_language(""), "unknown")

    def test_whitespace_only_returns_unknown(self):
        self.assertEqual(detect_language("   "), "unknown")

    def test_gibberish_no_crash(self):
        result = detect_language("xqzjpw kvmlrt bfshq")
        self.assertIsInstance(result, str)


# ---------------------------------------------------------------------------
# genre_from_subjects
# ---------------------------------------------------------------------------

class TestGenreFromSubjects(unittest.TestCase):

    def test_cooking_subject(self):
        self.assertEqual(genre_from_subjects(["Cooking"]), "cookbooks")

    def test_fiction_subject(self):
        self.assertEqual(genre_from_subjects(["Fiction"]), "fiction")

    def test_multiple_subjects_first_match_wins(self):
        result = genre_from_subjects(["Science Fiction", "Adventure"])
        self.assertEqual(result, "sci-fi")

    def test_empty_list_returns_none(self):
        self.assertIsNone(genre_from_subjects([]))

    def test_no_match_returns_none(self):
        self.assertIsNone(genre_from_subjects(["Unknownstuff"]))

    def test_slash_separated_subject(self):
        # "Cooking/Food" should still match
        result = genre_from_subjects(["Cooking/Food"])
        self.assertIsNotNone(result)

    def test_sport_subject(self):
        result = genre_from_subjects(["Sports"])
        self.assertIsNotNone(result)


# ---------------------------------------------------------------------------
# genre_from_text
# ---------------------------------------------------------------------------

class TestGenreFromText(unittest.TestCase):

    def test_keyword_in_title(self):
        genre, source = genre_from_text("The Cookbook", "")
        self.assertEqual(genre, "cookbooks")
        self.assertEqual(source, "keyword_title")

    def test_keyword_in_sample(self):
        genre, source = genre_from_text("My Book", "lots of recipes and cooking tips")
        self.assertEqual(genre, "cookbooks")
        self.assertEqual(source, "keyword_text")

    def test_title_takes_precedence_over_sample(self):
        genre, source = genre_from_text("Yoga Basics", "thriller mystery detective")
        self.assertEqual(source, "keyword_title")

    def test_no_match_returns_other(self):
        genre, source = genre_from_text("Zzz", "qqqq")
        self.assertEqual(genre, "other")
        self.assertEqual(source, "default")

    def test_thriller_keyword(self):
        genre, source = genre_from_text("The Detective", "")
        self.assertEqual(genre, "thriller")

    def test_fantasy_keyword(self):
        genre, _ = genre_from_text("", "dragons and wizards and magic spells")
        self.assertEqual(genre, "fantasy")


# ---------------------------------------------------------------------------
# genre_to_main_category
# ---------------------------------------------------------------------------

class TestGenreToMainCategory(unittest.TestCase):

    def test_cookbooks_genre(self):
        self.assertEqual(genre_to_main_category("cookbooks"), "cookbooks")

    def test_fiction_maps_to_reading(self):
        self.assertEqual(genre_to_main_category("fiction"), "reading")

    def test_thriller_maps_to_reading(self):
        self.assertEqual(genre_to_main_category("thriller"), "reading")

    def test_yoga_maps_to_sport_category(self):
        self.assertEqual(genre_to_main_category("yoga"), "sport_workout_yoga_health")

    def test_unknown_maps_to_other(self):
        self.assertEqual(genre_to_main_category("unicorns"), "other")

    def test_empty_maps_to_other(self):
        self.assertEqual(genre_to_main_category(""), "other")

    def test_case_insensitive(self):
        self.assertEqual(genre_to_main_category("Cookbooks"), "cookbooks")


# ---------------------------------------------------------------------------
# _add_genre / _score
# ---------------------------------------------------------------------------

class TestAddGenre(unittest.TestCase):

    def test_adds_new_genre(self):
        m = BookMeta()
        _add_genre(m, "thriller")
        self.assertIn("thriller", m.all_genres)

    def test_does_not_add_duplicate(self):
        m = BookMeta()
        _add_genre(m, "thriller")
        _add_genre(m, "thriller")
        self.assertEqual(m.all_genres.count("thriller"), 1)

    def test_does_not_add_other(self):
        m = BookMeta()
        _add_genre(m, "other")
        self.assertNotIn("other", m.all_genres)

    def test_does_not_add_unknown(self):
        m = BookMeta()
        _add_genre(m, "unknown")
        self.assertNotIn("unknown", m.all_genres)


class TestScore(unittest.TestCase):

    def test_unknown_everything_gives_low_score(self):
        m = BookMeta()
        _score(m)
        self.assertEqual(m.confidence, 0)

    def test_known_author_adds_points(self):
        m = BookMeta(author="Stephen King", sources=["library"])
        _score(m)
        self.assertGreater(m.confidence, 0)

    def test_ollama_source_boosts_score(self):
        m_no_ollama = BookMeta(
            author="Author", language="english", category="reading",
            sources=["library", "keyword_title"],
        )
        m_ollama = BookMeta(
            author="Author", language="english", category="reading",
            sources=["library", "ollama"],
        )
        _score(m_no_ollama)
        _score(m_ollama)
        self.assertGreater(m_ollama.confidence, m_no_ollama.confidence)

    def test_score_capped_at_100(self):
        m = BookMeta(
            author="Author", language="english", category="reading",
            sources=["library", "online", "online_lang", "subjects_online",
                     "langdetect", "ollama", "keyword_title"],
        )
        _score(m)
        self.assertLessEqual(m.confidence, 100)

    def test_library_lang_scores_higher_than_langdetect_alone(self):
        # "library" is a substring of "library_lang", so the author-bonus
        # section awards an extra +10 for library_lang (43 total) vs langdetect
        # alone which only earns the language points (35 total).
        m1 = BookMeta(author="A", language="english", sources=["library_lang"])
        m2 = BookMeta(author="A", language="english", sources=["langdetect"])
        _score(m1)
        _score(m2)
        self.assertGreater(m1.confidence, m2.confidence)


# ---------------------------------------------------------------------------
# BookMeta defaults
# ---------------------------------------------------------------------------

class TestBookMetaDefaults(unittest.TestCase):

    def test_default_title(self):
        self.assertEqual(BookMeta().title, "Unknown")

    def test_default_author(self):
        self.assertEqual(BookMeta().author, "Unknown Author")

    def test_default_language(self):
        self.assertEqual(BookMeta().language, "unknown")

    def test_default_confidence(self):
        self.assertEqual(BookMeta().confidence, 0)

    def test_default_all_genres_is_empty_list(self):
        m1, m2 = BookMeta(), BookMeta()
        m1.all_genres.append("thriller")
        self.assertEqual(m2.all_genres, [])  # dataclass field not shared


# ---------------------------------------------------------------------------
# destination()
# ---------------------------------------------------------------------------

class TestDestination(unittest.TestCase):

    def _meta(self, **kw):
        defaults = dict(
            author="Stephen King",
            language="english",
            category="reading",
            fallback=False,
        )
        defaults.update(kw)
        return BookMeta(**defaults)

    def test_normal_path_structure(self):
        p = Path("/tmp/It.epub")
        dest = destination(p, self._meta())
        parts = dest.parts
        self.assertIn("reading",      parts)
        self.assertIn("Stephen King", parts)
        self.assertIn("english",      parts)
        self.assertEqual(dest.name, "It.epub")

    def test_fallback_pdf_goes_to_pdf_folder(self):
        p = Path("/tmp/scanned.pdf")
        dest = destination(p, self._meta(fallback=True))
        self.assertIn("pdf", dest.parts)

    def test_fallback_epub_goes_to_unknown_folder(self):
        p = Path("/tmp/broken.epub")
        dest = destination(p, self._meta(fallback=True))
        self.assertIn("unknown", dest.parts)

    def test_category_reflected_in_path(self):
        p = Path("/tmp/recipe.epub")
        dest = destination(p, self._meta(category="cookbooks"))
        self.assertIn("cookbooks", dest.parts)

    def test_author_used_as_path_component(self):
        # destination() trusts that meta.author was already sanitized by
        # resolve() → first_author() → sanitize(). It places the author
        # string directly into the path without re-sanitizing.
        p = Path("/tmp/book.epub")
        dest = destination(p, self._meta(author="Frank Herbert"))
        self.assertIn("Frank Herbert", str(dest))


if __name__ == "__main__":
    unittest.main()
