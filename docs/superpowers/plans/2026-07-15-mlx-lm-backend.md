# mlx-lm Default LLM Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make in-process mlx-lm the default LLM backend for the organizer's low-confidence classification step, with Ollama remaining selectable via config/env var.

**Architecture:** A new `organizer/mlx_client.py` isolates all MLX specifics (dedicated single thread, mlx-lm→mlx-vlm loader fallback, chat-template fallbacks, reasoning-channel cleanup, one typed `MlxError`). `organizer/enrichment.py` keeps the backend-agnostic parts (system prompt, per-backend cache keys, JSON extraction/validation) in a new `classify_with_llm()` dispatcher. Startup hard-fails (`exit(1)`) if the mlx backend can't load; Ollama keeps its soft warn-and-skip behavior.

**Tech Stack:** Python 3.11+ (system python3 is 3.13), mlx-lm 0.31.3 / mlx-vlm 0.6.4 (already installed), stdlib `unittest`, SQLite cache.

**Spec:** `docs/superpowers/specs/2026-07-15-mlx-lm-backend-design.md`

## Global Constraints

- Model repo id (verified present in local HF cache): `mlx-community/gemma-4-26B-A4B-it-qat-mxfp8`
- Dependency floors: `mlx-lm>=0.31`, `mlx-vlm>=0.6.1`
- Backend selection: `LLM_BACKEND` in `config.py`, default `"mlx"`, overridable via env var `BABBELBOOK_LLM_BACKEND`
- Renames: `OLLAMA_THRESHOLD` → `LLM_THRESHOLD`, `OLLAMA_OK` → `LLM_OK` (values unchanged: 75 and True)
- The Ollama HTTP request path must behave exactly as before (same URL, payload, timeout, parsing)
- Cache keys are per-backend: `mlx:{title}:{author}` vs `ollama:{title}:{author}`; existing `ollama:` entries must never be read when backend is `mlx`
- All MLX work (load AND generate) runs on ONE dedicated thread — the organizer has a 10-worker `ThreadPoolExecutor` and MLX binds its GPU stream to the loading thread
- `config.py` stays the single source of truth for all constants; no other file defines them
- No changes to `browser/` or `babbelbook_flet.py`
- Tests: stdlib `unittest`, files start with `sys.path.insert(0, str(Path(__file__).resolve().parents[2]))`, run via `python3 run_tests.py unit`
- Every unit test must pass without Apple silicon or real model loads (mock `mlx_lm`/`mlx_vlm` via `sys.modules`)
- Commit after each task; commit messages end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

---

### Task 1: Config — LLM backend settings and renames

**Files:**
- Modify: `config.py:40-61`
- Modify: `organizer/enrichment.py:17-20,38-57,164`
- Modify: `organizer/classifier.py:10-16,286-289`
- Modify: `organize_books.py:13-18,39`
- Test: `tests/unit/test_config_llm.py` (create)

**Interfaces:**
- Consumes: nothing (first task)
- Produces: `config.LLM_BACKEND: str` (`"mlx"`|`"ollama"`), `config.MLX_MODEL: str`, `config.MLX_MAX_TOKENS: int`, `config.LLM_TEMPERATURE: float`, `config.LLM_THRESHOLD: int`, `config.LLM_OK: bool`. Later tasks import these exact names.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_config_llm.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.unit.test_config_llm -v`
Expected: FAIL/ERROR with `AttributeError: module 'config' has no attribute 'MLX_MODEL'` (and similar).

- [ ] **Step 3: Implement config changes**

In `config.py`, add `import os` at the top (below `from pathlib import Path`):

```python
import os
from pathlib import Path
```

Replace lines 40-41:

```python
# Ollama is accessed via plain HTTP (stdlib only)
OLLAMA_OK = True  # verified at startup via health check
```

with:

```python
# LLM backend availability — verified at startup via check_llm_backend()
LLM_OK = True
```

Replace line 54:

```python
OLLAMA_THRESHOLD    = 75   # below this → send to Ollama for reclassification
```

with:

```python
LLM_THRESHOLD       = 75   # below this → send to the LLM for reclassification
```

Replace lines 58-61 (`# -- Ollama ---...` block) with:

```python
# -- LLM backend ---------------------------------------------------------------
# "mlx"    → in-process mlx-lm on Apple silicon (default)
# "ollama" → local Ollama HTTP server
LLM_BACKEND = os.environ.get("BABBELBOOK_LLM_BACKEND", "mlx")

# mlx settings
MLX_MODEL       = "mlx-community/gemma-4-26B-A4B-it-qat-mxfp8"
MLX_MAX_TOKENS  = 512    # classification JSON is tiny
LLM_TEMPERATURE = 0.1    # shared by both backends

# ollama settings
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL    = "gpt-oss:20b"
DEFAULT_WORKERS = 10   # concurrent workers; good default for Apple Silicon
```

- [ ] **Step 4: Rename references in organizer/enrichment.py**

Replace lines 17-20 (the config import — `OLLAMA_OK` is dropped; the module always uses `config.OLLAMA_OK` at runtime, never the name-import):

```python
from config import (
    ISBNLIB_OK, LANGUAGE_MAP, MAIN_CATEGORIES,
    OLLAMA_BASE_URL, OLLAMA_MODEL,
)
```

In `check_ollama()` (lines 38-57), replace all three occurrences of `config.OLLAMA_OK = False` with `config.LLM_OK = False`.

In `classify_with_ollama()` line 164, replace:

```python
    if not config.OLLAMA_OK:
```

with:

