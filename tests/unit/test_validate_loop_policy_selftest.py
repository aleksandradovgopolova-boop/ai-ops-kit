"""Селфтест validate_loop_policy, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_loop_policy import (  # noqa: F401 — имена, которые использует тело
    LOOP_TYPES,
    SCHEMA,
    check,
    json,
)


@pytest.mark.slow
def test_validate_loop_policy_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    ex = json.loads(SCHEMA.read_text(encoding="utf-8"))["examples"][0]
    expect("пример из схемы валиден", check(ex) == [])
    expect("unbounded budgets -> ошибка",
           any("unbounded" in x for x in check({**ex,
               "budgets": {"max_iterations": None, "max_tokens": None, "max_cost_usd": None}})))
    expect("пустые stop_conditions -> ошибка",
           any("stop_conditions" in x for x in check({**ex, "stop_conditions": []})))
    expect("stop_conditions без исчерпания бюджета -> ошибка",
           any("исчерпание бюджета" in x for x in check({**ex, "stop_conditions": ["всё готово"]})))
    expect("пустой progress_measure -> ошибка",
           any("progress_measure" in x for x in check({**ex, "progress_measure": " "})))
    expect("неизвестный loop_type -> ошибка",
           any("loop_type" in x for x in check({**ex, "loop_type": "magic"})))
    expect("битый id -> ошибка", any("id" in x for x in check({**ex, "id": "LP1"})))
    expect("budget только по токенам -> валиден",
           check({**ex, "budgets": {"max_iterations": None, "max_tokens": 100000, "max_cost_usd": None}}) == [])
    expect("enum loop_type == схема",
           set(json.loads(SCHEMA.read_text(encoding="utf-8"))["properties"]["loop_type"]["enum"]) == LOOP_TYPES)

    assert ok, "перенесённый селфтест validate_loop_policy: см. строки FAIL в выводе"
