#!/usr/bin/env python3
"""invariants.py (v1.0.0) — Formal invariant catalog for the AI Ops Kit critical path.

Machine-checkable invariant specifications for: preflight, execution pipeline, delivery,
usage honesty, and budget. Each invariant has a unique ID, description, severity, and
a check function that returns True when the invariant HOLDS.

Usage:
    from invariants import check_invariant, ALL_INVARIANTS, selftest
    assert check_invariant("INV-PREFLIGHT-001", blocked=True, reasons=["spec missing"])
    selftest()

python3 tools/invariants.py --selftest
"""
from __future__ import annotations

import sys
from pathlib import Path

import _bootstrap  # noqa: E402
# ============================================================================
# Invariant registry
# ============================================================================

ALL_INVARIANTS: list[dict] = []


def _register(inv: dict) -> dict:
    ALL_INVARIANTS.append(inv)
    return inv


def check_invariant(invariant_id: str, **kwargs) -> bool:
    """Check a single invariant by ID. Returns True if the invariant holds."""
    for inv in ALL_INVARIANTS:
        if inv["id"] == invariant_id:
            return inv["check"](**kwargs)
    raise KeyError(f"Unknown invariant: {invariant_id}")


# ============================================================================
# Preflight Invariants
# ============================================================================

_register({
    "id": "INV-PREFLIGHT-001",
    "description": "If blocked=True, reasons must be non-empty",
    "severity": "critical",
    "check": lambda blocked, reasons, **kw: (not blocked) or (len(reasons) > 0),
})

_register({
    "id": "INV-PREFLIGHT-002",
    "description": "If ok=False, blocked must be True (no silent failures)",
    "severity": "critical",
    "check": lambda ok, blocked, **kw: ok or blocked,
})

_register({
    "id": "INV-PREFLIGHT-003",
    "description": "For ENGINEERING/PRODUCT/CRITICAL without spec artifact and not author mode, must be blocked",
    "severity": "critical",
    "check": lambda task_type, spec_artifact, author, blocked, **kw: (
        not (task_type in ("ENGINEERING", "PRODUCT", "CRITICAL") and not spec_artifact and not author)
    ) or blocked,
})

_register({
    "id": "INV-PREFLIGHT-004",
    "description": "reevaluate_only=True marks spec check with skipped_reevaluate flag",
    "severity": "warning",
    "check": lambda reevaluate_only, spec_check, **kw: (
        not reevaluate_only
    ) or (isinstance(spec_check, dict) and spec_check.get("skipped_reevaluate") is True),
})

_register({
    "id": "INV-PREFLIGHT-005",
    "description": "classification check always present in checks dict",
    "severity": "critical",
    "check": lambda checks, **kw: "classification" in checks,
})


# ============================================================================
# Execution Pipeline Invariants
# ============================================================================

_PIPELINE_REQUIRED_KEYS = {"overall_status", "ready_for_pr", "gates"}

_register({
    "id": "INV-PIPELINE-001",
    "description": "run_pipeline result always contains required keys (overall_status, ready_for_pr, gates)",
    "severity": "critical",
    "check": lambda result, **kw: isinstance(result, dict) and _PIPELINE_REQUIRED_KEYS.issubset(result.keys()),
})

_register({
    "id": "INV-PIPELINE-002",
    "description": "If ready_for_pr=True, overall_status must not be 'error'",
    "severity": "critical",
    "check": lambda ready_for_pr, overall_status, **kw: (
        not ready_for_pr
    ) or (overall_status != "error"),
})

_register({
    "id": "INV-PIPELINE-003",
    "description": "If security gate is blocking, ready_for_pr must be False",
    "severity": "critical",
    "check": lambda security_blocking, ready_for_pr, **kw: (
        not security_blocking
    ) or (not ready_for_pr),
})

_register({
    "id": "INV-PIPELINE-004",
    "description": "changed_files is always a list (never None)",
    "severity": "critical",
    "check": lambda changed_files, **kw: isinstance(changed_files, list),
})


# ============================================================================
# Delivery Invariants
# ============================================================================

_register({
    "id": "INV-DELIVERY-001",
    "description": "DeliveryReceipt with sha_verified=True must have remote_sha",
    "severity": "critical",
    "check": lambda sha_verified, remote_sha, **kw: (
        not sha_verified
    ) or (remote_sha is not None and remote_sha != ""),
})

_register({
    "id": "INV-DELIVERY-002",
    "description": "DeliveryReceipt status 'reconciled' implies sha_verified=True",
    "severity": "critical",
    "check": lambda status, sha_verified, **kw: (
        status != "reconciled"
    ) or sha_verified,
})

_register({
    "id": "INV-DELIVERY-003",
    "description": "DeliveryIntent always has commit_sha and branch",
    "severity": "critical",
    "check": lambda commit_sha, branch, **kw: (
        commit_sha is not None and commit_sha != ""
        and branch is not None and branch != ""
    ),
})


# ============================================================================
# Usage Honesty Invariants
# ============================================================================

_register({
    "id": "INV-USAGE-001",
    "description": "usage_status=unavailable → input_tokens=None AND output_tokens=None",
    "severity": "critical",
    "check": lambda usage_status, input_tokens, output_tokens, **kw: (
        usage_status != "unavailable"
    ) or (input_tokens is None and output_tokens is None),
})

_register({
    "id": "INV-USAGE-002",
    "description": "usage_status=measured → at least one token counter is not None",
    "severity": "critical",
    "check": lambda usage_status, input_tokens, output_tokens, **kw: (
        usage_status != "measured"
    ) or (input_tokens is not None or output_tokens is not None),
})

_register({
    "id": "INV-USAGE-003",
    "description": "cost_status=measured → cost is not None",
    "severity": "critical",
    "check": lambda cost_status, cost, **kw: (
        cost_status != "measured"
    ) or (cost is not None),
})

_register({
    "id": "INV-USAGE-004",
    "description": "cost is never negative",
    "severity": "critical",
    "check": lambda cost, **kw: cost is None or cost >= 0,
})


# ============================================================================
# Budget Invariants
# ============================================================================

_register({
    "id": "INV-BUDGET-001",
    "description": "model_calls never exceeds max_model_calls (when set)",
    "severity": "critical",
    "check": lambda model_calls, max_model_calls, **kw: (
        max_model_calls is None
    ) or (model_calls <= max_model_calls),
})

_register({
    "id": "INV-BUDGET-002",
    "description": "remaining_calls() == max_model_calls - model_calls (when max is set)",
    "severity": "critical",
    "check": lambda remaining_calls, max_model_calls, model_calls, **kw: (
        max_model_calls is None
    ) or (remaining_calls == max(0, max_model_calls - model_calls)),
})

_register({
    "id": "INV-BUDGET-003",
    "description": "BudgetExceeded raised iff model_calls >= max_model_calls (when max is set)",
    "severity": "critical",
    "check": lambda budget_exceeded_raised, model_calls, max_model_calls, **kw: (
        max_model_calls is None
    ) or (budget_exceeded_raised == (model_calls >= max_model_calls)),
})


# ============================================================================
# Selftest
# ============================================================================

def selftest() -> bool:
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
    return ok


def main(argv):
    if "--selftest" in argv:
        return 0 if selftest() else 1
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