```python
    if not config.LLM_OK:
```

- [ ] **Step 5: Rename references in organizer/classifier.py**

Replace line 14 inside the config import:

```python
    OLLAMA_THRESHOLD, OLLAMA_MODEL, UNCERTAIN_THRESHOLD,
```

with:

```python
    LLM_THRESHOLD, OLLAMA_MODEL, UNCERTAIN_THRESHOLD,
```

Replace line 288:

```python
    if meta.confidence < OLLAMA_THRESHOLD and config.OLLAMA_OK and not meta.fallback:
```

with:

```python
    if meta.confidence < LLM_THRESHOLD and config.LLM_OK and not meta.fallback:
```

- [ ] **Step 6: Rename references in organize_books.py**

Replace line 16 inside the config import:

```python
    OLLAMA_THRESHOLD, UNCERTAIN_THRESHOLD, OLLAMA_BASE_URL, OLLAMA_MODEL,
```

with:

```python
    LLM_THRESHOLD, UNCERTAIN_THRESHOLD, OLLAMA_BASE_URL, OLLAMA_MODEL,
```

Replace line 39:

```python
    print(f"  Ollama threshold      : {OLLAMA_THRESHOLD}/100  (model: {OLLAMA_MODEL})")
```

with:

```python
    print(f"  LLM threshold         : {LLM_THRESHOLD}/100  (model: {OLLAMA_MODEL})")
```

(The banner is fully reworked in Task 5; this keeps Task 1 a pure rename.)

- [ ] **Step 7: Run the new test and the full unit suite**

Run: `python3 -m unittest tests.unit.test_config_llm -v`
Expected: PASS (3 tests).

Run: `python3 run_tests.py unit`
Expected: all tests pass (renames are mechanical; nothing else referenced the old names — verify with `grep -rn "OLLAMA_THRESHOLD\|OLLAMA_OK" --include="*.py" .` which must return nothing).

- [ ] **Step 8: Commit**

```bash
git add config.py organizer/enrichment.py organizer/classifier.py organize_books.py tests/unit/test_config_llm.py
git commit -m "feat: add LLM backend config, rename OLLAMA_THRESHOLD/OLLAMA_OK to LLM_THRESHOLD/LLM_OK

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: mlx_client — errors, dedicated thread, template fallbacks, loader

**Files:**
- Create: `organizer/mlx_client.py`
- Modify: `requirements.txt:17` (append after langdetect), `pyproject.toml:31-33` (the `llm` extra)
- Test: `tests/unit/test_mlx_client.py` (create)

**Interfaces:**
- Consumes: `config.MLX_MODEL`, `config.LLM_TEMPERATURE` (Task 1)
- Produces:
  - `MlxError(Exception)` with attribute `raw_response: str | None`
  - `ensure_loaded() -> None` — blocks until model is loaded on the MLX thread; raises `MlxError` on any failure
  - `_apply_template(tok, system: str | None, user: str) -> str` (module-private, used by Task 3's generate path; tested directly)
  - Module globals `_MLX_THREAD` (1-worker `ThreadPoolExecutor`) and `_generator` (`None` until loaded, then `gen(system, user, max_tokens) -> str`) — tests reset `_generator` in `setUp`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_mlx_client.py`:

