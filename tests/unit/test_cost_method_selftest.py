"""Селфтест cost_method, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from cost_method import (  # noqa: F401 — имена, которые использует тело
    advise,
    check,
)


@pytest.mark.slow
def test_cost_method_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    # тяжёлый контекст -> гигиена приоритет 1 первой
    r = advise({"task_type": "ENGINEERING"}, snapshot={"context_current": 450_000})
    expect("тяжёлый контекст -> совет гигиены приоритета 1",
           r and r[0]["priority"] == 1 and r[0]["category"] == "session_hygiene")
    expect("порядок приоритетов неубывающий",
           all(r[i]["priority"] <= r[i + 1]["priority"] for i in range(len(r) - 1)))
    expect("check валиден", check(r) == [])

    # QUICK -> runtime дешёвый + low effort
    r = advise({"task_type": "QUICK"}, snapshot={"context_current": 50_000})
    cats = {x["category"]: x["advice"] for x in r}
    expect("QUICK -> дешёвый runtime", "runtime" in cats and "не нужен" in cats["runtime"])
    expect("QUICK -> low effort", "effort" in cats and "low effort" in cats["effort"])

    # много fix-итераций -> стоп fix-loop (приоритет 3)
    r = advise({"task_type": "ENGINEERING", "fix_attempts": 3}, snapshot={"context_current": 50_000})
    expect("3 fix-итерации -> совет остановить fix-loop",
           any(x["category"] == "iteration_limit" for x in r))

    # разведка 30 файлов -> делегирование (приоритет 2)
    r = advise({"task_type": "ENGINEERING", "exploration_files": 30}, snapshot={"context_current": 50_000})
    expect("30 файлов -> совет делегирования приоритета 2",
           any(x["category"] == "delegation" and x["priority"] == 2 for x in r))

    # неизвестный контекст -> совет передать /context
    r = advise({"task_type": "ENGINEERING"}, snapshot={"context_current": None})
    expect("контекст unknown -> совет передать --context",
           any("context" in x["advice"].lower() for x in r if x["category"] == "session_hygiene"))

    # малое изменение -> affected tests
    r = advise({"task_type": "ENGINEERING", "small_change": True}, snapshot={"context_current": 50_000})
    expect("малое изменение -> affected tests", any(x["category"] == "tests" for x in r))

    assert ok, "перенесённый селфтест cost_method: см. строки FAIL в выводе"
