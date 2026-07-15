# Design: mlx-lm as the default LLM backend

**Date:** 2026-07-15
**Status:** Approved by user (all sections)
**Source material:** `mlx-lm-handover.md` (empirical migration guide, referenced throughout as "handover §N")

## Goal

Replace Ollama with in-process [mlx-lm](https://github.com/ml-explore/mlx-lm) as the
default backend for step 8 of the classification pipeline (LLM reclassification of
low-confidence books). Ollama remains fully functional as a user-selectable
alternative. Measured on a comparable structured-extraction task, mlx-lm ran the same
weights 5.6× faster than Ollama.

## Scope

The LLM is called from exactly one place: `classify_with_ollama()` in
`organizer/enrichment.py`, invoked by `organizer/classifier.py` (step 9) when
confidence < threshold. The Flet app and Flask browser never call the LLM (their
"ollama" mentions are cache-key prefixes in the cache inspector, which keep working
unchanged). Only the organizer pipeline is touched.

## Decisions (user-confirmed)

| Decision | Choice |
|---|---|
| Backend selection | `config.py` constant `LLM_BACKEND` with `BABBELBOOK_LLM_BACKEND` env-var override; default `"mlx"` |
| MLX model | `mlx-community/gemma-4-26B-A4B-it-qat-mxfp8` (exact HF repo id to be verified at implementation time; must be an `-it` QAT/mxfp8 conversion — handover §1, §4) |
| Cache keys | Per-backend prefix: `mlx:{title}:{author}` vs existing `ollama:{title}:{author}`. Old Ollama entries stay intact and are reused when switching back. Books previously classified by Ollama get re-classified once by the new model. |
| mlx failure at startup | **Hard error**: print reason, `sys.exit(1)`. No auto-fallback to Ollama, no silent skip. |
| mlx failure mid-run (per book) | Warn + keep heuristic classification, run continues (matches today's per-book Ollama error handling). |
| Architecture | Dedicated backend module `organizer/mlx_client.py`; shared logic stays in `enrichment.py`. |

Target machine: Apple M2 Max, 96 GB unified memory — the ~16 GB resident model is a
non-issue. First-ever startup downloads ~13 GB from Hugging Face (inside the startup
health check, per the hard-error semantics); warm starts load in ~7 s.

## Section 1 — Configuration (`config.py`)

```python
# -- LLM backend --------------------------------------------------------------
LLM_BACKEND = os.environ.get("BABBELBOOK_LLM_BACKEND", "mlx")   # "mlx" | "ollama"

# mlx settings
MLX_MODEL       = "mlx-community/gemma-4-26B-A4B-it-qat-mxfp8"
MLX_MAX_TOKENS  = 512          # classification JSON is tiny
LLM_TEMPERATURE = 0.1          # shared by both backends (matches current Ollama option)

# ollama settings (unchanged)
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL    = "gpt-oss:20b"
```

Renames (these gate/report the LLM step regardless of backend):

- `OLLAMA_THRESHOLD` → **`LLM_THRESHOLD`** — update `classifier.py`,
  `organize_books.py`, CLAUDE.md.
- `OLLAMA_OK` → **`LLM_OK`** — set by the startup health check, gates step 9.

Dependencies: add `mlx-lm>=0.31` and `mlx-vlm>=0.6.1` to `requirements.txt` /
`pyproject.toml` (mlx-vlm is required for "unified" multimodal architectures such as
the gemma-4 family — handover §1, §2.4). Pin versions: the lm→vlm fallback detection
string-matches error messages and is brittle across versions (handover §2.4).

## Section 2 — New module `organizer/mlx_client.py`

All MLX-specific machinery, mirroring the handover's reference client (§5):

- **`MlxError(Exception)`** — the single typed error every failure is normalized
  into: import failure, download failure, load failure, generate failure, empty
  output. Carries the raw model response when one exists.
- **`_MLX_THREAD = ThreadPoolExecutor(max_workers=1)`** — every MLX operation (load
  *and* generate) is submitted to this one thread (handover §2.1). Mandatory: the
  organizer runs a 10-worker `ThreadPoolExecutor`, and MLX binds its GPU stream to
  the loading thread. `max_workers=1` also serializes concurrent generate calls,
  which MLX requires; organizer workers needing classification simply queue.
- **`ensure_loaded()`** — eagerly loads model + tokenizer on the MLX thread. Tries
  `mlx_lm.load(MLX_MODEL)`; on unsupported-architecture / missing-module errors falls
  through to `mlx_vlm.load()` (handover §2.4). Raises `MlxError` on any failure.
  Called once at organizer startup.
- **`generate(system, user, max_tokens)`** — on the MLX thread:
  1. `apply_chat_template(..., add_generation_prompt=True, tokenize=False,
     enable_thinking=False)`; on `TypeError` retry without the kwarg and **log a
     warning** (handover §2.3 — silent fallback = undiagnosable slowdowns).
  2. If the template rejects the `system` role, fold the system prompt into the user
     turn (`f"{system}\n\n{user}"`) and retry; system-role path stays primary
     (handover §2.5).
  3. Run generation with `sampler=make_sampler(temp=LLM_TEMPERATURE)` and
     `max_tokens` (handover §3 sampling parity).
  4. Clean: split on the *last* reasoning-channel close marker if present
     (handover §2.3 belt-and-braces), strip whitespace.
  5. Empty result → `MlxError`. Return the cleaned raw string.

No health-check endpoint semantics to worry about (batch CLI, eager load).
The model stays resident until the process exits — correct for a batch run.

## Section 3 — Dispatch and error handling (`enrichment.py`, call sites)

- **`classify_with_llm(title, author, sample, current_category, current_language)`**
  replaces `classify_with_ollama` as the public entry point. Owns everything
  backend-agnostic:
  - cache key: `f"{config.LLM_BACKEND}:{title}:{author}"` → `mlx:` or `ollama:`
  - the existing `_OLLAMA_SYSTEM` prompt (renamed `_LLM_SYSTEM`) and user prompt —
    identical for both backends; it already demands JSON-only output, which is the
    required strategy under mlx-lm since there is no grammar-forced JSON
    (handover §2.2)
  - dispatch: `mlx_client.generate(...)` or the existing Ollama HTTP call (kept
    verbatim as private `_ollama_generate`)
  - shared response handling: strip code fences, extract outermost `{…}`,
    `json.loads`, validate `category` against `MAIN_CATEGORIES` (fallback
    `"other"`), `cache_set`
- **Startup (`organize_books.py`)** — new `check_llm_backend()`:
  - `mlx`: call `mlx_client.ensure_loaded()`; on `MlxError` print the reason and
    `sys.exit(1)`. Sets `config.LLM_OK = True` on success.
  - `ollama`: existing `check_ollama()` soft behavior unchanged (warn, set
    `LLM_OK = False`, LLM step skipped).
  - Startup banner prints the active backend and model.
- **Mid-run**: `classify_with_llm` catches `MlxError` (and the existing Ollama
  exceptions), prints a per-book warning, returns `None`; the book keeps its
  heuristic classification. Hard error is startup-only.
- **`classifier.py`** (step 9): gate becomes `config.LLM_OK`; calls
  `classify_with_llm`; appends the *backend name* (`"mlx"` or `"ollama"`) to
  `meta.sources`. The confidence boost at `_score` applies to either tag.
  `organizer.py` summary counts either tag and reports the active model.

## Section 4 — Tests and docs

- **`tests/unit/test_mlx_client.py`** (mlx packages mocked; must not require Apple
  silicon or the real packages):
  - thread-confinement regression test: load + generate both execute on one thread
    that is not the caller's (handover §2.1)
  - channel-marker cleaning; `enable_thinking` `TypeError` fallback emits a warning;
    system-role rejection fallback; every failure surfaces as `MlxError`;
    empty-output → `MlxError`
- **`tests/unit/test_enrichment_dispatch.py`**:
  - backend dispatch honors `LLM_BACKEND`
  - cache-key prefixes are per-backend; an `ollama:` cache hit is not consulted when
    backend is `mlx` and vice versa
  - Ollama request path behaves exactly as before the change
  - fence-stripping / JSON extraction / category validation shared-path tests
- Existing tests: mechanical updates for `LLM_THRESHOLD` / `LLM_OK` renames.
  Integration tests already mock all LLM I/O.
- **CLAUDE.md**: pipeline step 8 wording, threshold table, config description, and a
  short "LLM backends" note (default mlx, `BABBELBOOK_LLM_BACKEND=ollama` to switch,
  hard-fail semantics for mlx).

## Out of scope

- No changes to `browser/` or `babbelbook_flet.py` (they never call the LLM).
- No settings UI.
- No benchmark harness (model choice already made; can be added later if quality
  concerns appear).
- No idle-unload / keep-alive machinery (batch process).

## Implementation notes

- Verify the exact `mlx-community` repo id for gemma-4-26B-A4B-it QAT/mxfp8 before
  coding; must be the `-it` conversion (base models produce fluent nonsense —
  handover §1).
- Port the existing guards: the Ollama path's timeout has no direct equivalent
  in-process; rely on `max_tokens` bounding generation length instead.