```python
"""
tests/unit/test_mlx_client.py

Unit tests for organizer/mlx_client.py with mlx_lm / mlx_vlm fully mocked
via sys.modules — no Apple silicon, no model downloads, no real MLX import.

Covers:
  - thread confinement  load (and, in Task 3, generate) run on one
                        dedicated thread that is NOT the caller's
  - loader fallback     unsupported-arch ValueError → mlx_vlm.load()
  - error normalization every failure surfaces as MlxError
  - template fallbacks  enable_thinking TypeError → retry + warning;
                        system-role rejection → fold into user turn
"""

import sys
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from organizer import mlx_client
from organizer.mlx_client import MlxError


def _fake_lm(load_result=None, load_exc=None, record=None,
             generate=None):
    """Build fake mlx_lm + mlx_lm.sample_utils modules for sys.modules."""
    lm = types.ModuleType("mlx_lm")
    su = types.ModuleType("mlx_lm.sample_utils")

    def load(repo):
        if record is not None:
            record["load_thread"] = threading.get_ident()
            record["load_repo"] = repo
        if load_exc is not None:
            raise load_exc
        return load_result or (MagicMock(), MagicMock())

    lm.load = load
    lm.generate = generate or MagicMock(return_value="{}")
    su.make_sampler = MagicMock(return_value="fake-sampler")
    return {"mlx_lm": lm, "mlx_lm.sample_utils": su}


def _fake_vlm(record=None):
    vlm = types.ModuleType("mlx_vlm")

    def load(repo):
        if record is not None:
            record["vlm_load_repo"] = repo
        proc = MagicMock()
        proc.tokenizer = MagicMock()
        return MagicMock(), proc

    vlm.load = load
    vlm.generate = MagicMock(return_value="ok")
    return {"mlx_vlm": vlm}


class MlxClientTestCase(unittest.TestCase):
    def setUp(self):
        mlx_client._generator = None


class TestEnsureLoaded(MlxClientTestCase):
    def test_load_runs_on_dedicated_non_caller_thread(self):
        record = {}
        with patch.dict(sys.modules, _fake_lm(record=record)):
            mlx_client.ensure_loaded()
        self.assertIn("load_thread", record)
        self.assertNotEqual(record["load_thread"], threading.get_ident())

    def test_loads_configured_model(self):
        record = {}
        with patch.dict(sys.modules, _fake_lm(record=record)):
            mlx_client.ensure_loaded()
        self.assertEqual(record["load_repo"], mlx_client.MLX_MODEL)

    def test_second_call_does_not_reload(self):
        record = {}
        fakes = _fake_lm(record=record)
        calls = []
        original = fakes["mlx_lm"].load
        fakes["mlx_lm"].load = lambda repo: (calls.append(repo), original(repo))[1]
        with patch.dict(sys.modules, fakes):
            mlx_client.ensure_loaded()
            mlx_client.ensure_loaded()
        self.assertEqual(len(calls), 1)

    def test_load_failure_raises_mlx_error(self):
        fakes = _fake_lm(load_exc=RuntimeError("metal exploded"))
        with patch.dict(sys.modules, fakes):
            with self.assertRaises(MlxError) as ctx:
                mlx_client.ensure_loaded()
        self.assertIn("metal exploded", str(ctx.exception))

    def test_unsupported_arch_falls_back_to_vlm(self):
        record = {}
        fakes = _fake_lm(
            load_exc=ValueError("Model type gemma4_unified not supported"))
        fakes.update(_fake_vlm(record=record))
        with patch.dict(sys.modules, fakes):
            mlx_client.ensure_loaded()
        self.assertEqual(record["vlm_load_repo"], mlx_client.MLX_MODEL)

    def test_vlm_failure_also_raises_mlx_error(self):
        fakes = _fake_lm(
            load_exc=ValueError("Model type gemma4_unified not supported"))
        vlm = types.ModuleType("mlx_vlm")
        def bad_load(repo):
            raise RuntimeError("vlm also broken")
        vlm.load = bad_load
        fakes["mlx_vlm"] = vlm
        with patch.dict(sys.modules, fakes):
            with self.assertRaises(MlxError) as ctx:
                mlx_client.ensure_loaded()
        self.assertIn("vlm also broken", str(ctx.exception))


class TestApplyTemplate(unittest.TestCase):
    def test_passes_enable_thinking_false(self):
        tok = MagicMock()
        tok.apply_chat_template.return_value = "PROMPT"
        out = mlx_client._apply_template(tok, "sys", "user")
        self.assertEqual(out, "PROMPT")
        kwargs = tok.apply_chat_template.call_args.kwargs
        self.assertIs(kwargs["enable_thinking"], False)
        self.assertIs(kwargs["add_generation_prompt"], True)
        self.assertIs(kwargs["tokenize"], False)

    def test_system_message_included_when_supported(self):
        tok = MagicMock()
        tok.apply_chat_template.return_value = "PROMPT"
        mlx_client._apply_template(tok, "SYS", "USER")
        messages = tok.apply_chat_template.call_args.args[0]
        self.assertEqual(messages[0], {"role": "system", "content": "SYS"})
        self.assertEqual(messages[1], {"role": "user", "content": "USER"})

    def test_typeerror_retries_without_kwarg_and_warns(self):
        tok = MagicMock()
        def apply(messages, **kw):
            if "enable_thinking" in kw:
                raise TypeError("unexpected keyword 'enable_thinking'")
            return "PROMPT"
        tok.apply_chat_template.side_effect = apply
        with self.assertLogs("babbelbook.mlx", level="WARNING"):
            out = mlx_client._apply_template(tok, "sys", "user")
        self.assertEqual(out, "PROMPT")

    def test_system_role_rejection_folds_into_user_turn(self):
        tok = MagicMock()
        def apply(messages, **kw):
            if any(m["role"] == "system" for m in messages):
                raise ValueError("System role not supported")
            return messages[-1]["content"]
        tok.apply_chat_template.side_effect = apply
        out = mlx_client._apply_template(tok, "SYS", "USER")
        self.assertEqual(out, "SYS\n\nUSER")

    def test_no_system_prompt_failure_propagates(self):
        tok = MagicMock()
        tok.apply_chat_template.side_effect = ValueError("template is broken")
        with self.assertRaises(ValueError):
            mlx_client._apply_template(tok, None, "USER")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.unit.test_mlx_client -v`
Expected: ERROR at import — `ModuleNotFoundError: No module named 'organizer.mlx_client'`.

- [ ] **Step 3: Write the implementation**

Create `organizer/mlx_client.py`:

