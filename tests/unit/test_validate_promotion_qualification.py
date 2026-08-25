"""Гранулярные тесты validate_promotion_qualification (миграция из селфтеста v3.30)."""
from __future__ import annotations

import pytest

from validate_promotion_qualification import (  # noqa: F401
    DEFAULT_PLAN,
    _good_plan,
    check,
    yaml,
)


@pytest.fixture
def good_plan():
    """Валидный план promotion qualification."""
    return _good_plan()


@pytest.mark.unit
def test_valid_plan_passes(good_plan):
    """Валидный план проходит."""
    assert check(good_plan) == []


@pytest.mark.unit
def test_wrong_promotion_sequence_is_error(good_plan):
    """promotion_sequence не shadow->hybrid->default -> ошибка."""
    bad = {**good_plan, "promotion_sequence": [{"stage": "default", "description": "d", "gate": "g"}]}
    errs = check(bad)
    assert any("promotion_sequence" in x for x in errs), errs


@pytest.mark.unit
def test_run_without_exact_sha_bound_is_error(good_plan):
    """run без exact_sha_bound -> ошибка."""
    bad = good_plan.copy()
    bad["runs"] = [dict(r) for r in bad["runs"]]
    bad["runs"][0]["exact_sha_bound"] = False
    errs = check(bad)
    assert any("exact_sha_bound" in x for x in errs), errs


@pytest.mark.unit
def test_uses_nonexistent_tool_is_error(good_plan):
    """uses на несуществующий инструмент -> ошибка (честность)."""
    bad = good_plan.copy()
    bad["runs"] = [dict(r) for r in bad["runs"]]
    bad["runs"][0]["uses"] = ["does_not_exist_9x.py"]
    errs = check(bad)
    assert any("несуществующ" in x for x in errs), errs


@pytest.mark.unit
def test_incomplete_negative_scenarios_is_error(good_plan):
    """Неполный набор негативов -> ошибка."""
    bad = good_plan.copy()
    bad["negative_scenarios"] = bad["negative_scenarios"][:-1]
    errs = check(bad)
    assert any("негатив" in x for x in errs), errs


@pytest.mark.unit
def test_incomplete_exit_criteria_is_error(good_plan):
    """Неполный набор exit-критериев -> ошибка."""
    bad = good_plan.copy()
    bad["exit_criteria"] = bad["exit_criteria"][:-1]
    errs = check(bad)
    assert any("критери" in x for x in errs), errs


@pytest.mark.unit
def test_runs_not_covering_all_kinds_is_error(good_plan):
    """runs не покрывают все три вида -> ошибка."""
    bad = good_plan.copy()
    bad["runs"] = bad["runs"][:2]
    errs = check(bad)
    assert any("обязательные виды" in x for x in errs), errs


@pytest.mark.unit
def test_empty_blocked_by_is_error(good_plan):
    """Пустой blocked_by -> ошибка."""
    bad = {**good_plan, "blocked_by": []}
    errs = check(bad)
    assert any("blocked_by" in x for x in errs), errs


@pytest.mark.unit
def test_real_default_plan_is_valid():
    """Реальный план на диске (если есть) — валиден."""
    if DEFAULT_PLAN.exists():
        data = yaml.safe_load(DEFAULT_PLAN.read_text(encoding="utf-8"))
        errs = check(data)
        assert errs == [], errs
