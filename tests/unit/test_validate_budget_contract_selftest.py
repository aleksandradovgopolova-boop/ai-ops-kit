"""Селфтест validate_budget_contract, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_budget_contract import (  # noqa: F401 — имена, которые использует тело
    DEMO,
    ON_EXH,
    SCHEMA,
    check,
    check_registry,
    json,
)


@pytest.mark.slow
def test_validate_budget_contract_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    ex = json.loads(SCHEMA.read_text(encoding="utf-8"))["examples"][0]
    expect("пример из схемы валиден", check(ex) == [])
    expect("реальный examples/budget-demo целостен",
           check_registry(DEMO)[0] == [])
    expect("limits без единой границы -> ошибка",
           any("хотя бы одна граница" in x for x in check({**ex,
               "limits": {"max_model_calls": None, "max_iterations": None, "max_tokens": None,
                          "max_cost_usd": None, "max_wall_seconds": None}})))
    expect("hard=true + degrade -> ошибка",
           any("degrade" in x for x in check({**ex, "hard": True, "on_exhaustion": "degrade"})))
    expect("hard=false + degrade -> валиден",
           check({**ex, "hard": False, "on_exhaustion": "degrade"}) == [])
    expect("scope=loop с не-LP ref -> ошибка",
           any("LP-NNN" in x for x in check({**ex, "scope": "loop", "scope_ref": "loop1"})))
    expect("scope=work_graph требует WG-NNN",
           any("WG-NNN" in x for x in check({**ex, "scope": "work_graph", "scope_ref": "x"})))
    expect("пустой enforced_by -> ошибка (экономика должна быть enforced)",
           any("enforced_by" in x for x in check({**ex, "enforced_by": " "})))
    expect("битый id -> ошибка", any("id" in x for x in check({**ex, "id": "BUD1"})))
    expect("enum on_exhaustion == схема",
           set(json.loads(SCHEMA.read_text(encoding="utf-8"))["properties"]["on_exhaustion"]["enum"]) == ON_EXH)

    assert ok, "перенесённый селфтест validate_budget_contract: см. строки FAIL в выводе"
