"""Селфтест promotion_qual, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from promotion_qual import (  # noqa: F401 — имена, которые использует тело
    execute,
    load_plan,
    preflight,
    runbook,
    verify_negatives,
)


@pytest.mark.slow
def test_promotion_qual_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    plan = load_plan()
    expect("реальный план грузится и валиден", plan["plan_id"] == "PQP-001")

    neg = verify_negatives(plan)
    expect(f"ВСЕ негативы доказаны оффлайн ({neg['proven']}/{neg['total']})",
           neg["proven"] == neg["total"] and neg["total"] == 10)
    for r in neg["results"]:
        if not r["proven"]:
            print("   НЕ доказан:", r["covers"], "-", r["detail"])

    pf = preflight(plan)
    expect("preflight возвращает checks по всем 4 требованиям среды",
           set(pf["checks"]) == {"provider_key", "git", "node_react", "scratch_repo"})
    expect("preflight per_run по каждому прогону", set(pf["per_run"]) ==
           {r["id"] for r in plan["runs"]})

    rb = runbook(plan)
    expect("runbook покрывает все 3 прогона с командами",
           len(rb) == 3 and all(r["commands"] for r in rb))

    # execute без ключа/среды -> blocked ИЛИ dry-run, НО никогда не 'passed'
    ex = execute(plan, dry_run=False)
    expect("execute без готовности -> status blocked (не фейковый pass)",
           ex["status"] in ("blocked", "ready") and "passed" not in ex["status"])
    exd = execute(plan, dry_run=True)
    expect("execute dry-run -> живые прогоны не засчитаны", exd["status"] == "dry-run")

    assert ok, "перенесённый селфтест promotion_qual: см. строки FAIL в выводе"
