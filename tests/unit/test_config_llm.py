"""
tests/unit/test_config_llm.py

Unit tests for the LLM backend settings in config.py:
  - default backend, model id, token/temperature constants
  - renamed LLM_THRESHOLD / LLM_OK
  - BABBELBOOK_LLM_BACKEND env-var override (checked in a subprocess,
    because config reads the env var at import time)
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import config


def _backend_in_subprocess(env: dict) -> str:
    out = subprocess.run(
        [sys.executable, "-c", "import config; print(config.LLM_BACKEND)"],
        env=env, capture_output=True, text=True, cwd=ROOT,
    )
    return out.stdout.strip()


class TestLlmConfig(unittest.TestCase):
    def test_constants(self):
        self.assertEqual(config.MLX_MODEL,
                         "mlx-community/gemma-4-26B-A4B-it-qat-mxfp8")
        self.assertEqual(config.MLX_MAX_TOKENS, 512)
        self.assertEqual(config.LLM_TEMPERATURE, 0.1)
        self.assertEqual(config.LLM_THRESHOLD, 75)
        self.assertTrue(config.LLM_OK)
        self.assertIn(config.LLM_BACKEND, ("mlx", "ollama"))

    def test_default_backend_is_mlx(self):
        env = {k: v for k, v in os.environ.items()
               if k != "BABBELBOOK_LLM_BACKEND"}
        self.assertEqual(_backend_in_subprocess(env), "mlx")

    def test_env_var_overrides_backend(self):
        env = {**os.environ, "BABBELBOOK_LLM_BACKEND": "ollama"}
        self.assertEqual(_backend_in_subprocess(env), "ollama")


if __name__ == "__main__":
    unittest.main()
