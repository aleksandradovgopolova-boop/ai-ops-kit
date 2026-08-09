"""Селфтест session_boundary, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from session_boundary import (  # noqa: F401 — имена, которые использует тело
    CLASSES,
    check,
    classify,
    to_relation,
)


@pytest.mark.slow
def test_session_boundary_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    c, _ = classify(current_workitem="WI-143", new_workitem="WI-143", new_task="ещё правка")
    expect("тот же id -> same_task", c == "same_task")
    c, _ = classify(current_workitem="WI-143", new_task="дожми canary для WI-143")
    expect("маркер продолжения без нового id -> continuation", c == "continuation")
    c, _ = classify(current_workitem="WI-143", new_task="добавить environment discovery", scope_overlap=True)
    expect("пересечение scope, иной фокус -> adjacent_subtask", c == "adjacent_subtask")
    c, _ = classify(current_workitem="WI-143", new_task="добавить совершенно другую фичу")
    expect("нет признаков -> new_independent_task (безопасно для гигиены)", c == "new_independent_task")
    c, _ = classify(current_workitem="WI-143", new_task="что угодно", repo_changed=True)
    expect("сменился репозиторий -> new_product", c == "new_product")
    c, _ = classify(current_workitem=None, new_task="первая задача")
    expect("нет текущего WI -> new_independent_task", c == "new_independent_task")
    expect("continues=False подавляет лексический маркер",
           classify(current_workitem="WI-1", new_task="продолжаем", continues=False)[0] == "new_independent_task")
    expect("все классы валидны", all(check(x) == [] for x in CLASSES))
    expect("to_relation тождественно", to_relation("same_task") == "same_task")

    assert ok, "перенесённый селфтест session_boundary: см. строки FAIL в выводе"
