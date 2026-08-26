"""Unit-тесты RunContext — переписываемого состояния pipeline-ветви run().

K6-глубина: скелет вводится ПЕРВЫМ, чистым добавлением (run() ещё не тронут). Тесты
фиксируют контракт фабрики и мутабельность полей, на которые впредь опрутся вынесенные
из run() блоки (resume-restore, model-routing, execute+fix-loop, delivery).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ai_ops_kit.engine.run_context import RunContext


def _mk(**over):
    base = dict(task_text="добавить X", signals={"task_type": "QUICK"}, child_root="/tmp/child",
               features_dir=None, feature="feat-1", provider_name="mock", model=None,
               runtime="claude-code", sandbox=False, baseline_diff=False, require_fix=False,
               author=False, review=False, open_pr=False, write_scope=None, max_steps=40, base=None)
    base.update(over)
    return RunContext.from_run_args(**base)


@pytest.mark.unit
class TestFromRunArgs:
    """Фабрика собирает ctx из аргументов run() с той же нормализацией, что и голова run()."""

    def test_stable_inputs_carried(self):
        ctx = _mk()
        assert ctx.child_root == Path("/tmp/child")
        assert ctx.feature == "feat-1"
        assert ctx.provider_name == "mock"
        assert ctx.runtime == "claude-code"

    def test_features_dir_defaults_under_child_root(self):
        """features_dir=None -> child_root/features (то же правило, что в голове run())."""
        assert _mk(features_dir=None).features_dir == Path("/tmp/child") / "features"

    def test_features_dir_explicit_kept(self):
        assert _mk(features_dir="/tmp/other/features").features_dir == Path("/tmp/other/features")

    def test_signals_gets_task_text(self):
        """setdefault task_text — как в run() (строка signals.setdefault)."""
        assert _mk(signals={}, task_text="Z").signals["task_text"] == "Z"

    def test_signals_existing_task_text_not_overwritten(self):
        assert _mk(signals={"task_text": "keep"}, task_text="other").signals["task_text"] == "keep"

    def test_signals_none_becomes_dict(self):
        assert _mk(signals=None).signals == {"task_text": "добавить X"}

    def test_signals_is_a_copy_not_the_caller_dict(self):
        """Фабрика копирует signals — мутация ctx.signals не трогает переданный dict."""
        src = {"task_type": "ENGINEERING"}
        ctx = _mk(signals=src)
        ctx.signals["risk"] = "high"
        assert "risk" not in src

    def test_policy_defaults_reflected(self):
        ctx = _mk(sandbox=True, review=True, max_steps=7, base="main", write_scope=["a/"])
        assert ctx.sandbox is True and ctx.review is True
        assert ctx.max_steps == 7 and ctx.base == "main" and ctx.write_scope == ["a/"]


@pytest.mark.unit
class TestMutableState:
    """Поля ctx мутабельны на месте — так вынесенные хелперы перевязывают состояние прогона."""

    def test_routing_fields_default_empty(self):
        ctx = _mk()
        assert ctx.writer_model is None and ctx.writer_prov is None
        assert ctx.model_resolution is None and ctx.sec_qualified is False
        assert ctx.prop is None and ctx.rev_prop is None and ctx.auth_prop is None

    def test_trust_cache_is_independent_per_instance(self):
        """default_factory: у каждого ctx свой trust_cache (не разделяемый мутабельный дефолт)."""
        a, b = _mk(), _mk()
        a.trust_cache["deepseek"] = {"ready": True}
        assert b.trust_cache == {}

    def test_policy_fields_rewritable(self):
        """resume-restore перезаписывает policy-поля — фиксируем, что это возможно на месте."""
        ctx = _mk(sandbox=False, base=None)
        ctx.signals = {**ctx.signals, "risk": "high"}
        ctx.sandbox = True
        ctx.base = "release/1.x"
        ctx.saved_task = "исходная продуктовая задача"
        assert ctx.sandbox is True and ctx.base == "release/1.x"
        assert ctx.signals["risk"] == "high" and ctx.saved_task == "исходная продуктовая задача"

    def test_replan_flag_carried(self):
        assert _mk(replan=True).replan is True
        assert _mk().replan is False