```python
"""
mlx_client.py — in-process LLM text generation via mlx-lm (Apple silicon).

All MLX work — model load AND generation — is confined to one dedicated
thread: MLX binds its GPU stream to the thread that loads the model, and
generation is not thread-safe. The organizer calls in from a 10-worker
ThreadPoolExecutor, so every call here is submitted to _MLX_THREAD and
naturally serialized (max_workers=1).

Loading is lazy but can be forced eagerly via ensure_loaded() so the
organizer can hard-fail at startup before processing any book. The first
ever load downloads the model from Hugging Face (~13 GB); warm loads take
a few seconds. The model stays resident until the process exits.

Every failure — import, download, load, generate, empty output — is
normalized into MlxError so callers stay backend-agnostic.
"""

import logging
from concurrent.futures import ThreadPoolExecutor

from config import LLM_TEMPERATURE, MLX_MODEL

_LOG = logging.getLogger("babbelbook.mlx")

# Reasoning-channel close marker emitted by gemma-4-family chat templates
# when thinking is not (or cannot be) disabled.
_CHANNEL_CLOSE = "<channel|>"


class MlxError(Exception):
    """Any MLX failure: import, download, load, generate, empty output."""

    def __init__(self, message: str, raw_response: str | None = None):
        super().__init__(message)
        self.raw_response = raw_response


_MLX_THREAD = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mlx")
_generator = None  # gen(system, user, max_tokens) -> str, set by _load()


# -- Chat template ------------------------------------------------------------

def _template_once(tok, messages):
    try:
        return tok.apply_chat_template(
            messages, add_generation_prompt=True, tokenize=False,
            enable_thinking=False,
        )
    except TypeError:
        _LOG.warning(
            "apply_chat_template rejected enable_thinking=False; "
            "responses may include a reasoning channel and be slower"
        )
        return tok.apply_chat_template(
            messages, add_generation_prompt=True, tokenize=False,
        )


def _apply_template(tok, system: str | None, user: str) -> str:
    msgs = ([{"role": "system", "content": system}] if system else []) \
           + [{"role": "user", "content": user}]
    try:
        return _template_once(tok, msgs)
    except Exception:
        if not system:
            raise
        # Some templates reject the system role — fold it into the user turn.
        merged = [{"role": "user", "content": f"{system}\n\n{user}"}]
        return _template_once(tok, merged)


# -- Loading (runs on the MLX thread) -----------------------------------------

def _load_lm():
    from mlx_lm import generate, load
    from mlx_lm.sample_utils import make_sampler
    model, tok = load(MLX_MODEL)
    sampler = make_sampler(temp=LLM_TEMPERATURE)

    def gen(system, user, max_tokens):
        prompt = _apply_template(tok, system, user)
        return generate(model, tok, prompt=prompt, max_tokens=max_tokens,
                        sampler=sampler, verbose=False)

    return gen


def _load_vlm():
    from mlx_vlm import generate, load
    model, proc = load(MLX_MODEL)
    tok = getattr(proc, "tokenizer", proc)

    def gen(system, user, max_tokens):
        prompt = _apply_template(tok, system, user)
        out = generate(model, proc, prompt=prompt, max_tokens=max_tokens,
                       temperature=LLM_TEMPERATURE, verbose=False)
        return out.text if hasattr(out, "text") else out

    return gen


def _load():
    try:
        return _load_lm()
    except Exception as e:
        msg = str(e)
        unsupported = isinstance(e, (ValueError, ModuleNotFoundError)) and (
            "not supported" in msg or "No module named" in msg
        )
        if not unsupported:
            raise MlxError(
                f"mlx-lm failed to load '{MLX_MODEL}': {e}") from e
    try:
        return _load_vlm()
    except Exception as e:
        raise MlxError(f"mlx-vlm failed to load '{MLX_MODEL}': {e}") from e


def _ensure_loaded_on_thread():
    global _generator
    if _generator is None:
        _generator = _load()


def ensure_loaded() -> None:
    """Load the model on the MLX thread (blocks; downloads on first ever run).

    Raises MlxError on any failure.
    """
    _MLX_THREAD.submit(_ensure_loaded_on_thread).result()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.unit.test_mlx_client -v`
Expected: PASS (11 tests).

- [ ] **Step 5: Declare the dependencies**

In `requirements.txt`, append after line 17 (`langdetect>=1.0.9`):

```
# Local LLM via in-process MLX (Apple silicon only; default backend)
#   mlx-lm   →  text-architecture models
#   mlx-vlm  →  "unified"/multimodal architectures (gemma-4 family)
mlx-lm>=0.31
mlx-vlm>=0.6.1
```

In `pyproject.toml`, replace lines 31-33:

```toml
# Local LLM support via Ollama (HTTP only — no extra Python package needed)
# Run:  ollama pull gpt-oss:20b && ollama serve
llm = []
```

with:

```toml
# Local LLM support. Default backend is in-process mlx-lm (Apple silicon).
# Ollama alternative needs no Python package — set BABBELBOOK_LLM_BACKEND=ollama
# and run:  ollama pull gpt-oss:20b && ollama serve
llm = [
    "mlx-lm>=0.31",
    "mlx-vlm>=0.6.1",
]
```

- [ ] **Step 6: Run the full unit suite**

Run: `python3 run_tests.py unit`
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add organizer/mlx_client.py tests/unit/test_mlx_client.py requirements.txt pyproject.toml
git commit -m "feat: add mlx_client with dedicated MLX thread, loader fallback, template fallbacks

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: mlx_client.generate() — public generation with channel cleaner

**Files:**
- Modify: `organizer/mlx_client.py` (append)
- Test: `tests/unit/test_mlx_client.py` (append)

