"""Селфтест validate_promotion_qualification, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_promotion_qualification import (  # noqa: F401 — имена, которые использует тело
    DEFAULT_PLAN,
    _good_plan,
    check,
    yaml,
)


@pytest.mark.slow
def test_validate_promotion_qualification_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    expect("валидный план проходит", check(_good_plan()) == [])
    expect("promotion_sequence не shadow->hybrid->default -> ошибка",
           any("promotion_sequence" in x for x in
               check({**_good_plan(), "promotion_sequence": [{"stage": "default", "description": "d", "gate": "g"}]})))
    bad_run = _good_plan()
    bad_run["runs"][0]["exact_sha_bound"] = False
    expect("run без exact_sha_bound -> ошибка", any("exact_sha_bound" in x for x in check(bad_run)))
    phantom = _good_plan()
    phantom["runs"][0]["uses"] = ["does_not_exist_9x.py"]
    expect("uses на несуществующий инструмент -> ошибка (честность)",
           any("несуществующ" in x for x in check(phantom)))
    miss_neg = _good_plan()
    miss_neg["negative_scenarios"] = miss_neg["negative_scenarios"][:-1]
    expect("неполный набор негативов -> ошибка", any("негатив" in x for x in check(miss_neg)))
    miss_crit = _good_plan()
    miss_crit["exit_criteria"] = miss_crit["exit_criteria"][:-1]
    expect("неполный набор exit-критериев -> ошибка", any("критери" in x for x in check(miss_crit)))
    no_kind = _good_plan()
    no_kind["runs"] = no_kind["runs"][:2]
    expect("runs не покрывают все три вида -> ошибка", any("обязательные виды" in x for x in check(no_kind)))
    expect("пустой blocked_by -> ошибка", any("blocked_by" in x for x in check({**_good_plan(), "blocked_by": []})))

    # реальный план на диске (если есть) — валиден
    if DEFAULT_PLAN.exists():
        data = yaml.safe_load(DEFAULT_PLAN.read_text(encoding="utf-8"))
        errs = check(data)
        expect(f"реальный {DEFAULT_PLAN.name} валиден", errs == [])
        if errs:
            for x in errs:
                print("   -", x)

    assert ok, "перенесённый селфтест validate_promotion_qualification: см. строки FAIL в выводе"
