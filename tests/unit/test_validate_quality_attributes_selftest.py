"""Селфтест validate_quality_attributes, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_quality_attributes import (  # noqa: F401 — имена, которые использует тело
    fitness,
    profile,
    reg,
)


@pytest.mark.slow
def test_validate_quality_attributes_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    # реальный реестр кита проходит fitness
    real_errs, real_adrs = reg.check_registry(reg.DEFAULT_DIR)
    expect("реальный ADR-реестр целостен (предусловие)", real_errs == [])
    expect(f"реальный реестр проходит quality-attributes fitness ({len(real_adrs)} ADR)",
           fitness(real_adrs) == [])
    expect("профиль непуст и покрывает реальные атрибуты",
           bool(profile(real_adrs)) and "maintainability" in profile(real_adrs))

    def _adr(aid, qas, status="accepted"):
        return {"id": aid, "status": status, "quality_attributes": qas}

    # degrades без note -> смелл
    e = fitness({"ADR-001": _adr("ADR-001", [{"attribute": "performance", "effect": "degrades"}])})
    expect("degrades без note -> смелл", any("без note" in x for x in e))
    # degrades с note -> ок
    e = fitness({"ADR-001": _adr("ADR-001",
                 [{"attribute": "performance", "effect": "degrades", "note": "кэш прогревается"}])})
    expect("degrades с note -> ок", e == [])
    # неуправляемое противоречие improves vs degrades без tradeoff
    e = fitness({
        "ADR-001": _adr("ADR-001", [{"attribute": "security", "effect": "improves"}]),
        "ADR-002": _adr("ADR-002", [{"attribute": "security", "effect": "degrades", "note": "x"}]),
    })
    expect("improves+degrades без tradeoff -> противоречие",
           any("противоречие" in x for x in e))
    # с tradeoff -> напряжение осознано, не смелл
    e = fitness({
        "ADR-001": _adr("ADR-001", [{"attribute": "security", "effect": "improves"}]),
        "ADR-002": _adr("ADR-002", [{"attribute": "security", "effect": "degrades", "note": "x"}]),
        "ADR-003": _adr("ADR-003", [{"attribute": "security", "effect": "tradeoff"}]),
    })
    expect("improves+degrades+tradeoff -> осознанно (не смелл)",
           not any("противоречие" in x for x in e))
    # superseded ADR не участвует в противоречии активных
    e = fitness({
        "ADR-001": _adr("ADR-001", [{"attribute": "cost", "effect": "improves"}]),
        "ADR-002": _adr("ADR-002", [{"attribute": "cost", "effect": "degrades", "note": "x"}],
                        status="superseded"),
    })
    expect("superseded ADR не создаёт противоречие среди активных", e == [])

    assert ok, "перенесённый селфтест validate_quality_attributes: см. строки FAIL в выводе"
