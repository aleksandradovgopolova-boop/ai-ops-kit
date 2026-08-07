"""Селфтест product_health, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from product_health import (  # noqa: F401 — имена, которые использует тело
    compute,
)


@pytest.mark.slow
def test_product_health_selftest():
    ok = True

    def expect(name, got, want):
        nonlocal ok
        good = got == want
        ok = ok and good
        print(f"{'PASS' if good else 'FAIL'} {name}" + ("" if good else f" (got {got})"))

    r = compute({"scope": "feature:x", "period": "2026-W30", "metrics": {
        "adoption": {"value": 0.5, "target": 0.5},
        "errors": {"value": 0.5, "target": 1.0, "direction": "lower-is-better"},
    }})
    expect("идеальные метрики -> score 100", r["health_score"]["value"], 100.0)
    expect("band healthy", r["health_score"]["band"], "healthy")

    r = compute({"metrics": {
        "adoption": {"value": 0.1, "target": 0.5},
        "errors": {"value": 4.0, "target": 1.0, "direction": "lower-is-better"},
    }})
    expect("плохие метрики -> band critical", r["health_score"]["band"], "critical")
    expect("оба findings", len(r["findings"]), 2)

    r = compute({"metrics": {
        "adoption": {"value": 0.25, "target": 0.5},     # 0.5
        "reliability": {"value": 1.0, "target": 1.0},   # 1.0
    }, "weights": {"adoption": 3, "reliability": 1}})
    expect("веса учитываются (0.5*3+1*1)/4=62.5", r["health_score"]["value"], 62.5)
    expect("band warning", r["health_score"]["band"], "warning")

    assert ok, "перенесённый селфтест product_health: см. строки FAIL в выводе"
