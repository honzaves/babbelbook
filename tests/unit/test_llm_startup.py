"""
tests/unit/test_llm_startup.py

Unit tests for the startup LLM health check.

Covers:
  - mlx: ensure_loaded success → LLM_OK True; MlxError → False, LLM_OK False
  - ollama: delegates to check_ollama unchanged
  - organize_books.main(): exits 1 when backend is mlx and the check fails,
    keeps the warn-and-continue path for ollama
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import config
from organizer.enrichment import check_llm_backend
from organizer.mlx_client import MlxError


class TestCheckLlmBackend(unittest.TestCase):
    def test_mlx_success_sets_llm_ok(self):
        with patch("config.LLM_BACKEND", "mlx"), \
             patch("config.LLM_OK", False), \
             patch("organizer.mlx_client.ensure_loaded") as loaded:
            self.assertTrue(check_llm_backend())
            loaded.assert_called_once()
            self.assertTrue(config.LLM_OK)

    def test_mlx_failure_returns_false_and_clears_llm_ok(self):
        with patch("config.LLM_BACKEND", "mlx"), \
             patch("config.LLM_OK", True), \
             patch("organizer.mlx_client.ensure_loaded",
                   side_effect=MlxError("no metal device")):
            self.assertFalse(check_llm_backend())
            self.assertFalse(config.LLM_OK)

    def test_ollama_backend_delegates_to_check_ollama(self):
        with patch("config.LLM_BACKEND", "ollama"), \
             patch("organizer.enrichment.check_ollama",
                   return_value=True) as co:
            self.assertTrue(check_llm_backend())
            co.assert_called_once()


class TestOrganizeBooksStartup(unittest.TestCase):
    def test_mlx_check_failure_exits_1_before_scanning(self):
        import organize_books
        with patch("organize_books.LLM_BACKEND", "mlx"), \
             patch("organize_books.check_llm_backend", return_value=False), \
             patch("organize_books.scan_and_organize") as scan, \
             patch("sys.argv", ["organize_books.py", "--dry-run"]):
            with self.assertRaises(SystemExit) as ctx:
                organize_books.main()
            self.assertEqual(ctx.exception.code, 1)
            scan.assert_not_called()

    def test_ollama_check_failure_continues_with_warning(self):
        import organize_books
        with patch("organize_books.LLM_BACKEND", "ollama"), \
             patch("organize_books.check_llm_backend", return_value=False), \
             patch("organize_books.scan_and_organize") as scan, \
             patch("sys.argv", ["organize_books.py", "--dry-run"]):
            organize_books.main()
            scan.assert_called_once()


if __name__ == "__main__":
    unittest.main()
