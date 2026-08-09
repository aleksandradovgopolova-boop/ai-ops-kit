"""Селфтест model_comparison, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from model_comparison import (  # noqa: F401 — имена, которые использует тело
    DEMO,
    SCHEMA,
    _load_dir,
    check,
    compare,
    json,
)


@pytest.mark.slow
def test_model_comparison_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    ex = json.loads(SCHEMA.read_text(encoding="utf-8"))["examples"][0]
    expect("пример MBR из схемы валиден", check(ex) == [])
    expect("pass>total -> ошибка",
           any("pass > total" in x for x in check({**ex,
               "quality": {"total": 1, "pass": 2, "false_green": 0, "false_fail": 0, "fix_recovered": 0}})))

    def _mbr(model, tier, total, passed, fg, ff, cost):
        return {"kind": "ModelBenchResult", "model": model, "provider": "p", "task_tier": tier,
                "quality": {"total": total, "pass": passed, "false_green": fg, "false_fail": ff,
                            "fix_recovered": 0},
                "economics": {"tokens": None, "cost_usd": cost, "latency_s": None}}

    # ENGINEERING: strong (sonnet-ish) safe, weak (deepseek) safe, cheap-but-unsafe
    res = [
        _mbr("strong", "ENGINEERING", 10, 9, 0, 1, 0.50),
        _mbr("weak", "ENGINEERING", 10, 3, 0, 0, 0.02),
        _mbr("unsafe-cheap", "ENGINEERING", 10, 10, 2, 0, 0.001),
    ]
    cmp = compare(res)
    eng = cmp["tiers"]["ENGINEERING"]
    expect("unsafe (false_green>0) ДИСКВАЛИФИЦИРОВАН несмотря на дешевизну/качество",
           any(d["model"] == "unsafe-cheap" for d in eng["disqualified"])
           and all(r["model"] != "unsafe-cheap" for r in eng["ranked"]))
    expect("ENGINEERING: рекомендован strong (высокий pass-rate среди безопасных)",
           eng["recommended"] == "strong")
    expect("weak безопасен и в ранжировании (ниже strong)",
           [r["model"] for r in eng["ranked"]] == ["strong", "weak"])

    # QUICK: weak дешёвый и adequate -> может рекомендоваться
    res_q = [_mbr("strong", "QUICK", 5, 5, 0, 0, 0.30), _mbr("weak", "QUICK", 5, 5, 0, 0, 0.01)]
    q = compare(res_q)["tiers"]["QUICK"]
    expect("QUICK: при равном качестве рекомендован более дешёвый (weak)", q["recommended"] == "weak")

    # все дисквалифицированы -> нет рекомендации
    allbad = compare([_mbr("a", "UI", 5, 5, 1, 0, 0.1)])["tiers"]["UI"]
    expect("все небезопасны -> recommended=None (fail-closed)", allbad["recommended"] is None)

    # реальный демо-набор валиден
    real = _load_dir(DEMO)
    expect(f"реальные MBR в examples/model-comparison-demo валидны ({len(real)})",
           all(check(r) == [] for r in real) and len(real) >= 1)

    assert ok, "перенесённый селфтест model_comparison: см. строки FAIL в выводе"
