"""Селфтест invariants, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from invariants import (  # noqa: F401 — имена, которые использует тело
    ALL_INVARIANTS,
    check_invariant,
)


@pytest.mark.slow
def test_invariants_selftest():
    """Verify all invariants are well-formed and pass basic sanity checks."""
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"  {'PASS' if cond else 'FAIL'} {name}")

    # Structural: every invariant has required fields
    expect(f"ALL_INVARIANTS is non-empty ({len(ALL_INVARIANTS)} invariants)", len(ALL_INVARIANTS) > 0)
    for inv in ALL_INVARIANTS:
        has_fields = all(k in inv for k in ("id", "description", "severity", "check"))
        expect(f"{inv.get('id', '?')} has required fields", has_fields)
        expect(f"{inv.get('id', '?')} severity is critical or warning",
               inv.get("severity") in ("critical", "warning"))
        expect(f"{inv.get('id', '?')} check is callable", callable(inv.get("check")))

    # Uniqueness of IDs
    ids = [inv["id"] for inv in ALL_INVARIANTS]
    expect("All invariant IDs are unique", len(ids) == len(set(ids)))

    # Sanity checks for each category
    # Preflight
    expect("INV-PREFLIGHT-001: blocked=True, reasons=[] → FAIL",
           not check_invariant("INV-PREFLIGHT-001", blocked=True, reasons=[]))
    expect("INV-PREFLIGHT-001: blocked=True, reasons=['x'] → PASS",
           check_invariant("INV-PREFLIGHT-001", blocked=True, reasons=["x"]))
    expect("INV-PREFLIGHT-001: blocked=False, reasons=[] → PASS",
           check_invariant("INV-PREFLIGHT-001", blocked=False, reasons=[]))

    expect("INV-PREFLIGHT-002: ok=False, blocked=False → FAIL",
           not check_invariant("INV-PREFLIGHT-002", ok=False, blocked=False))
    expect("INV-PREFLIGHT-002: ok=False, blocked=True → PASS",
           check_invariant("INV-PREFLIGHT-002", ok=False, blocked=True))

    expect("INV-PREFLIGHT-005: checks={} → FAIL",
           not check_invariant("INV-PREFLIGHT-005", checks={}))
    expect("INV-PREFLIGHT-005: checks={'classification': {}} → PASS",
           check_invariant("INV-PREFLIGHT-005", checks={"classification": {}}))

    # Pipeline
    expect("INV-PIPELINE-001: missing keys → FAIL",
           not check_invariant("INV-PIPELINE-001", result={"overall_status": "done"}))
    expect("INV-PIPELINE-001: all keys → PASS",
           check_invariant("INV-PIPELINE-001",
                           result={"overall_status": "done", "ready_for_pr": True, "gates": {}}))

    expect("INV-PIPELINE-002: ready_for_pr=True, status='error' → FAIL",
           not check_invariant("INV-PIPELINE-002", ready_for_pr=True, overall_status="error"))
    expect("INV-PIPELINE-002: ready_for_pr=True, status='delivered' → PASS",
           check_invariant("INV-PIPELINE-002", ready_for_pr=True, overall_status="delivered"))

    expect("INV-PIPELINE-004: changed_files=None → FAIL",
           not check_invariant("INV-PIPELINE-004", changed_files=None))
    expect("INV-PIPELINE-004: changed_files=[] → PASS",
           check_invariant("INV-PIPELINE-004", changed_files=[]))

    # Delivery
    expect("INV-DELIVERY-001: sha_verified=True, remote_sha=None → FAIL",
           not check_invariant("INV-DELIVERY-001", sha_verified=True, remote_sha=None))
    expect("INV-DELIVERY-001: sha_verified=True, remote_sha='abc' → PASS",
           check_invariant("INV-DELIVERY-001", sha_verified=True, remote_sha="abc"))

    expect("INV-DELIVERY-002: status='reconciled', sha_verified=False → FAIL",
           not check_invariant("INV-DELIVERY-002", status="reconciled", sha_verified=False))

    expect("INV-DELIVERY-003: commit_sha=None → FAIL",
           not check_invariant("INV-DELIVERY-003", commit_sha=None, branch="main"))

    # Usage
    expect("INV-USAGE-001: unavailable, tokens=(1,2) → FAIL",
           not check_invariant("INV-USAGE-001", usage_status="unavailable",
                               input_tokens=1, output_tokens=2))
    expect("INV-USAGE-001: unavailable, tokens=(None,None) → PASS",
           check_invariant("INV-USAGE-001", usage_status="unavailable",
                           input_tokens=None, output_tokens=None))

    expect("INV-USAGE-002: measured, tokens=(None,None) → FAIL",
           not check_invariant("INV-USAGE-002", usage_status="measured",
                               input_tokens=None, output_tokens=None))

    expect("INV-USAGE-004: cost=-1.0 → FAIL",
           not check_invariant("INV-USAGE-004", cost=-1.0))
    expect("INV-USAGE-004: cost=None → PASS",
           check_invariant("INV-USAGE-004", cost=None))

    # Budget
    expect("INV-BUDGET-001: calls=5, max=3 → FAIL",
           not check_invariant("INV-BUDGET-001", model_calls=5, max_model_calls=3))
    expect("INV-BUDGET-001: calls=2, max=3 → PASS",
           check_invariant("INV-BUDGET-001", model_calls=2, max_model_calls=3))

    expect("INV-BUDGET-002: remaining=1, max=3, calls=2 → PASS",
           check_invariant("INV-BUDGET-002", remaining_calls=1, max_model_calls=3, model_calls=2))

    print(f"\ninvariants selftest: {'PASS' if ok else 'FAIL'}")
    assert ok, "перенесённый селфтест invariants: см. строки FAIL в выводе"
