"""Селфтест validate_qualification, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_qualification import (  # noqa: F401 — имена, которые использует тело
    PKG,
    check,
    yaml,
)


@pytest.mark.slow
def test_validate_qualification_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    wf = {"QUICK", "ENGINEERING", "PRODUCT"}
    good = {"kind": "qualification-scenarios",
            "scenarios": [{"id": "s1", "title": "t", "task": "do", "task_type": "QUICK",
                           "acceptance": ["a"], "proves": "p", "flags": ["--sandbox"]}],
            "os_stack_matrix": {"os": ["macOS"], "stacks": ["node"]}}
    expect("валидный пакет -> без ошибок", check(good, wf) == [])
    bad_tt = {"kind": "qualification-scenarios",
              "scenarios": [{"id": "s1", "title": "t", "task": "d", "task_type": "NOPE",
                             "acceptance": ["a"], "proves": "p"}],
              "os_stack_matrix": {"os": ["macOS"], "stacks": ["node"]}}
    expect("неизвестный task_type -> ошибка", any("NOPE" in e for e in check(bad_tt, wf)))
    bad_flag = {"kind": "qualification-scenarios",
                "scenarios": [{"id": "s1", "title": "t", "task": "d", "task_type": "QUICK",
                               "acceptance": ["a"], "proves": "p", "flags": ["--ghost"]}],
                "os_stack_matrix": {"os": ["macOS"], "stacks": ["node"]}}
    expect("неизвестный флаг -> ошибка", any("--ghost" in e for e in check(bad_flag, wf)))
    expect("нет обязательного поля -> ошибка",
           any("proves" in e for e in check(
               {"kind": "qualification-scenarios",
                "scenarios": [{"id": "s1", "title": "t", "task": "d", "task_type": "QUICK",
                               "acceptance": ["a"]}],
                "os_stack_matrix": {"os": ["m"], "stacks": ["n"]}}, wf)))
    expect("нет матрицы -> ошибка",
           any("os_stack_matrix" in e for e in check(
               {"kind": "qualification-scenarios",
                "scenarios": [{"id": "s1", "title": "t", "task": "d", "task_type": "QUICK",
                               "acceptance": ["a"], "proves": "p"}]}, wf)))
    # реальный поставляемый пакет проходит
    real = PKG / "qualification" / "scenarios.yaml"
    if real.exists():
        expect("поставляемый qualification/scenarios.yaml валиден",
               check(yaml.safe_load(real.read_text(encoding="utf-8"))) == [])

    assert ok, "перенесённый селфтест validate_qualification: см. строки FAIL в выводе"