**Interfaces:**
- Consumes: Task 2's `_MLX_THREAD`, `_generator`, `_ensure_loaded_on_thread`, `MlxError`, `_CHANNEL_CLOSE`
- Produces: `generate(system: str | None, user: str, max_tokens: int) -> str` — cleaned response text; raises `MlxError` on any failure or empty output. This is the function `enrichment.classify_with_llm` (Task 4) calls.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_mlx_client.py`:

```python
class TestGenerate(MlxClientTestCase):
    @staticmethod
    def _fakes_with_generate(record, text):
        model, tok = MagicMock(), MagicMock()
        tok.apply_chat_template.return_value = "PROMPT"
        fakes = _fake_lm(load_result=(model, tok), record=record)

        def gen(model, tok, prompt, max_tokens, sampler, verbose):
            record["gen_thread"] = threading.get_ident()
            record["max_tokens"] = max_tokens
            return text

        fakes["mlx_lm"].generate = gen
        return fakes

    def test_generate_runs_on_the_load_thread(self):
        record = {}
        fakes = self._fakes_with_generate(record, '{"category": "reading"}')
        with patch.dict(sys.modules, fakes):
            out = mlx_client.generate("sys", "user", 512)
        self.assertEqual(out, '{"category": "reading"}')
        self.assertEqual(record["gen_thread"], record["load_thread"])
        self.assertNotEqual(record["gen_thread"], threading.get_ident())

    def test_max_tokens_forwarded(self):
        record = {}
        fakes = self._fakes_with_generate(record, "x")
        with patch.dict(sys.modules, fakes):
            mlx_client.generate("sys", "user", 77)
        self.assertEqual(record["max_tokens"], 77)

    def test_reasoning_channel_stripped(self):
        record = {}
        fakes = self._fakes_with_generate(
            record, 'thinking thinking<channel|>{"a": 1}')
        with patch.dict(sys.modules, fakes):
            out = mlx_client.generate("sys", "user", 512)
        self.assertEqual(out, '{"a": 1}')

    def test_empty_output_raises_mlx_error_with_raw(self):
        record = {}
        fakes = self._fakes_with_generate(record, "   \n ")
        with patch.dict(sys.modules, fakes):
            with self.assertRaises(MlxError) as ctx:
                mlx_client.generate("sys", "user", 512)
        self.assertEqual(ctx.exception.raw_response, "   \n ")

    def test_generation_exception_normalized_to_mlx_error(self):
        record = {}
        model, tok = MagicMock(), MagicMock()
        tok.apply_chat_template.return_value = "PROMPT"
        fakes = _fake_lm(load_result=(model, tok), record=record)

        def boom(*args, **kwargs):
            raise RuntimeError("gpu fault")

        fakes["mlx_lm"].generate = boom
        with patch.dict(sys.modules, fakes):
            with self.assertRaises(MlxError) as ctx:
                mlx_client.generate("sys", "user", 512)
        self.assertIn("gpu fault", str(ctx.exception))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.unit.test_mlx_client.TestGenerate -v`
Expected: ERROR — `AttributeError: module 'organizer.mlx_client' has no attribute 'generate'`.

- [ ] **Step 3: Write the implementation**

Append to `organizer/mlx_client.py`:

```python
# -- Generation ----------------------------------------------------------------

def _generate_on_thread(system, user, max_tokens):
    _ensure_loaded_on_thread()
    return _generator(system, user, max_tokens)


def _clean(text: str) -> str:
    # Belt-and-braces: if a reasoning channel leaked through, keep only the
    # text after the LAST channel-close marker.
    if _CHANNEL_CLOSE in text:
        text = text.rsplit(_CHANNEL_CLOSE, 1)[1]
    return text.strip()


def generate(system: str | None, user: str, max_tokens: int) -> str:
    """Generate a completion on the MLX thread and return the cleaned text.

    Raises MlxError on any failure, including an empty response.
    """
    try:
        raw = _MLX_THREAD.submit(
            _generate_on_thread, system, user, max_tokens).result()
    except MlxError:
        raise
    except Exception as e:
        raise MlxError(f"MLX generation failed: {e}") from e
    text = _clean(raw or "")
    if not text:
        raise MlxError("MLX returned an empty response", raw_response=raw)
    return text
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.unit.test_mlx_client -v`
Expected: PASS (16 tests).

- [ ] **Step 5: Commit**

```bash
git add organizer/mlx_client.py tests/unit/test_mlx_client.py
git commit -m "feat: add mlx_client.generate with channel cleaner and error normalization

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Backend dispatch — classify_with_llm, classifier and organizer call sites

**Files:**
- Modify: `organizer/enrichment.py:1-20,131-211` (docstring, imports, the whole Ollama-classification section)
- Modify: `organizer/classifier.py:10-20,155-161,286-307`
- Modify: `organizer/organizer.py:15-18,169,174,230,243-244,273,394,402`
- Modify: `tests/unit/test_classifier.py:331-342`
- Test: `tests/unit/test_enrichment_dispatch.py` (create)

**Interfaces:**
- Consumes: `mlx_client.generate(system, user, max_tokens) -> str`, `mlx_client.MlxError` (Task 3); `config.LLM_BACKEND`, `config.LLM_OK`, `config.MLX_MAX_TOKENS`, `config.LLM_TEMPERATURE`, `config.MLX_MODEL` (Task 1)
- Produces: `enrichment.classify_with_llm(title, author, sample, current_category, current_language) -> dict | None` — same return contract `classify_with_ollama` had (dict with `category`/`genre`/`language`/`author`/`confidence`, or `None`). `classify_with_ollama` is REMOVED (classifier.py was its only consumer). Source tag appended by classifier is now `config.LLM_BACKEND` (`"mlx"` or `"ollama"`).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_enrichment_dispatch.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.unit.test_enrichment_dispatch -v`
Expected: ERROR — `ImportError: cannot import name 'classify_with_llm' from 'organizer.enrichment'`.

- [ ] **Step 3: Rework the classification section in organizer/enrichment.py**

Update the module docstring's Ollama line (line 8) to:

```python
  LLM (mlx-lm or Ollama) → low-confidence books → category, genre, language, author
```

Replace the config import (currently lines 17-20 after Task 1) with:

```python
from config import (
    ISBNLIB_OK, LANGUAGE_MAP, LLM_TEMPERATURE, MAIN_CATEGORIES,
    OLLAMA_BASE_URL, OLLAMA_MODEL,
)
```

Replace the entire section from `# -- Ollama classification ---...` (line 131) to the end of `classify_with_ollama` (line 211) with:

