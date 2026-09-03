"""Гранулярные тесты validate_context_bundle (миграция с селфтеста)."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

from validate_context_bundle import (
    PKG,
    REQUIRED_INCLUDED,
    check,
)


@pytest.fixture(scope="module")
def good_bundle():
    """Минимальный валидный ContextBundle."""
    return {
        "schema_version": 1, "kind": "ContextBundle", "workitem_id": "wi-x",
        "included": {k: [] for k in REQUIRED_INCLUDED},
        "excluded": [{"source": "agent:foo", "reason": "не в RunPlan"}],
        "estimated_tokens": 100, "context_budget": 1000, "overflow": False,
        "open_questions": [],
    }


@pytest.mark.unit
@pytest.mark.slow
class TestContextBundleValidation:

    def test_valid_bundle(self, good_bundle):
        # Копия, не мутация: фикстура module-scoped, и запись в неё утекала в соседние тесты —
        # test_agent_in_both_... проходил только ПОСЛЕ этого теста (в xdist падал).
        bundle = json.loads(json.dumps(good_bundle))
        bundle["included"]["agents"] = ["a"]
        assert check(bundle) == []

    def test_wrong_kind_rejected(self):
        assert any("ContextBundle" in e for e in check({"kind": "x"}))

    def test_excluded_without_reason_rejected(self, good_bundle):
        bad = json.loads(json.dumps(good_bundle))
        bad["excluded"] = [{"source": "agent:foo"}]
        assert any("reason" in e for e in check(bad))

    def test_overflow_without_open_questions_rejected(self, good_bundle):
        bad = json.loads(json.dumps(good_bundle))
        bad["overflow"] = True
        bad["open_questions"] = []
        assert any("молча" in e for e in check(bad))

    def test_agent_in_both_included_and_excluded_rejected(self, good_bundle):
        bad = json.loads(json.dumps(good_bundle))
        # Самодостаточно: agents ставится ЗДЕСЬ, а не наследуется от мутации фикстуры соседним
        # тестом (scope="module" + порядок исполнения; в xdist порядок другой — тест падал в CI
        # и проходил локально, класс «первый по случайности»).
        bad["included"]["agents"] = ["a"]
        bad["excluded"] = [{"source": "agent:a", "reason": "x"}]
        assert any("included и excluded" in e for e in check(bad))

    def test_negative_tokens_rejected(self, good_bundle):
        bad = json.loads(json.dumps(good_bundle))
        bad["estimated_tokens"] = -1
        assert any("estimated_tokens" in e for e in check(bad))

    def test_real_compiler_produces_valid_bundle(self, good_bundle):
        sys.path.insert(0, str(PKG / "tools"))
        from ai_ops_kit.context import context_compiler
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "package.json").write_text(
                '{"dependencies":{"react":"^18"}}', encoding="utf-8")
            bundle = context_compiler.compile_bundle(
                {"task_type": "ENGINEERING", "risk": "medium",
                 "affected_areas": ["core"], "task_text": "t"},
                Path(td))
            assert check(bundle) == []
