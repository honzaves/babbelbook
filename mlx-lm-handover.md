# Switching from Ollama to mlx-lm — Handover Guide

**Audience:** any application currently calling Ollama that wants to run models in-process via [mlx-lm](https://github.com/ml-explore/mlx-lm) on Apple silicon.
**Provenance:** every item below was *empirically hit* while migrating the recipe-extractor pipeline (2026-07). Reference implementation: `src/recipe_extractor/mlx_client.py` (production client, all lessons baked in), `compare_models_mlx.py` (evaluation harness). Measured outcome there: **same weights, same quant, 5.6× faster than Ollama** (gemma-4-26B-A4B mxfp8: 324s vs 1812s over an 18-chunk benchmark) with equal extraction fidelity.

---

## 1. Prerequisites

| Requirement | Detail |
|---|---|
| **Apple silicon** | MLX is Metal-only. No Intel Macs, no Linux, no Windows. Keep an Ollama (or other) fallback path if the app must run elsewhere. |
| **Unified memory** | The model lives **in your process**: ~16 GB resident for a 26B mxfp8, ~8 GB for a 12B. Size = weights + KV cache + your app. Check `sysctl hw.memsize` headroom before committing. |
| **Python packages** | `mlx-lm>=0.31` for text architectures. **`mlx-vlm>=0.6.1` additionally required for "unified"/multimodal architectures** (e.g. `gemma4_unified`) — mlx-lm alone fails with `Model type X not supported`. |
| **Models from Hugging Face** | Use `mlx-community/*` conversions; they resolve through the standard HF cache (`~/.cache/huggingface/hub`). First use of a new model downloads it (a 26B mxfp8 ≈ 13 GB) — decide whether first-request download latency is acceptable or pre-pull at deploy time. |
| **Instruction-tuned (`-it`) conversions ONLY** | `mlx-community/<model>-mxfp8` without `-it` is the **base** model: no chat template, continues your prompt as prose, hallucinates content. Symptom: fluent nonsense instead of task output. Always pick the `-it` variant. |

---

## 2. The five bugs you WILL hit (and their fixes)

These are not theoretical — each one broke the reference migration in sequence.

### 2.1 Thread affinity — the production killer
**Symptom:** `RuntimeError: There is no Stream(gpu, 1) in current thread` on every call — but only in production, never in test scripts.
**Cause:** MLX binds its GPU stream to the thread that loads the model. Single-threaded scripts work; real apps (FastAPI threadpools, background job threads, any framework that dispatches work across threads) load in one thread and generate in another.
**Fix:** confine **all** MLX work — load *and* generate — to one dedicated thread:

```python
_MLX_THREAD = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mlx")

def generate(...):
    return _MLX_THREAD.submit(_generate_on_mlx_thread, ...).result()
```

`max_workers=1` also serializes concurrent requests, which you want anyway — MLX generation is not thread-safe. Exceptions propagate unchanged through `Future.result()`. Write a regression test asserting load + generate all execute on one non-caller thread.

### 2.2 No grammar-constrained JSON
Ollama's `format: "json"` **does not exist** in mlx-lm. If your app depends on structured output:
- Prompt explicitly for JSON (system prompt: "return ONLY the JSON object, no markdown, no prose").
- Clean deterministically before parsing: strip code fences, extract the outermost `{…}`.
- Treat parse failures as first-class: raise a typed error carrying the raw response, and have a retry/dead-letter path.
- Measured with a well-trained `-it` model (gemma-4-26B-A4B): 18/18 clean JSON without any constraint. But it is *behavioral*, not guaranteed — validate every response.

### 2.3 Reasoning / thinking channels
Newer models (Gemma 4 family and others) default to emitting a reasoning channel (`<|channel>thought…`) before the answer. Consequences: token budget burned on thoughts, parse failures, ~4× slower responses.
**Fix:** pass `enable_thinking=False` to `apply_chat_template(...)` — the template then emits a pre-closed empty thought and the model answers directly. Two gotchas:
- mlx-vlm's `apply_chat_template` may not accept the kwarg in some versions → wrap in `try/except TypeError`, retry without it, **log a warning** (silent fallback = undiagnosable slowdowns).
- Belt-and-braces: make your cleaner split on the *last* channel-close marker (`text.rsplit("<channel|>", 1)[1]`) before JSON extraction.

### 2.4 Architecture support gaps
`ValueError: Model type <X> not supported` — mlx-lm's architecture list lags new model families, and multimodal "unified" variants live in mlx-vlm, not mlx-lm. Robust loader: try `mlx_lm.load()`, and on unsupported-arch/missing-module errors fall through to `mlx_vlm.load()`. Note the detection is string-matching on error messages ("not supported", "No module named") — brittle across versions, pin your versions.

### 2.5 System-role rejection
Some chat templates reject a `system` role outright (exception from `apply_chat_template`). Fallback: fold the system prompt into the user turn (`f"{system}\n\n{user}"`). Keep the system-role path primary — templates that support it behave better.

---

## 3. Operational caveats (vs. what Ollama gave you for free)

| Ollama gave you | With mlx-lm you must |
|---|---|
| A shared server — CLI + web app + scripts all hit one resident model | Accept **one copy per process** (16 GB × N processes), or run `mlx_lm.server` (OpenAI-compatible HTTP) as your own shared daemon |
| `ollama pull` model registry | Manage HF repo ids + cache yourself |
| Per-request `model:` switching | One model per process; hot-swap means reload |
| Grammar-forced JSON | §2.2 |
| Process isolation (model crash ≠ app crash) | A Metal/MLX fault takes your app process with it |
| `keep_alive` idle unload | The model stays resident until your process exits (or you build unloading) |
| Request queueing | Your own serialization (the single-thread executor gives you this) |

More:
- **Lazy-load, and decide health-check semantics.** If `health()` triggers the load, a monitoring probe or stray `curl` blocks minutes (download) and pins 16 GB. Distinguish "runtime importable" from "model loaded", or document the cost.
- **First-call latency:** ~7s model load from a warm cache (per process, per restart); one-time ~13 GB download cold.
- **Dev-server reload** (`uvicorn --reload` etc.) double-loads the model across restarts.
- **Port your guards.** Whatever your Ollama client checked — empty responses, repetition loops (`"own own own …"`), timeouts — port them; mlx-lm gives you a raw string and nothing else. Normalize **every** failure (import, download, load, generate, parse) into your app's single error type so downstream handling stays backend-agnostic.
- **Keep the old backend switchable.** A config flag (`LLM_BACKEND=mlx|ollama`) with the Ollama path untouched cost almost nothing and provides instant rollback + a non-Apple-silicon story.
- **Sampling parity:** mlx-lm uses `sampler=make_sampler(temp=…)` and `max_tokens=`; map your `num_predict`/`temperature` explicitly — defaults differ from Ollama's.

---

## 4. Model & quantization guidance (measured)

- **mxfp8 quants are near-lossless; naive 4-bit quants are not** — especially for MoE models, where Q4 post-training quantization collapses quality (documented: naive Q4_0 on gemma-4-26B-A4B → 70.2% top-1 vs ~85.6% recovered). Prefer mxfp8 or QAT conversions; for MoE, treat non-QAT 4-bit as broken until proven otherwise.
- **MoE is the speed sweet spot in-process:** a 26B-A4B (3.8B active params) generates *faster* than a dense 12B while carrying far more capacity. Don't assume smaller = faster.
- **Measured cross-runtime matrix** (same task, same 18 inputs, same prompts; M-series Mac, all `-it` mxfp8 conversions):

  | Model | via mlx-lm | via Ollama | MLX speedup | Fidelity |
  |---|---:|---:|---:|---|
  | gemma-4-26B-A4B (MoE, 3.8B active) | **324s** | 1812s | **5.6×** | clean (1 minor dup quirk) |
  | gemma-4-31B (dense) | 2170s | 4436s | 2.0× | **cleanest of all configs** |
  | gemma-4-12B (dense) | 830s | (broken GGUF) | — | clean |

  Two rules of thumb fall out: the **MLX runtime bonus is largest for MoE** (sparse activation seems to suit MLX's kernels), and the **MoE tax for choosing dense-31B quality is ~6.7×** (~120s vs ~18s per equivalent unit). The dense 31B was the *fidelity ceiling* — it even fixed an omission its own Ollama-served twin made — so "dense for quality-critical, MoE for throughput" is a measured trade, not folklore.
- **Do NOT use Ollama's own `-mlx` model tags as a proxy for mlx-lm.** Ollama's MLX backend ignores `format:"json"` (markdown-fenced output, mass parse failures). "MLX via Ollama" ≠ "mlx-lm direct"; only the latter is covered by this guide.
- **Benchmark before trusting, on YOUR task.** Build a fixed input set with known-answer tripwires (items a lossy model silently drops or duplicates — silent corruption never shows up in error rates). Run every candidate model/quant through the identical harness and diff outputs. See `compare_models_mlx.py` + `docs/model_comparison.md` for the pattern; small samples mislead (a model that looked fine at n=6 showed silent data loss at n=18).
- **Budget generative workloads by OUTPUT tokens, not requests.** Measured output rates on an M-series Mac (mxfp8, in-process): dense 31B ≈ **5–8 tok/s**, 26B-A4B MoE ≈ **30–40 tok/s**. For long-form generation (translation, book summarization: ~120k output tokens per 300-page book) that is the difference between ~5–6 hours and under an hour per book. Extraction-style tasks (short structured output from long input) feel much faster than translation-style tasks (output ≈ input length) on the *same* model — plan capacity on tokens out.
- **Task-fit beats a single "best model".** Published benchmarks for the gemma-4 pair: 26B-A4B ≈ 97% of dense-31B quality overall, but the *knowledge* gap is large (49.2 vs 61.3) — dense wins where nuance/world-knowledge dominates (translation idiom, terminology); the MoE is the economical choice for compression-style tasks (summaries, extraction). Running both models split by task is often the right architecture — they share the HF cache, but each loaded model pins its own RAM, so load them in separate processes or sequentially, not concurrently in one process.

---

## 5. Minimal reference client (all lessons combined)

```python
from concurrent.futures import ThreadPoolExecutor

_MLX_THREAD = ThreadPoolExecutor(max_workers=1)   # §2.1
_runtime = None

def _load():                                       # §2.4: lm → vlm fallback
    try:
        from mlx_lm import load, generate
        from mlx_lm.sample_utils import make_sampler
        model, tok = load(REPO_ID)                 # -it conversion only (§1)
        sampler = make_sampler(temp=TEMPERATURE)
        def gen(system, user, max_tokens):
            msgs = ([{"role": "system", "content": system}] if system else []) \
                   + [{"role": "user", "content": user}]
            try:                                    # §2.3 + §2.5
                prompt = tok.apply_chat_template(msgs, add_generation_prompt=True,
                                                 tokenize=False, enable_thinking=False)
            except Exception:
                merged = [{"role": "user", "content": f"{system}\n\n{user}"}]
                prompt = tok.apply_chat_template(merged, add_generation_prompt=True,
                                                 tokenize=False, enable_thinking=False)
            return generate(model, tok, prompt=prompt, max_tokens=max_tokens,
                            sampler=sampler, verbose=False)
        return gen
    except (ValueError, ModuleNotFoundError):
        ...  # fall through to mlx_vlm.load(); wrap ALL other errors in your app error

def generate_json(prompt, system=None, max_tokens=10000):
    def body():
        global _runtime
        if _runtime is None:
            _runtime = _load()                     # lazy (§3)
        text = _runtime(system, prompt, max_tokens)
        # guards: empty / repetition / clean (§2.2, §2.3) / json.loads → typed error
        ...
    return _MLX_THREAD.submit(body).result()
```

The full production version (error taxonomy, repetition guard, health check, tests including the thread-confinement regression test) is `src/recipe_extractor/mlx_client.py` + `tests/test_mlx_client.py` in this repo.

---

## 6. Pre-flight checklist for a new app

- [ ] Apple silicon + enough unified memory for model + app + headroom
- [ ] `pip install "mlx-lm>=0.31" "mlx-vlm>=0.6.1"` (as an optional extra if the app runs elsewhere too)
- [ ] Picked an **`-it`**, **mxfp8/QAT** conversion from mlx-community
- [ ] Single dedicated MLX thread for load + generate (with regression test)
- [ ] JSON prompting + fence/channel cleaner + parse-failure dead-letter path
- [ ] `enable_thinking=False` with TypeError fallback + warning
- [ ] All failures normalized to one app error type
- [ ] Lazy load; health semantics decided (importable vs loaded)
- [ ] Backend flag with the old path intact for rollback
- [ ] Task-specific benchmark with silent-corruption tripwires run against the incumbent