```python
# -- LLM classification --------------------------------------------------------

_LLM_SYSTEM = """You are a book classification assistant.
Given a book title, author, and a short text sample, return ONLY a valid JSON
object with no explanation, no markdown, no extra text whatsoever.

Required keys:
{
  "category": "<one of: cookbooks | reading | home_improvement | sport_workout_yoga_health | other>",
  "genre":    "<specific genre e.g. thriller, fantasy, yoga, gardening, biography>",
  "language": "<one of: english | spanish | german | dutch | unknown>",
  "author":   "<corrected/normalized author name, or Unknown Author>",
  "confidence": <integer 0-100>
}

Rules:
- category must be EXACTLY one of the five listed values.
- Use full context to determine category, not isolated words.
  Example: 'stake' in a vampire novel is NOT woodworking.
  Example: 'Vampireslayer' is horror/fantasy -> reading.
- If uncertain, use 'other' for category.
- confidence reflects certainty about the category assignment.
"""


def _ollama_generate(user_prompt: str) -> str:
    """POST to the local Ollama server; returns the raw response text."""
    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": _LLM_SYSTEM},
            {"role": "user",   "content": user_prompt},
        ],
        "stream": False,
        "options": {"temperature": LLM_TEMPERATURE},
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        response = json.loads(r.read().decode())
    return response["choices"][0]["message"]["content"].strip()


def _extract_json(raw: str) -> dict:
    """Strip code fences, take the outermost {...}, parse. Raises on failure."""
    raw = re.sub(r"^```[a-z]*\n?", "", raw)
    raw = re.sub(r"\n?```$",        "", raw)
    json_match = re.search(r"\{.*\}", raw, re.DOTALL)
    if json_match:
        raw = json_match.group()
    return json.loads(raw)


def classify_with_llm(title: str, author: str, sample: str,
                      current_category: str, current_language: str) -> dict | None:
    """Classify one book via the configured LLM backend (config.LLM_BACKEND).

    Results are cached per backend ("mlx:..." / "ollama:...") so switching
    backends never reuses the other model's answers. Returns the parsed dict,
    or None on any failure (the book keeps its heuristic classification).
    """
    import config
    cache_key = f"{config.LLM_BACKEND}:{title}:{author}"
    cached    = cache_get(cache_key)
    if cached is not None:
        return cached

    if not config.LLM_OK:
        return None

    snippet = sample[:1500].strip() if sample else "(no text available)"
    prompt  = (
        f"Title  : {title}\n"
        f"Author : {author}\n"
        f"Current category guess : {current_category}\n"
        f"Current language guess : {current_language}\n\n"
        f"Text sample:\n{snippet}\n"
    )

    try:
        if config.LLM_BACKEND == "mlx":
            from . import mlx_client
            raw = mlx_client.generate(_LLM_SYSTEM, prompt, config.MLX_MAX_TOKENS)
        else:
            raw = _ollama_generate(prompt)
        data = _extract_json(raw)
    except Exception as e:
        print(f"    [LLM/{config.LLM_BACKEND}] error: {e}")
        return None

    if data.get("category") not in MAIN_CATEGORIES:
        data["category"] = "other"
    cache_set(cache_key, data)
    return data
```

(Note: `classify_with_ollama` no longer exists; `classifier.py` is updated in the next step, and nothing else imported it.)

- [ ] **Step 4: Update organizer/classifier.py**

Replace the config import lines 10-16 with (drop `OLLAMA_MODEL` — the model name is now read via `config` at the call site):

```python
from config import (
    EBOOKLIB_OK, PYMUPDF_OK, MOBI_OK,
    LANGDETECT_OK, LANGUAGE_MAP,
    GENRE_KEYWORDS, GENRE_TO_CATEGORY, SUBJECT_GENRE_MAP,
    LLM_THRESHOLD, UNCERTAIN_THRESHOLD,
    ORGANIZED_DIR,
)
```

Replace the enrichment import (lines 18-20) with:

```python
from .enrichment import (
    enrich_isbn, enrich_google_books, enrich_open_library, classify_with_llm,
)
```

In `_score` (line 157), replace:

```python
        if "ollama"             in meta.sources: score += 30
```

with:

```python
        if "ollama" in meta.sources or "mlx" in meta.sources: score += 30
```

Replace the step-9 block (lines 286-307) with:

```python
    # 9. LLM pass for low-confidence books
    import config
    if meta.confidence < LLM_THRESHOLD and config.LLM_OK and not meta.fallback:
        model_name = config.MLX_MODEL if config.LLM_BACKEND == "mlx" else config.OLLAMA_MODEL
        print(f"    [LLM/{config.LLM_BACKEND}] confidence {meta.confidence}/100 "
              f"-- asking {model_name} ...")
        result = classify_with_llm(
            meta.title, meta.author, sample,
            meta.category, meta.language
        )
        if result:
            old_cat = meta.category
            meta.category = result.get("category", meta.category)
            meta.genre    = result.get("genre",    meta.genre)
            if result.get("language", "unknown") != "unknown":
                meta.language = result["language"]
            if result.get("author", "Unknown Author") != "Unknown Author":
                meta.author = sanitize(result["author"])
            meta.sources.append(config.LLM_BACKEND)
            _add_genre(meta, meta.genre)  # add the LLM's genre to the collection
            if old_cat != meta.category:
                print(f"    [LLM/{config.LLM_BACKEND}] reclassified: {old_cat} -> {meta.category}  "
                      f"(genre: {meta.genre}, confidence: {result.get('confidence', '?')})")
            _score(meta)
