"""Селфтест validate_agent_evals, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_agent_evals import (  # noqa: F401 — имена, которые использует тело
    check,
    eval_structure_errors,
)


@pytest.mark.slow
def test_validate_agent_evals_selftest():
    ok = True

    def expect(name, got, want):
        nonlocal ok
        status = "PASS" if got == want else "FAIL"
        ok = ok and (got == want)
        print(f"{status} {name}")

    # 1. изменённый агент без eval-кейсов -> ошибка
    errs = check(["agents/core/task-planner.md"], evals_present=set())
    expect("изменённый агент без eval -> fail", len(errs), 1)
    # 2. изменённый агент с eval-кейсами -> чисто
    errs = check(["agents/core/task-planner.md"], evals_present={"task-planner"})
    expect("изменённый агент с eval -> pass", len(errs), 0)
    # 3. изменения вне agents/ и README не требуют eval
    errs = check(["registry/agents.yaml", "agents/README.md", "workflows/release.md"],
                 evals_present=set())
    expect("не-агентные изменения -> pass", len(errs), 0)
    # 4. структура: реальный eval-файл валиден; выдуманный «пустой» — нет
    expect("структура существующего eval валидна",
           eval_structure_errors("code-reviewer"), [])
    expect("структура отсутствующего eval -> ошибка",
           len(eval_structure_errors("__nope__")) >= 1, True)

    assert ok, "перенесённый селфтест validate_agent_evals: см. строки FAIL в выводе"
