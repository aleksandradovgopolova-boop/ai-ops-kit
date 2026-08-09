"""Селфтест validate_scenario_evidence, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_scenario_evidence import (  # noqa: F401 — имена, которые использует тело
    check,
)


@pytest.mark.slow
def test_validate_scenario_evidence_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    good = {"status": "pass", "named_user_scenario": "владелец видит правку коллеги над общим объектом",
            "scenario_test": "tests/e2e/shared_object.py::test_two_users_one_object"}
    expect("ENGINEERING + named scenario + scenario_test -> без advisory", check(good, "ENGINEERING") == [])
    # проверка, что гейт СРАБАТЫВАЕТ (Оговорка дока: гейт, который не падал, неотличим от отсутствующего)
    empty = {"status": "pass", "provided": ["build_passed", "tests_passed", "tested_revision"]}
    fires = check(empty, "ENGINEERING")
    expect("ENGINEERING без сценария/теста -> advisory СРАБАТЫВАЕТ (2 находки)", len(fires) == 2)
    expect("PRODUCT без сценария -> тоже срабатывает", len(check(empty, "PRODUCT")) == 2)
    expect("CRITICAL: только scenario, нет теста -> одна находка",
           len(check({"named_user_scenario": "s"}, "CRITICAL")) == 1)
    expect("scenario_test не похож на тест -> находка",
           any("не похож" in f for f in check({"named_user_scenario": "s", "scenario_test": "just words"}, "ENGINEERING")))
    # неприменимость: QUICK/VISUAL не требуют сценарного evidence -> тихо
    expect("QUICK -> неприменимо, тихо (нет ложного шума)", check(empty, "QUICK") == [])
    expect("VISUAL -> неприменимо, тихо", check(empty, "VISUAL") == [])
    expect("evidence не словарь при ENGINEERING -> честная находка", check(None, "ENGINEERING") != [])

    assert ok, "перенесённый селфтест validate_scenario_evidence: см. строки FAIL в выводе"
