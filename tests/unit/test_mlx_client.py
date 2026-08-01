"""
tests/unit/test_mlx_client.py

Unit tests for organizer/mlx_client.py with mlx_lm / mlx_vlm fully mocked
via sys.modules — no Apple silicon, no model downloads, no real MLX import.

Covers:
  - thread confinement  load and generate run on one dedicated thread
                        that is NOT the caller's
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
        vlm.generate = MagicMock()
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


if __name__ == "__main__":
    unittest.main()