```

- [ ] **Step 5: Update organizer/organizer.py**

In the config import (around line 17), replace `OLLAMA_MODEL` with nothing — remove it from the list (the summary reads via `config` below).

Line 169, replace:

```python
    ollama = " [Ollama]" if "ollama" in meta.sources else ""
```

with:

```python
    llm = " [LLM]" if ("ollama" in meta.sources or "mlx" in meta.sources) else ""
```

Line 174, replace `{ollama}` with `{llm}` in the print.

Line 230, replace:

```python
    copied = failed = uncertain_count = ollama_count = 0
```

with:

```python
    copied = failed = uncertain_count = llm_count = 0
```

Lines 243-244, replace:

```python
                if "ollama" in meta.sources:
                    ollama_count += 1
```

with:

```python
                if "ollama" in meta.sources or "mlx" in meta.sources:
                    llm_count += 1
```

Line 273, replace `ollama_count` with `llm_count` in the `_print_summary` call.

Line 394, replace the parameter `ollama_count` with `llm_count` in the `_print_summary` signature.

Line 402, replace:

```python
    print(f"  Classified by Ollama    : {ollama_count}  (model: {OLLAMA_MODEL})")
```

with:

```python
    import config
    model = config.MLX_MODEL if config.LLM_BACKEND == "mlx" else config.OLLAMA_MODEL
    print(f"  Classified by LLM       : {llm_count}  (backend: {config.LLM_BACKEND}, model: {model})")
```

- [ ] **Step 6: Update the scoring test in tests/unit/test_classifier.py**

Replace `test_ollama_source_boosts_score` (lines 331-342) with:

```python
    def test_llm_source_boosts_score(self):
        for tag in ("ollama", "mlx"):
            with self.subTest(backend=tag):
                m_no_llm = BookMeta(
                    author="Author", language="english", category="reading",
                    sources=["library", "keyword_title"],
                )
                m_llm = BookMeta(
                    author="Author", language="english", category="reading",
                    sources=["library", tag],
                )
                _score(m_no_llm)
                _score(m_llm)
                self.assertGreater(m_llm.confidence, m_no_llm.confidence)
```

- [ ] **Step 7: Run the new tests and the full unit suite**

Run: `python3 -m unittest tests.unit.test_enrichment_dispatch -v`
Expected: PASS (11 tests).

Run: `python3 run_tests.py unit && python3 run_tests.py integration`
Expected: all pass. Then confirm nothing references the removed symbol:
`grep -rn "classify_with_ollama" --include="*.py" .` must return nothing.

- [ ] **Step 8: Commit**

```bash
git add organizer/enrichment.py organizer/classifier.py organizer/organizer.py tests/unit/test_enrichment_dispatch.py tests/unit/test_classifier.py
git commit -m "feat: dispatch LLM classification via classify_with_llm (mlx default, ollama selectable)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Startup health check — hard fail for mlx, soft skip for Ollama

**Files:**
- Modify: `organizer/enrichment.py` (add `check_llm_backend` after `check_ollama`)
- Modify: `organize_books.py:13-20,34-43,61-65`
- Test: `tests/unit/test_llm_startup.py` (create)

**Interfaces:**
- Consumes: `mlx_client.ensure_loaded()`, `mlx_client.MlxError` (Task 2); `check_ollama()` (existing); `config.LLM_BACKEND`, `config.LLM_OK` (Task 1)
- Produces: `enrichment.check_llm_backend() -> bool` — verifies the configured backend and sets `config.LLM_OK`. `organize_books.main()` exits with code 1 when the backend is `mlx` and the check fails.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_llm_startup.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.unit.test_llm_startup -v`
Expected: ERROR — `ImportError: cannot import name 'check_llm_backend' from 'organizer.enrichment'`.

- [ ] **Step 3: Add check_llm_backend to organizer/enrichment.py**

Insert directly after `check_ollama()` (after line 57):

```python
def check_llm_backend() -> bool:
    """Verify the configured LLM backend and set config.LLM_OK.

    mlx    → eagerly load the model (blocks; first-ever run downloads it).
    ollama → HTTP reachability + model presence (existing soft check).
    """
    import config
    if config.LLM_BACKEND == "mlx":
        from . import mlx_client
        try:
            mlx_client.ensure_loaded()
            config.LLM_OK = True
            return True
        except mlx_client.MlxError as e:
            print(f"  ERROR: mlx backend unavailable: {e}")
            config.LLM_OK = False
            return False
    return check_ollama()
```

- [ ] **Step 4: Rework the organize_books.py banner and health check**

Replace the imports (lines 13-20) with:

```python
from config import (
    BOOKS_DIR, ORGANIZED_DIR,
    EBOOKLIB_OK, PYMUPDF_OK, MOBI_OK, ISBNLIB_OK, LANGDETECT_OK,
    LLM_THRESHOLD, UNCERTAIN_THRESHOLD,
    LLM_BACKEND, MLX_MODEL, OLLAMA_BASE_URL, OLLAMA_MODEL,
    DEFAULT_WORKERS,
)
from organizer.enrichment import check_llm_backend
from organizer.organizer import scan_and_organize
```

Replace the two banner lines (39-40) with:

```python
    model = MLX_MODEL if LLM_BACKEND == "mlx" else OLLAMA_MODEL
    print(f"  LLM backend           : {LLM_BACKEND}  (model: {model})")
    print(f"  LLM threshold         : {LLM_THRESHOLD}/100")
