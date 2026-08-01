"""
tests/unit/test_enrichment_dispatch.py

Unit tests for enrichment.classify_with_llm backend dispatch.

Covers:
  - backend selection honors config.LLM_BACKEND
  - per-backend cache keys (mlx: / ollama:) are fully isolated
  - Ollama HTTP path: same URL, payload shape, timeout as before
  - mlx failures return None and cache nothing
  - shared response handling: fence stripping, JSON extraction,
    category validation against MAIN_CATEGORIES
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import config
from organizer.mlx_client import MlxError

VALID = {"category": "reading", "genre": "thriller",
         "language": "english", "author": "Ann Author", "confidence": 90}


def _http_response(content: str):
    """Context-manager mock mimicking urllib.request.urlopen."""
    resp = MagicMock()
    resp.read.return_value = json.dumps(
        {"choices": [{"message": {"content": content}}]}).encode()
    cm = MagicMock()
    cm.__enter__.return_value = resp
    cm.__exit__.return_value = False
    return cm


class DispatchTestCase(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.mkdtemp()
        self._patches = [
            patch("organizer.cache.ORGANIZED_DIR", Path(self._td)),
            patch("organizer.cache.CACHE_DB", Path(self._td) / ".cache.db"),
            patch("config.LLM_OK", True),
        ]
        for p in self._patches:
            p.start()
        # import after cache paths are patched
        from organizer.enrichment import classify_with_llm
        from organizer.cache import cache_get, cache_set
        self.classify = classify_with_llm
        self.cache_get = cache_get
        self.cache_set = cache_set

    def tearDown(self):
        for p in self._patches:
            p.stop()
        shutil.rmtree(self._td, ignore_errors=True)

    def _call(self):
        return self.classify("Title", "Author", "sample text",
                             "other", "unknown")


class TestMlxDispatch(DispatchTestCase):
    def test_mlx_backend_calls_mlx_generate_and_caches(self):
        with patch("config.LLM_BACKEND", "mlx"), \
             patch("organizer.mlx_client.generate",
                   return_value=json.dumps(VALID)) as gen:
            result = self._call()
        self.assertEqual(result, VALID)
        gen.assert_called_once()
        args = gen.call_args.args
        self.assertIn("book classification assistant", args[0])  # system
        self.assertIn("Title", args[1])                          # user prompt
        self.assertEqual(args[2], config.MLX_MAX_TOKENS)
        self.assertEqual(self.cache_get("mlx:Title:Author"), VALID)

    def test_mlx_error_returns_none_and_caches_nothing(self):
        with patch("config.LLM_BACKEND", "mlx"), \
             patch("organizer.mlx_client.generate",
                   side_effect=MlxError("boom")):
            result = self._call()
        self.assertIsNone(result)
        self.assertIsNone(self.cache_get("mlx:Title:Author"))

    def test_ollama_cache_entry_ignored_when_backend_is_mlx(self):
        stale = dict(VALID, category="cookbooks")
        self.cache_set("ollama:Title:Author", stale)
        with patch("config.LLM_BACKEND", "mlx"), \
             patch("organizer.mlx_client.generate",
                   return_value=json.dumps(VALID)) as gen:
            result = self._call()
        gen.assert_called_once()
        self.assertEqual(result["category"], "reading")

    def test_mlx_cache_hit_skips_generation(self):
        self.cache_set("mlx:Title:Author", VALID)
        with patch("config.LLM_BACKEND", "mlx"), \
             patch("organizer.mlx_client.generate") as gen:
            result = self._call()
        gen.assert_not_called()
        self.assertEqual(result, VALID)

    def test_llm_not_ok_returns_none_without_calling_backend(self):
        with patch("config.LLM_BACKEND", "mlx"), \
             patch("config.LLM_OK", False), \
             patch("organizer.mlx_client.generate") as gen:
            self.assertIsNone(self._call())
        gen.assert_not_called()

    def test_fenced_json_is_extracted(self):
        fenced = "```json\n" + json.dumps(VALID) + "\n```"
        with patch("config.LLM_BACKEND", "mlx"), \
             patch("organizer.mlx_client.generate", return_value=fenced):
            result = self._call()
        self.assertEqual(result, VALID)

    def test_invalid_category_coerced_to_other(self):
        bad = dict(VALID, category="astrology")
        with patch("config.LLM_BACKEND", "mlx"), \
             patch("organizer.mlx_client.generate",
                   return_value=json.dumps(bad)):
            result = self._call()
        self.assertEqual(result["category"], "other")

    def test_unparseable_response_returns_none(self):
        with patch("config.LLM_BACKEND", "mlx"), \
             patch("organizer.mlx_client.generate",
                   return_value="I am not JSON at all"):
            self.assertIsNone(self._call())


class TestOllamaDispatch(DispatchTestCase):
    def test_ollama_backend_posts_same_request_as_before(self):
        with patch("config.LLM_BACKEND", "ollama"), \
             patch("urllib.request.urlopen",
                   return_value=_http_response(json.dumps(VALID))) as opened:
            result = self._call()
        self.assertEqual(result, VALID)
        req = opened.call_args.args[0]
        self.assertEqual(req.full_url,
                         "http://localhost:11434/v1/chat/completions")
        self.assertEqual(opened.call_args.kwargs["timeout"], 60)
        payload = json.loads(req.data.decode())
        self.assertEqual(payload["model"], config.OLLAMA_MODEL)
        self.assertEqual(payload["stream"], False)
        self.assertEqual(payload["options"], {"temperature": 0.1})
        self.assertEqual(payload["messages"][0]["role"], "system")
        self.assertIn("Title", payload["messages"][1]["content"])
        self.assertEqual(self.cache_get("ollama:Title:Author"), VALID)

    def test_ollama_http_error_returns_none(self):
        with patch("config.LLM_BACKEND", "ollama"), \
             patch("urllib.request.urlopen",
                   side_effect=OSError("connection refused")):
            self.assertIsNone(self._call())

    def test_mlx_cache_entry_ignored_when_backend_is_ollama(self):
        self.cache_set("mlx:Title:Author", dict(VALID, category="history"))
        with patch("config.LLM_BACKEND", "ollama"), \
             patch("urllib.request.urlopen",
                   return_value=_http_response(json.dumps(VALID))) as opened:
            result = self._call()
        opened.assert_called_once()
        self.assertEqual(result["category"], "reading")


if __name__ == "__main__":
    unittest.main()
