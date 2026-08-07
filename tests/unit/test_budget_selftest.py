"""Селфтест budget, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from budget import (  # noqa: F401 — имена, которые использует тело
    Budget,
    BudgetExceeded,
)


@pytest.mark.slow
def test_budget_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    b = Budget(max_model_calls=2)
    b.charge_call(); b.charge_call()
    expect("два вызова в пределах бюджета", b.model_calls == 2)
    try:
        b.charge_call(); raised = False
    except BudgetExceeded:
        raised = True
    expect("третий вызов -> BudgetExceeded", raised)
    expect("потолок не превышен (осталось 0, calls=2)", b.remaining_calls() == 0 and b.model_calls == 2)

    unb = Budget()
    for _ in range(100):
        unb.charge_call()
    expect("без лимита -> не блокирует", unb.model_calls == 100 and unb.remaining_calls() is None)

    cb = Budget(max_cost=1.0)
    cb.charge_call(cost=0.6)
    try:
        cb.charge_call(cost=0.6); raised = False
    except BudgetExceeded:
        raised = True
    expect("max_cost превышение -> BudgetExceeded (если cost учитывается)", raised)

    expect("from_dict читает RunPlan.execution_budget",
           Budget.from_dict({"max_model_calls": 5}).max_model_calls == 5)

    assert ok, "перенесённый селфтест budget: см. строки FAIL в выводе"
