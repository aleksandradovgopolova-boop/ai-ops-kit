"""Гранулярные тесты validate_bootstrap_qualification (миграция из селфтеста v3.30)."""
from __future__ import annotations

import copy

import pytest

from validate_bootstrap_qualification import (  # noqa: F401
    DEFAULT_PLAN,
    check,
    yaml,
)


@pytest.fixture(scope="module")
def base_plan():
    if not DEFAULT_PLAN.exists():
        pytest.fail(f"v3.8.0-plan не найден ({DEFAULT_PLAN}) — тест выполнить нечем")
    return yaml.safe_load(DEFAULT_PLAN.read_text(encoding="utf-8"))


@pytest.mark.unit
def test_real_plan_is_valid(base_plan):
    errs = check(base_plan)
    assert errs == [], f"реальный v3.8.0-plan имеет ошибки: {errs}"


@pytest.mark.unit
def test_missing_vertical_feature_stage(base_plan):
    d1 = copy.deepcopy(base_plan)
    d1["bootstrap_stages"] = [
        s for s in d1["bootstrap_stages"] if s["id"] != "vertical_feature"
    ]
    errs = check(d1)
    assert any("bootstrap_stages" in x for x in errs)


@pytest.mark.unit
def test_missing_provider_fallback_scenario(base_plan):
    d2 = copy.deepcopy(base_plan)
    d2["readiness_scenarios"] = [
        s for s in d2["readiness_scenarios"] if s["id"] != "provider_fallback"
    ]
    errs = check(d2)
    assert any("readiness_scenarios" in x for x in errs)


@pytest.mark.unit
def test_missing_zero_false_green_exit_criterion(base_plan):
    d3 = copy.deepcopy(base_plan)
    d3["exit_criteria"] = [c for c in d3["exit_criteria"] if c != "zero_false_green"]
    errs = check(d3)
    assert any("exit_criteria" in x for x in errs)


@pytest.mark.unit
def test_phantom_builds_over_ref(base_plan):
    d4 = copy.deepcopy(base_plan)
    d4["builds_over"] = [{"name": "Ghost", "ref": "tools/ghost_subsystem.py"}]
    errs = check(d4)
    assert any("не существует" in x for x in errs)


@pytest.mark.unit
def test_no_greenfield_child(base_plan):
    d5 = copy.deepcopy(base_plan)
    d5["reference_children"] = [
        c for c in d5["reference_children"] if c.get("kind") != "greenfield"
    ]
    errs = check(d5)
    assert any("greenfield" in x for x in errs)


@pytest.mark.unit
def test_security_judge_before_bench_v2(base_plan):
    d6 = copy.deepcopy(base_plan)
    d6["models"] = {"security_integration_judge": "kimi"}
    errs = check(d6)
    assert any("security_integration_judge" in x for x in errs)
