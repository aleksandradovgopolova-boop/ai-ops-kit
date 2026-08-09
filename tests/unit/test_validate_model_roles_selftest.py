"""Селфтест validate_model_roles, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_model_roles import (  # noqa: F401 — имена, которые использует тело
    DEFAULT,
    ROLES,
    _model_classes_and_cost,
    check,
    yaml,
)


@pytest.mark.slow
def test_validate_model_roles_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    if DEFAULT.exists():
        errs = check(yaml.safe_load(DEFAULT.read_text(encoding="utf-8")))
        expect("реальный registry/model-roles.yaml валиден", errs == [])
        for x in errs:
            print("   -", x)

    classes, _ = _model_classes_and_cost()
    base = {"registry_type": "model-roles",
            "roles": {r: {"preferred_class": ("balanced" if r in ("implementation", "code_review") else "high-reasoning"),
                          "fallback_class": "high-reasoning"} for r in ROLES},
            "escalation_policy": {"triggers": ["reviewer_abstain"], "max_targeted_retries": 1,
                                  "escalate_scope": "review_only", "cost_never_by_weakening_gates": True},
            "qualification_matrix": {
                "balanced": {"implementation": "qualified", "code_review": "conditional",
                             "security_review": "not_qualified", "integration_judge": "not_qualified"},
                "high-reasoning": {"implementation": "qualified", "code_review": "qualified",
                                   "security_review": "qualified", "integration_judge": "qualified"}}}
    expect("синтетический базовый валиден", check(base) == [])
    expect("escalate_scope != review_only -> ошибка",
           any("review_only" in x for x in check({**base, "escalation_policy": {**base["escalation_policy"], "escalate_scope": "full"}})))
    expect("cost_never_by_weakening_gates=false -> ошибка",
           any("cost_never" in x for x in check({**base, "escalation_policy": {**base["escalation_policy"], "cost_never_by_weakening_gates": False}})))
    # судья на неквалифицированном классе -> ошибка
    bad_judge = {**base, "roles": {**base["roles"], "security_review": {"preferred_class": "balanced", "fallback_class": "balanced"}}}
    expect("security_review на 'balanced' (не qualified) -> safety-first ошибка",
           any("судья" in x for x in check(bad_judge)))
    # несуществующий класс
    expect("несуществующий класс -> ошибка",
           any("model_classes" in x for x in check({**base, "roles": {**base["roles"], "implementation": {"preferred_class": "vibes", "fallback_class": "high-reasoning"}}})))

    assert ok, "перенесённый селфтест validate_model_roles: см. строки FAIL в выводе"
