"""Селфтест evolution_triggers, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from evolution_triggers import (  # noqa: F401 — имена, которые использует тело
    reg,
    triggers,
)


@pytest.mark.slow
def test_evolution_triggers_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    def _adr(aid, qas):
        return {"id": aid, "status": "accepted", "quality_attributes": qas}

    adrs = {
        "ADR-A": _adr("ADR-A", [{"attribute": "reliability", "effect": "improves"}]),
        "ADR-B": _adr("ADR-B", [{"attribute": "performance", "effect": "tradeoff"}]),
        "ADR-OLD": {"id": "ADR-OLD", "status": "superseded",
                    "quality_attributes": [{"attribute": "reliability", "effect": "improves"}]},
    }

    def _hr(metrics, band="warning"):
        return {"scope": "s", "period": "p", "health_score": {"band": band},
                "metrics": {k: {"normalized": v} for k, v in metrics.items()}}

    # reliability деградирует, ADR-A обещал improve -> promise_broken на ADR-A
    t = triggers(adrs, _hr({"reliability": 0.5, "performance": 0.9}))
    expect("promise_broken при деградации обещанного improve",
           any(x["kind"] == "promise_broken" and x["adrs"] == ["ADR-A"] for x in t))
    expect("нет cost_realized когда performance здоров",
           not any(x["kind"] == "cost_realized" for x in t))

    # performance деградирует, ADR-B принимал tradeoff -> cost_realized на ADR-B
    t = triggers(adrs, _hr({"performance": 0.4}))
    expect("cost_realized при деградации tradeoff-атрибута",
           any(x["kind"] == "cost_realized" and x["adrs"] == ["ADR-B"] for x in t))

    # маппинг метрики errors -> атрибут reliability
    t = triggers(adrs, _hr({"errors": 0.3}))
    expect("метрика errors отображается на reliability -> promise_broken ADR-A",
           any(x["attribute"] == "reliability" and x["metric"] == "errors" for x in t))

    # здоровые метрики -> нет триггеров
    expect("всё здорово -> нет триггеров",
           triggers(adrs, _hr({"reliability": 0.95, "performance": 0.9}, band="healthy")) == [])

    # superseded ADR не порождает триггеров (только активные)
    t = triggers({"ADR-OLD": adrs["ADR-OLD"]}, _hr({"reliability": 0.2}))
    expect("superseded ADR не порождает evolution-триггеров", t == [])

    # интеграция с РЕАЛЬНЫМ реестром + здоровым демо-health -> петля замыкается без триггеров
    real_errs, real_adrs = reg.check_registry(reg.DEFAULT_DIR)
    expect("реальный ADR-реестр целостен (предусловие)", real_errs == [])
    healthy = _hr({"reliability": 0.95, "performance": 0.95, "errors": 0.95}, band="healthy")
    expect("реальные ADR + здоровый health -> 0 триггеров (петля замыкается чисто)",
           triggers(real_adrs, healthy) == [])
    # а при деградации reliability реальные ADR-002/003 (improve reliability) дают promise_broken
    degraded = _hr({"reliability": 0.4}, band="critical")
    rt = triggers(real_adrs, degraded)
    expect("деградация reliability -> promise_broken на реальных ADR (002/003 обещали improve)",
           any(x["kind"] == "promise_broken" and "ADR-002" in x["adrs"] for x in rt))

    assert ok, "перенесённый селфтест evolution_triggers: см. строки FAIL в выводе"
