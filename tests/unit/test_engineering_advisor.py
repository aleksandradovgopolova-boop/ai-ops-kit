"""Гранулярные тесты engineering_advisor (мигрировано из test_engineering_advisor_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import textwrap

import pytest

from ai_ops_kit.engops.engineering_advisor import (
    advise,
    check,
)


def _write_experience_contract(root):
    """Положить в дочку минимальный Experience Contract с названной целью пользователя."""
    d = root / ".ai" / "project"
    d.mkdir(parents=True, exist_ok=True)
    (d / "experience-contract.yaml").write_text(textwrap.dedent("""\
        id: cockpit
        title: Экран активной работы
        user_goal: понять, что идёт прямо сейчас
        flow:
          - {step: 1, action: открыть}
    """), encoding="utf-8")


@pytest.mark.unit
class TestAdvise:
    def test_advise_on_empty_repo_returns_engineering_advice(self, tmp_path):
        result = advise(str(tmp_path))
        assert result.get("kind") == "EngineeringAdvice"

    def test_check_valid(self, tmp_path):
        result = advise(str(tmp_path))
        assert check(result) == []

    def test_recommendations_is_list(self, tmp_path):
        result = advise(str(tmp_path))
        assert isinstance(result.get("recommendations", []), list)

    def test_summary_is_string(self, tmp_path):
        result = advise(str(tmp_path))
        assert isinstance(result.get("summary"), str)


@pytest.mark.unit
class TestCheck:
    def test_invalid_data_returns_errors(self):
        errors = check({"kind": "wrong"})
        assert errors


@pytest.mark.unit
class TestExperienceOptionsOffered:
    """#416: для UI-задачи варианты опыта ПРЕДЛАГАЮТСЯ рабочим кодом, каждый с trade-off."""

    def _options(self, result):
        return [r for r in result["recommendations"]
                if r.get("category") == "experience_options"]

    def test_visual_task_offers_options_each_with_a_tradeoff(self, tmp_path):
        """(а)+(г): рабочий `advise` предлагает варианты, и каждый несёт названную цену."""
        _write_experience_contract(tmp_path)
        opts = self._options(advise(str(tmp_path), task_type="VISUAL"))
        assert len(opts) >= 2, "для UI-задачи предложено меньше двух вариантов — это не выбор"
        for r in opts:
            assert "Чем платим:" in r["advice"], f"вариант предъявлен без trade-off: {r['advice']}"
            assert r["source"] == "experience_contract"

    def test_non_ui_task_offers_no_options(self, tmp_path):
        """(в): не-UI задача вариантов опыта не сыплет, даже если контракт лежит рядом."""
        _write_experience_contract(tmp_path)
        assert self._options(advise(str(tmp_path), task_type="PRODUCT")) == []
        assert self._options(advise(str(tmp_path))) == []

    def test_visual_task_without_contract_is_silent(self, tmp_path):
        """Нет Experience Contract — предлагать не из чего: молчим, не маскируем."""
        assert self._options(advise(str(tmp_path), task_type="VISUAL")) == []
