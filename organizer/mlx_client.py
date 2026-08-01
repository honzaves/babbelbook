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
