"""Гранулярные тесты cost_method (мигрировано из test_cost_method_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.providers.cost_method import (
    advise,
    check,
)


@pytest.mark.unit
class TestAdviseEngineering:
    def test_heavy_context_hygiene_priority_1(self):
        r = advise({"task_type": "ENGINEERING"}, snapshot={"context_current": 450_000})
        assert r and r[0]["priority"] == 1 and r[0]["category"] == "session_hygiene"

    def test_priority_order_non_decreasing(self):
        r = advise({"task_type": "ENGINEERING"}, snapshot={"context_current": 450_000})
        assert all(r[i]["priority"] <= r[i + 1]["priority"] for i in range(len(r) - 1))

    def test_check_valid(self):
        r = advise({"task_type": "ENGINEERING"}, snapshot={"context_current": 450_000})
        assert check(r) == []

    def test_3_fix_iterations_advises_stop(self):
        r = advise({"task_type": "ENGINEERING", "fix_attempts": 3}, snapshot={"context_current": 50_000})
        assert any(x["category"] == "iteration_limit" for x in r)

    def test_30_files_delegation_priority_2(self):
        r = advise({"task_type": "ENGINEERING", "exploration_files": 30}, snapshot={"context_current": 50_000})
        assert any(x["category"] == "delegation" and x["priority"] == 2 for x in r)

    def test_unknown_context_advises_context(self):
        r = advise({"task_type": "ENGINEERING"}, snapshot={"context_current": None})
        assert any("context" in x["advice"].lower() for x in r if x["category"] == "session_hygiene")

    def test_small_change_affected_tests(self):
        r = advise({"task_type": "ENGINEERING", "small_change": True}, snapshot={"context_current": 50_000})
        assert any(x["category"] == "tests" for x in r)


@pytest.mark.unit
class TestAdviseQuick:
    def test_quick_cheap_runtime(self):
        r = advise({"task_type": "QUICK"}, snapshot={"context_current": 50_000})
        cats = {x["category"]: x["advice"] for x in r}
        assert "runtime" in cats and "не нужен" in cats["runtime"]

    def test_quick_low_effort(self):
        r = advise({"task_type": "QUICK"}, snapshot={"context_current": 50_000})
        cats = {x["category"]: x["advice"] for x in r}
        assert "effort" in cats and "low effort" in cats["effort"]


class TestSkippedAdviceIsNamed:
    """Пропущенная категория совета НАЗЫВАЕТСЯ, а не исчезает (срез providers ратчета, 2026-08-12)."""

    def test_broken_subadvisor_is_named_not_dropped(self, monkeypatch):
        """Сбой под-советчика -> в выдаче есть пункт «НЕ ОЦЕНЕНО», а не тишина."""
        from ai_ops_kit.providers import cost_method
        from ai_ops_kit.engops import session_guardrails as sg

        def boom(*a, **k):
            raise RuntimeError("под-советчик сломан")

        monkeypatch.setattr(sg, "load_policy", boom)
        out = cost_method.advise({"task_type": "QUICK"})
        skipped = [o for o in out if "НЕ ОЦЕНЕНО" in str(o.get("advice"))]
        assert skipped, f"категория выпала молча: {[o.get('category') for o in out]}"
        assert "session_hygiene" in skipped[0]["category"]
        assert "RuntimeError" in skipped[0]["advice"], "не сказано, ПОЧЕМУ не оценено"

    def test_healthy_run_has_no_skipped_marker(self):
        """Обратная сторона: на исправных советчиках «НЕ ОЦЕНЕНО» не появляется."""
        from ai_ops_kit.providers import cost_method
        out = cost_method.advise({"task_type": "QUICK"})
        assert not [o for o in out if "НЕ ОЦЕНЕНО" in str(o.get("advice"))], out

    def test_advice_still_returned_when_one_category_fails(self, monkeypatch):
        """fail-open сохранён: остальные советы на месте, команда не падает."""
        from ai_ops_kit.providers import cost_method
        from ai_ops_kit.engops import session_guardrails as sg
        monkeypatch.setattr(sg, "load_policy", lambda *a, **k: (_ for _ in ()).throw(OSError("нет файла")))
        out = cost_method.advise({"task_type": "QUICK"})
        cats = {o["category"] for o in out}
        assert len(cats) >= 2, f"сбой одной категории убил всю выдачу: {cats}"
