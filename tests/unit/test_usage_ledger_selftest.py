"""Селфтест usage_ledger, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from usage_ledger import (  # noqa: F401 — имена, которые использует тело
    aggregate,
    append,
    check,
    load_product,
    load_task,
)


@pytest.mark.slow
def test_usage_ledger_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    good = {"run_id": "r1", "workitem_id": "w1", "role": "implementation", "provider": "claude-cli",
            "model": "claude-code-local", "input_tokens": 100, "output_tokens": 50,
            "usage_status": "measured", "cost": 0.07, "cost_status": "measured", "trigger": "initial"}
    expect("валидная measured-запись -> без ошибок", check(good) == [])
    expect("unavailable с токенами -> ошибка (неизвестное != 0)",
           any("unavailable" in x for x in check({**good, "usage_status": "unavailable"})))
    expect("unavailable с None-токенами -> ok",
           check({**good, "usage_status": "unavailable", "input_tokens": None, "output_tokens": None,
                  "cost": None, "cost_status": "unavailable"}) == [])
    expect("measured без токенов -> ошибка",
           any("нечего измерять" in x for x in check({**good, "input_tokens": None, "output_tokens": None})))
    expect("input_tokens=0 при measured -> валиден (0 измерено — не то же, что неизвестно)",
           check({**good, "input_tokens": 0, "output_tokens": 1}) == [])
    expect("неизвестный trigger -> ошибка", any("trigger" in x for x in check({**good, "trigger": "bogus"})))

    # агрегат честный: unavailable не топит суммы и помечает cost неполной
    recs = [good,
            {**good, "role": "code_review", "provider": "deepseek", "trigger": "review", "cost": 0.001,
             "cost_status": "estimated"},
            {"usage_status": "unavailable", "input_tokens": None, "output_tokens": None, "cost": None,
             "cost_status": "unavailable", "role": "implementation", "provider": "kimi", "trigger": "escalation"}]
    a = aggregate(recs)
    expect("агрегат: 3 вызова, 2 measured + 1 unavailable",
           a["calls"] == 3 and a["usage_measured"] == 2 and a["usage_unavailable"] == 1)
    expect("агрегат: токены только по measured (200/100)",
           a["input_tokens"] == 200 and a["output_tokens"] == 100)
    expect("агрегат: cost неполон (есть unavailable-стоимость)", a["cost_complete"] is False)
    expect("агрегат: by_role/by_trigger разложены",
           a["by_role"]["implementation"] == 2 and a["by_trigger"]["review"] == 1)

    # round-trip append/load/aggregate
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        n = append(td, "w1", recs, run_id="r1")
        expect("append записал 3", n == 3)
        expect("load_task читает 3", len(load_task(td, "w1")) == 3)
        expect("load_product читает 3 (агрегат по продукту)", len(load_product(td)) == 3)
        expect("нормализация влила run_id/workitem_id", load_task(td, "w1")[0].get("run_id") == "r1")

    assert ok, "перенесённый селфтест usage_ledger: см. строки FAIL в выводе"
