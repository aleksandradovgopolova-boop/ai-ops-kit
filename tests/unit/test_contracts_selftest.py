"""Селфтест contracts, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from contracts import (  # noqa: F401 — имена, которые использует тело
    ContextBundle,
    DeliveryIntent,
    DeliveryReceipt,
    GateResultV2,
    PreflightResult,
    RunReport,
    UsageRecord,
    WorkItemState,
)


@pytest.mark.slow
def test_contracts_selftest():
    """Проверка контрактов: все TypedDicts импортируемы, аннотации непусты, runtime = dict."""
    ok = True

    def expect(label: str, cond: bool):
        nonlocal ok
        if not cond:
            print(f"  FAIL: {label}")
            ok = False

    # Все TypedDicts — это dict на runtime (обратно совместимо)
    for cls in (UsageRecord, PreflightResult, GateResultV2, RunReport,
                DeliveryIntent, DeliveryReceipt, ContextBundle, WorkItemState):
        expect(f"{cls.__name__} is dict subclass", issubclass(cls, dict))
        expect(f"{cls.__name__} has annotations", len(cls.__annotations__) > 0)

    # UsageRecord: ключевые поля
    expect("UsageRecord has usage_status", "usage_status" in UsageRecord.__annotations__)
    expect("UsageRecord has input_tokens", "input_tokens" in UsageRecord.__annotations__)
    expect("UsageRecord has cost", "cost" in UsageRecord.__annotations__)

    # PreflightResult: обязательные поля
    expect("PreflightResult has ok", "ok" in PreflightResult.__annotations__)
    expect("PreflightResult has blocked", "blocked" in PreflightResult.__annotations__)
    expect("PreflightResult has checks", "checks" in PreflightResult.__annotations__)
    expect("PreflightResult has reasons", "reasons" in PreflightResult.__annotations__)

    # GateResultV2: v2-статусы
    expect("GateResultV2 has status", "status" in GateResultV2.__annotations__)
    expect("GateResultV2 has schema_version", "schema_version" in GateResultV2.__annotations__)

    # RunReport: delivery-ключи
    expect("RunReport has ready_for_pr", "ready_for_pr" in RunReport.__annotations__)
    expect("RunReport has overall_status", "overall_status" in RunReport.__annotations__)
    expect("RunReport has gates", "gates" in RunReport.__annotations__)

    # DeliveryReceipt: sha_verified
    expect("DeliveryReceipt has sha_verified", "sha_verified" in DeliveryReceipt.__annotations__)

    # Интеграция: preflight.assess возвращает PreflightResult-совместимый dict
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    import preflight
    pf = preflight.assess({"task_type": "QUICK"}, "/tmp/nonexistent", "test-wid")
    expect("preflight.assess returns dict", isinstance(pf, dict))
    expect("preflight.assess has ok", "ok" in pf)
    expect("preflight.assess has blocked", "blocked" in pf)
    expect("preflight.assess has checks", "checks" in pf)
    expect("preflight.assess has reasons", "reasons" in pf)

    assert ok, "перенесённый селфтест contracts: см. строки FAIL в выводе"
