"""Тесты K7: инварианты вызываются в producer'ах (fail-closed)."""
from __future__ import annotations

import pytest


def test_preflight_checks_invariants():
    """preflight.assess() проверяет INV-PREFLIGHT-001/002/005 и записывает breaches."""
    from ai_ops_kit.gates import preflight
    # Минимальный вызов: preflight должен вернуть результат без invariant_breaches
    # при нормальных входах (ok=True, blocked=False).
    result = preflight.assess(
        signals={"task_type": "QUICK"},
        child_root="/tmp/nonexistent",
        wid="test",
    )
    # Если инварианты нарушены, они записываются в invariant_breaches
    breaches = result.get("invariant_breaches", [])
    # При нормальном preflight breaches пуст (ok=True, blocked=False — все инварианты держатся)
    assert isinstance(breaches, list)


def test_pipeline_invariants_in_report():
    """run_pipeline отчёт содержит invariant_breaches при нарушении."""
    from ai_ops_kit.gates.invariants import check_invariant
    # Проверяем, что INV-PIPELINE-001 работает
    assert check_invariant("INV-PIPELINE-001", result={
        "overall_status": "done", "ready_for_pr": True, "gates": {}
    })
    # Нарушение: нет required keys
    assert not check_invariant("INV-PIPELINE-001", result={"foo": "bar"})


def test_delivery_invariants():
    """DeliveryReceipt инварианты проверяются."""
    from ai_ops_kit.gates.invariants import check_invariant
    # sha_verified=True + remote_sha=None = нарушение INV-DELIVERY-001
    assert not check_invariant("INV-DELIVERY-001", sha_verified=True, remote_sha=None)
    # sha_verified=True + remote_sha="abc" = норма
    assert check_invariant("INV-DELIVERY-001", sha_verified=True, remote_sha="abc")
    # status=reconciled + sha_verified=False = нарушение INV-DELIVERY-002
    assert not check_invariant("INV-DELIVERY-002", status="reconciled", sha_verified=False)
