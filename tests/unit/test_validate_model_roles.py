"""Гранулярные тесты validate_model_roles (миграция из селфтеста v3.30)."""
from __future__ import annotations

import pytest

from validate_model_roles import (  # noqa: F401
    DEFAULT,
    ROLES,
    _model_classes_and_cost,
    check,
    yaml,
)


@pytest.fixture
def base_plan():
    """Синтетический базовый валидный план."""
    return {
        "registry_type": "model-roles",
        "roles": {
            r: {
                "preferred_class": (
                    "balanced" if r in ("implementation", "code_review") else "high-reasoning"
                ),
                "fallback_class": "high-reasoning",
            }
            for r in ROLES
        },
        "escalation_policy": {
            "triggers": ["reviewer_abstain"],
            "max_targeted_retries": 1,
            "escalate_scope": "review_only",
            "cost_never_by_weakening_gates": True,
        },
        "qualification_matrix": {
            "balanced": {
                "implementation": "qualified",
                "code_review": "conditional",
                "security_review": "not_qualified",
                "integration_judge": "not_qualified",
            },
            "high-reasoning": {
                "implementation": "qualified",
                "code_review": "qualified",
                "security_review": "qualified",
                "integration_judge": "qualified",
            },
        },
    }


@pytest.mark.unit
def test_real_registry_is_valid():
    """Реальный registry/model-roles.yaml валиден."""
    if DEFAULT.exists():
        errs = check(yaml.safe_load(DEFAULT.read_text(encoding="utf-8")))
        assert errs == [], errs


@pytest.mark.unit
def test_synthetic_base_is_valid(base_plan):
    """Синтетический базовый валиден."""
    assert check(base_plan) == []


@pytest.mark.unit
def test_escalate_scope_not_review_only_is_error(base_plan):
    """escalate_scope != review_only -> ошибка."""
    bad = {**base_plan, "escalation_policy": {**base_plan["escalation_policy"], "escalate_scope": "full"}}
    errs = check(bad)
    assert any("review_only" in x for x in errs), errs


@pytest.mark.unit
def test_cost_never_by_weakening_gates_false_is_error(base_plan):
    """cost_never_by_weakening_gates=false -> ошибка."""
    bad = {
        **base_plan,
        "escalation_policy": {
            **base_plan["escalation_policy"],
            "cost_never_by_weakening_gates": False,
        },
    }
    errs = check(bad)
    assert any("cost_never" in x for x in errs), errs


@pytest.mark.unit
def test_security_review_on_unqualified_class_is_error(base_plan):
    """security_review на 'balanced' (не qualified) -> safety-first ошибка."""
    bad = {
        **base_plan,
        "roles": {
            **base_plan["roles"],
            "security_review": {"preferred_class": "balanced", "fallback_class": "balanced"},
        },
    }
    errs = check(bad)
    assert any("судья" in x for x in errs), errs


@pytest.mark.unit
def test_nonexistent_class_is_error(base_plan):
    """Несуществующий класс -> ошибка."""
    bad = {
        **base_plan,
        "roles": {
            **base_plan["roles"],
            "implementation": {"preferred_class": "vibes", "fallback_class": "high-reasoning"},
        },
    }
    errs = check(bad)
    assert any("model_classes" in x for x in errs), errs
