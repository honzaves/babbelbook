"""
tests/unit/test_language_map.py

Unit tests for config.LANGUAGE_MAP.

Covers:
  - All 16 canonical language names are reachable
  - Every ISO 639-1 (2-letter) code resolves correctly
  - Every ISO 639-2 (3-letter) code resolves correctly
  - Languages with multiple 3-letter variants (fr: fre/fra, de: ger/deu,
    nl: dut/nld, cs: cze/ces) all resolve to the same value
  - Unknown codes return None (no KeyError, no silent wrong result)
  - Map is used correctly in classifier.detect_language()
  - Map is used correctly in enrichment helpers (Google Books + Open Library)
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from config import LANGUAGE_MAP


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EXPECTED_LANGUAGES = {
    "english", "spanish", "french", "german", "chinese",
    "portuguese", "russian", "japanese", "arabic", "hindi",
    "italian", "korean", "dutch", "polish", "bengali", "czech",
}

# Every code that must be in the map, grouped by canonical name
CODE_TABLE = {
    "english":    ["en", "eng"],
    "spanish":    ["es", "spa"],
    "french":     ["fr", "fre", "fra"],
    "german":     ["de", "ger", "deu"],
    "chinese":    ["zh", "chi", "zho"],
    "portuguese": ["pt", "por"],
    "russian":    ["ru", "rus"],
    "japanese":   ["ja", "jpn"],
    "arabic":     ["ar", "ara"],
    "hindi":      ["hi", "hin"],
    "italian":    ["it", "ita"],
    "korean":     ["ko", "kor"],
    "dutch":      ["nl", "dut", "nld"],
    "polish":     ["pl", "pol"],
    "bengali":    ["bn", "ben"],
    "czech":      ["cs", "cze", "ces"],
}


# ---------------------------------------------------------------------------
# LANGUAGE_MAP structure tests
# ---------------------------------------------------------------------------

class TestLanguageMapStructure(unittest.TestCase):

    def test_all_expected_languages_reachable(self):
        """Every canonical language name must appear as a value."""
        values = set(LANGUAGE_MAP.values())
        missing = EXPECTED_LANGUAGES - values
        self.assertFalse(missing, f"Missing languages: {missing}")

    def test_no_unexpected_languages(self):
        """No language name should appear that is not in our expected set."""
        extra = set(LANGUAGE_MAP.values()) - EXPECTED_LANGUAGES
        self.assertFalse(extra, f"Unexpected language values: {extra}")

    def test_all_values_are_lowercase_strings(self):
        for code, name in LANGUAGE_MAP.items():
            self.assertIsInstance(name, str, f"Value for {code!r} is not a string")
            self.assertEqual(name, name.lower(), f"Value {name!r} for {code!r} is not lowercase")

    def test_all_keys_are_lowercase_strings(self):
        for code in LANGUAGE_MAP:
            self.assertIsInstance(code, str)
            self.assertEqual(code, code.lower(), f"Key {code!r} is not lowercase")

    def test_sixteen_canonical_languages(self):
        self.assertEqual(len(EXPECTED_LANGUAGES), 16)
        self.assertEqual(set(LANGUAGE_MAP.values()), EXPECTED_LANGUAGES)


# ---------------------------------------------------------------------------
# ISO 639-1 (2-letter) code tests
# ---------------------------------------------------------------------------

class TestTwoLetterCodes(unittest.TestCase):

    def _assert_code(self, code, expected):
        self.assertIn(code, LANGUAGE_MAP, f"ISO 639-1 code {code!r} missing from map")
        self.assertEqual(LANGUAGE_MAP[code], expected,
                         f"LANGUAGE_MAP[{code!r}] should be {expected!r}")

    def test_en(self): self._assert_code("en", "english")
    def test_es(self): self._assert_code("es", "spanish")
    def test_fr(self): self._assert_code("fr", "french")
    def test_de(self): self._assert_code("de", "german")
    def test_zh(self): self._assert_code("zh", "chinese")
    def test_pt(self): self._assert_code("pt", "portuguese")
    def test_ru(self): self._assert_code("ru", "russian")
    def test_ja(self): self._assert_code("ja", "japanese")
    def test_ar(self): self._assert_code("ar", "arabic")
    def test_hi(self): self._assert_code("hi", "hindi")
    def test_it(self): self._assert_code("it", "italian")
    def test_ko(self): self._assert_code("ko", "korean")
    def test_nl(self): self._assert_code("nl", "dutch")
    def test_pl(self): self._assert_code("pl", "polish")
    def test_bn(self): self._assert_code("bn", "bengali")
    def test_cs(self): self._assert_code("cs", "czech")


# ---------------------------------------------------------------------------
# ISO 639-2 (3-letter) code tests
# ---------------------------------------------------------------------------

class TestThreeLetterCodes(unittest.TestCase):

    def _assert_code(self, code, expected):
        self.assertIn(code, LANGUAGE_MAP, f"ISO 639-2 code {code!r} missing from map")
        self.assertEqual(LANGUAGE_MAP[code], expected,
                         f"LANGUAGE_MAP[{code!r}] should be {expected!r}")

    def test_eng(self): self._assert_code("eng", "english")
    def test_spa(self): self._assert_code("spa", "spanish")
    def test_fre(self): self._assert_code("fre", "french")
    def test_fra(self): self._assert_code("fra", "french")
    def test_ger(self): self._assert_code("ger", "german")
    def test_deu(self): self._assert_code("deu", "german")
    def test_chi(self): self._assert_code("chi", "chinese")
    def test_zho(self): self._assert_code("zho", "chinese")
    def test_por(self): self._assert_code("por", "portuguese")
    def test_rus(self): self._assert_code("rus", "russian")
    def test_jpn(self): self._assert_code("jpn", "japanese")
    def test_ara(self): self._assert_code("ara", "arabic")
    def test_hin(self): self._assert_code("hin", "hindi")
    def test_ita(self): self._assert_code("ita", "italian")
    def test_kor(self): self._assert_code("kor", "korean")
    def test_dut(self): self._assert_code("dut", "dutch")
    def test_nld(self): self._assert_code("nld", "dutch")
    def test_pol(self): self._assert_code("pol", "polish")
    def test_ben(self): self._assert_code("ben", "bengali")
    def test_cze(self): self._assert_code("cze", "czech")
    def test_ces(self): self._assert_code("ces", "czech")


# ---------------------------------------------------------------------------
# Aliases consistency — all codes for a language must agree
# ---------------------------------------------------------------------------

class TestAliasConsistency(unittest.TestCase):

    def _assert_all_agree(self, codes, expected):
        for code in codes:
            self.assertEqual(
                LANGUAGE_MAP.get(code), expected,
                f"Code {code!r}: expected {expected!r}, got {LANGUAGE_MAP.get(code)!r}"
            )

    def test_french_aliases_agree(self):
        self._assert_all_agree(["fr", "fre", "fra"], "french")

    def test_german_aliases_agree(self):
        self._assert_all_agree(["de", "ger", "deu"], "german")

    def test_dutch_aliases_agree(self):
        self._assert_all_agree(["nl", "dut", "nld"], "dutch")

    def test_chinese_aliases_agree(self):
        self._assert_all_agree(["zh", "chi", "zho"], "chinese")

    def test_czech_aliases_agree(self):
        self._assert_all_agree(["cs", "cze", "ces"], "czech")


# ---------------------------------------------------------------------------
# Unknown / edge-case codes
# ---------------------------------------------------------------------------

class TestUnknownCodes(unittest.TestCase):

    def test_unknown_code_returns_none(self):
        self.assertIsNone(LANGUAGE_MAP.get("xx"))

    def test_uppercase_code_not_found(self):
        """Keys are lowercase; uppercase variants must NOT silently match."""
        self.assertIsNone(LANGUAGE_MAP.get("EN"))
        self.assertIsNone(LANGUAGE_MAP.get("ENG"))

    def test_empty_string_returns_none(self):
        self.assertIsNone(LANGUAGE_MAP.get(""))

    def test_numeric_string_returns_none(self):
        self.assertIsNone(LANGUAGE_MAP.get("123"))

    def test_partial_code_not_matched(self):
        """'e' should not accidentally match 'en'."""
        self.assertIsNone(LANGUAGE_MAP.get("e"))

    def test_get_with_default_returns_default_for_unknown(self):
        sentinel = object()
        self.assertIs(LANGUAGE_MAP.get("zz", sentinel), sentinel)


# ---------------------------------------------------------------------------
# Integration: classifier.detect_language() uses LANGUAGE_MAP
# ---------------------------------------------------------------------------

class TestClassifierUsesLanguageMap(unittest.TestCase):

    def _detect(self, langdetect_return):
        """Call detect_language with langdetect mocked to return a given code."""
        with patch("organizer.classifier.LANGDETECT_OK", True), \
             patch("organizer.classifier.detect", return_value=langdetect_return, create=True):
            from organizer import classifier
            with patch.object(classifier, "_langdetect", return_value=langdetect_return,
                               create=True):
                # Patch the langdetect import inside the module
                import importlib
                with patch.dict("sys.modules", {"langdetect": MagicMock(
                    detect=MagicMock(return_value=langdetect_return)
                )}):
                    from organizer.classifier import detect_language
                    return detect_language("some sample text")

    def test_known_code_maps_to_language_name(self):
        """detect_language should return the mapped name for a known 2-letter code."""
        from organizer.classifier import detect_language
        with patch("organizer.classifier.LANGDETECT_OK", True), \
             patch("organizer.classifier._langdetect", return_value="fr", create=True):
            result = detect_language("Du pain, du vin, du Boursin")
        self.assertEqual(result, "french")

    def test_czech_code_maps_correctly(self):
        from organizer.classifier import detect_language
        with patch("organizer.classifier.LANGDETECT_OK", True), \
             patch("organizer.classifier._langdetect", return_value="cs", create=True):
            result = detect_language("Byl jednou jeden král")
        self.assertEqual(result, "czech")

    def test_unknown_code_returns_unknown(self):
        from organizer.classifier import detect_language
        with patch("organizer.classifier.LANGDETECT_OK", True), \
             patch("organizer.classifier._langdetect", return_value="xx", create=True):
            result = detect_language("gibberish text sample")
        self.assertEqual(result, "unknown")

    def test_langdetect_unavailable_returns_unknown(self):
        from organizer.classifier import detect_language
        with patch("organizer.classifier.LANGDETECT_OK", False):
            result = detect_language("any text")
        self.assertEqual(result, "unknown")


# ---------------------------------------------------------------------------
# Integration: enrichment helpers use LANGUAGE_MAP with 3-letter codes
# ---------------------------------------------------------------------------

class TestEnrichmentUsesLanguageMap(unittest.TestCase):
    """
    Verify that the enrichment functions correctly pass ISO codes through
    LANGUAGE_MAP — in particular 3-letter codes from Open Library.
    """

    def _make_ol_response(self, lang_code):
        """Build a minimal Open Library API response with the given language code."""
        return {
            "docs": [{
                "title": "Test Book",
                "author_name": ["Test Author"],
                "language": [lang_code],
                "subject": [],
            }]
        }

    def _make_gb_response(self, lang_code):
        """Build a minimal Google Books API response with the given language code."""
        return {
            "totalItems": 1,
            "items": [{"volumeInfo": {
                "title": "Test Book",
                "authors": ["Test Author"],
                "language": lang_code,
                "categories": [],
            }}]
        }

    def test_open_library_three_letter_eng(self):
        from organizer.enrichment import enrich_open_library
        with patch("organizer.enrichment._http_get",
                   return_value=self._make_ol_response("eng")), \
             patch("organizer.enrichment.cache_get", return_value=None), \
             patch("organizer.enrichment.cache_set"):
            result = enrich_open_library("Test Book", "Test Author")
        self.assertEqual(result["language"], "english")

    def test_open_library_three_letter_cze(self):
        from organizer.enrichment import enrich_open_library
        with patch("organizer.enrichment._http_get",
                   return_value=self._make_ol_response("cze")), \
             patch("organizer.enrichment.cache_get", return_value=None), \
             patch("organizer.enrichment.cache_set"):
            result = enrich_open_library("Testovací kniha", "Autor")
        self.assertEqual(result["language"], "czech")

    def test_open_library_three_letter_ces(self):
        from organizer.enrichment import enrich_open_library
        with patch("organizer.enrichment._http_get",
                   return_value=self._make_ol_response("ces")), \
             patch("organizer.enrichment.cache_get", return_value=None), \
             patch("organizer.enrichment.cache_set"):
            result = enrich_open_library("Testovací kniha", "Autor")
        self.assertEqual(result["language"], "czech")

    def test_open_library_three_letter_fra(self):
        from organizer.enrichment import enrich_open_library
        with patch("organizer.enrichment._http_get",
                   return_value=self._make_ol_response("fra")), \
             patch("organizer.enrichment.cache_get", return_value=None), \
             patch("organizer.enrichment.cache_set"):
            result = enrich_open_library("Livre test", "Auteur")
        self.assertEqual(result["language"], "french")

    def test_open_library_unknown_code_returns_none(self):
        from organizer.enrichment import enrich_open_library
        with patch("organizer.enrichment._http_get",
                   return_value=self._make_ol_response("xxx")), \
             patch("organizer.enrichment.cache_get", return_value=None), \
             patch("organizer.enrichment.cache_set"):
            result = enrich_open_library("Test Book", "Test Author")
        self.assertIsNone(result["language"])

    def test_google_books_two_letter_cs(self):
        from organizer.enrichment import enrich_google_books
        with patch("organizer.enrichment._http_get",
                   return_value=self._make_gb_response("cs")), \
             patch("organizer.enrichment.cache_get", return_value=None), \
             patch("organizer.enrichment.cache_set"):
            result = enrich_google_books("Test Book", "Test Author")
        self.assertEqual(result["language"], "czech")

    def test_google_books_two_letter_fr(self):
        from organizer.enrichment import enrich_google_books
        with patch("organizer.enrichment._http_get",
                   return_value=self._make_gb_response("fr")), \
             patch("organizer.enrichment.cache_get", return_value=None), \
             patch("organizer.enrichment.cache_set"):
            result = enrich_google_books("Livre test", "Auteur")
        self.assertEqual(result["language"], "french")

    def test_google_books_unknown_code_returns_none(self):
        from organizer.enrichment import enrich_google_books
        with patch("organizer.enrichment._http_get",
                   return_value=self._make_gb_response("xx")), \
             patch("organizer.enrichment.cache_get", return_value=None), \
             patch("organizer.enrichment.cache_set"):
            result = enrich_google_books("Test Book", "Test Author")
        self.assertIsNone(result["language"])


if __name__ == "__main__":
    unittest.main()