```

Replace the health-check block (lines 61-65) with:

```python
    print(f"  Checking LLM backend '{LLM_BACKEND}' ...")
    if check_llm_backend():
        print(f"  LLM OK -- backend '{LLM_BACKEND}' is ready.\n")
    elif LLM_BACKEND == "mlx":
        print("  Aborting: the mlx backend is configured but unavailable.")
        print("  Set BABBELBOOK_LLM_BACKEND=ollama to use Ollama instead.")
        sys.exit(1)
    else:
        print(f"  Ollama unavailable at {OLLAMA_BASE_URL} -- "
              "LLM classification will be skipped.\n")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m unittest tests.unit.test_llm_startup -v`
Expected: PASS (5 tests).

Run: `python3 run_tests.py unit`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add organizer/enrichment.py organize_books.py tests/unit/test_llm_startup.py
git commit -m "feat: startup LLM health check -- hard exit for mlx, soft skip for ollama

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Documentation, full-suite verification, real-model smoke test

**Files:**
- Modify: `CLAUDE.md` (pipeline section, thresholds, project layout, new "LLM backends" note)
- Test: full suite + a one-off real-model smoke script (not committed)

**Interfaces:**
- Consumes: everything above
- Produces: updated docs; verified end-to-end behavior on the real model

- [ ] **Step 1: Update CLAUDE.md**

In the **Project Layout** tree, under `organizer/`, add after the `enrichment.py` line:

```
│   ├── mlx_client.py       ← in-process mlx-lm generation (dedicated MLX thread)
```

In **Classification Pipeline (organiser)**, replace step 8:

```
8. Ollama LLM (if confidence < `OLLAMA_THRESHOLD = 75`)
```

with:

```
8. Local LLM (if confidence < `LLM_THRESHOLD = 75`) — in-process mlx-lm by default, Ollama if `LLM_BACKEND = "ollama"`
```

Replace the thresholds list item:

```
- `OLLAMA_THRESHOLD = 75` — below this → send to Ollama
```

with:

```
- `LLM_THRESHOLD = 75` — below this → send to the LLM backend
```

Update the `enrichment.py` layout line from `Google Books, Open Library, isbnlib, Ollama` to `Google Books, Open Library, isbnlib, LLM dispatch (mlx/Ollama)`.

Add a new section after **Classification Pipeline (organiser)**:

```markdown
## LLM Backends

The organiser's low-confidence classification step runs against one of two local
LLM backends, selected by `LLM_BACKEND` in `config.py` (env override:
`BABBELBOOK_LLM_BACKEND`):

- **`mlx` (default)** — in-process via mlx-lm/mlx-vlm on Apple silicon.
  Model: `MLX_MODEL` (an `-it` mlx-community conversion). All MLX work runs on
  one dedicated thread in `organizer/mlx_client.py` — never call mlx from
  another thread. If the model can't load, the organiser **exits 1 at startup**
  (first-ever run downloads the model inside this check).
- **`ollama`** — local Ollama HTTP server (`OLLAMA_BASE_URL`, `OLLAMA_MODEL`).
  If unreachable, the organiser warns and skips LLM classification (soft).

LLM results are cached per backend (`mlx:{title}:{author}` /
`ollama:{title}:{author}`), so switching backends never reuses the other
model's answers. Every backend failure surfaces as `mlx_client.MlxError`
(mlx) or is caught in `classify_with_llm` (both); a per-book failure keeps
the heuristic classification and continues.
```

- [ ] **Step 2: Run the entire test suite**

Run: `python3 run_tests.py`
Expected: all unit + integration tests pass.

- [ ] **Step 3: Real-model smoke test (manual, not committed)**

This is the only step that loads the real model (it is already in the local HF cache). It validates the lm→vlm loader against the pinned mlx-vlm version and the end-to-end JSON discipline:

```bash
python3 - <<'EOF'
import json, time
from organizer import mlx_client
from organizer.enrichment import _LLM_SYSTEM

t0 = time.time()
mlx_client.ensure_loaded()
print(f"loaded in {time.time()-t0:.1f}s")

t0 = time.time()
out = mlx_client.generate(
    _LLM_SYSTEM,
    "Title  : The Girl with the Dragon Tattoo\n"
    "Author : Stieg Larsson\n"
    "Current category guess : other\n"
    "Current language guess : unknown\n\n"
    "Text sample:\n(no text available)\n",
    512,
)
print(f"generated in {time.time()-t0:.1f}s")
print(out)
data = json.loads(out.removeprefix("```json").removesuffix("```").strip()
                  if out.startswith("```") else out)
assert data["category"] == "reading", data
print("SMOKE TEST OK:", data)
EOF
```

Expected: `loaded in ~7s` (warm cache), generation in seconds, `SMOKE TEST OK` with a sane JSON dict. If `mlx_vlm.generate()` rejects a kwarg (`temperature`/`temp` naming varies across versions), fix `_load_vlm()` in `organizer/mlx_client.py` to match the installed 0.6.4 signature and re-run both this smoke test and `python3 -m unittest tests.unit.test_mlx_client -v`.

- [ ] **Step 4: Optional end-to-end check**

Run: `python3 organize_books.py --dry-run`
Expected: banner shows `LLM backend : mlx (model: mlx-community/gemma-4-26B-A4B-it-qat-mxfp8)`, the health check loads the model, and any low-confidence book prints `[LLM/mlx] ... -- asking ...`. (Skippable if the library source folder is huge; the smoke test in Step 3 already covers load + generate.)

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document mlx-lm default backend and LLM backend selection

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
