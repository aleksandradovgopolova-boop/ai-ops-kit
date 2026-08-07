"""Селфтест validate_bootstrap_qualification, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_bootstrap_qualification import (  # noqa: F401 — имена, которые использует тело
    DEFAULT_PLAN,
    check,
    yaml,
)


@pytest.mark.slow
def test_validate_bootstrap_qualification_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    if DEFAULT_PLAN.exists():
        errs = check(yaml.safe_load(DEFAULT_PLAN.read_text(encoding="utf-8")))
        expect("реальный v3.8.0-plan валиден", errs == [])
        for x in errs:
            print("   -", x)
        base = yaml.safe_load(DEFAULT_PLAN.read_text(encoding="utf-8"))
    else:
        expect("v3.8.0-plan существует", False); return 1

    # негативы: срезанная стадия / сценарий / критерий / фантомный builds_over / нет greenfield
    import copy
    d1 = copy.deepcopy(base); d1["bootstrap_stages"] = [s for s in d1["bootstrap_stages"] if s["id"] != "vertical_feature"]
    expect("нет vertical_feature -> ошибка", any("bootstrap_stages" in x for x in check(d1)))
    d2 = copy.deepcopy(base); d2["readiness_scenarios"] = [s for s in d2["readiness_scenarios"] if s["id"] != "provider_fallback"]
    expect("нет provider_fallback сценария -> ошибка", any("readiness_scenarios" in x for x in check(d2)))
    d3 = copy.deepcopy(base); d3["exit_criteria"] = [c for c in d3["exit_criteria"] if c != "zero_false_green"]
    expect("нет zero_false_green в exit -> ошибка", any("exit_criteria" in x for x in check(d3)))
    d4 = copy.deepcopy(base); d4["builds_over"] = [{"name": "Ghost", "ref": "tools/ghost_subsystem.py"}]
    expect("фантомный builds_over ref -> ошибка (не новая подсистема)", any("не существует" in x for x in check(d4)))
    d5 = copy.deepcopy(base); d5["reference_children"] = [c for c in d5["reference_children"] if c.get("kind") != "greenfield"]
    expect("нет greenfield child -> ошибка", any("greenfield" in x for x in check(d5)))
    d6 = copy.deepcopy(base); d6["models"] = {"security_integration_judge": "kimi"}
    expect("автосудья security до Bench v2 -> ошибка (нужен human)", any("security_integration_judge" in x for x in check(d6)))

    assert ok, "перенесённый селфтест validate_bootstrap_qualification: см. строки FAIL в выводе"
