"""Property-based verification for the AI Ops Kit invariant catalog.

Uses hypothesis to verify each invariant holds under random inputs.
Each invariant is tested with both valid (invariant-holding) and boundary inputs.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

pytestmark = [pytest.mark.unit, pytest.mark.critical_path]

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT / "tools"))

from invariants import (  # noqa: E402
    ALL_INVARIANTS,
    check_invariant,
)
import budget as budget_mod  # noqa: E402


# ============================================================================
# Helpers
# ============================================================================

st_optional_text = st.one_of(st.none(), st.text(min_size=1, max_size=20))
st_sha = st.text(alphabet="0123456789abcdef", min_size=7, max_size=40)
st_branch = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-/", min_size=1, max_size=40)
st_status_pipeline = st.sampled_from(["error", "ready-undelivered", "delivered", "delivery-failed"])
st_delivery_status = st.sampled_from(["reconciled", "not-delivered", "mismatch", "reconciled-absent"])
st_usage_status = st.sampled_from(["measured", "estimated", "unavailable"])
st_cost_status = st.sampled_from(["measured", "estimated", "unavailable"])
st_task_type = st.sampled_from([
    "QUICK", "ENGINEERING", "PRODUCT", "CRITICAL", "AI_FEATURE", "RESEARCH", "MARKETING",
])


# ============================================================================
# Selftest
# ============================================================================

class TestInvariantCatalogSelfTest:
    """Verify the invariant catalog itself is well-formed."""

# тест selftest() удалён: тело переехало в tests/unit/test_invariants_selftest.py

    def test_all_invariants_have_ids(self):
        ids = [inv["id"] for inv in ALL_INVARIANTS]
        assert len(ids) == len(set(ids)), "Duplicate invariant IDs"

    def test_check_invariant_unknown_raises(self):
        with pytest.raises(KeyError):
            check_invariant("INV-NONEXISTENT-999")


# ============================================================================
# Preflight Invariants — Property-Based
# ============================================================================

class TestPreflightInvariants:
    """Property-based verification for preflight invariants."""

    @given(
        blocked=st.booleans(),
        n_reasons=st.integers(min_value=0, max_value=10),
    )
    @settings(max_examples=50, deadline=2000)
    def test_inv_preflight_001_blocked_implies_reasons(self, blocked, n_reasons):
        """INV-PREFLIGHT-001: If blocked=True, reasons must be non-empty."""
        reasons = [f"reason_{i}" for i in range(n_reasons)]
        # When blocked=True and reasons non-empty → invariant holds
        # When blocked=True and reasons empty → invariant violated (we don't assert that case)
        if blocked and len(reasons) > 0:
            assert check_invariant("INV-PREFLIGHT-001", blocked=blocked, reasons=reasons)
        elif not blocked:
            assert check_invariant("INV-PREFLIGHT-001", blocked=blocked, reasons=reasons)

    @given(
        ok=st.booleans(),
        blocked=st.booleans(),
    )
    @settings(max_examples=50, deadline=2000)
    def test_inv_preflight_002_no_silent_failures(self, ok, blocked):
        """INV-PREFLIGHT-002: ok=False → blocked=True."""
        result = check_invariant("INV-PREFLIGHT-002", ok=ok, blocked=blocked)
        # Invariant fails only when ok=False AND blocked=False
        assert result == (ok or blocked)

    @given(
        task_type=st_task_type,
        spec_artifact=st.booleans(),
        author=st.booleans(),
        blocked=st.booleans(),
    )
    @settings(max_examples=50, deadline=2000)
    def test_inv_preflight_003_heavy_without_spec(self, task_type, spec_artifact, author, blocked):
        """INV-PREFLIGHT-003: ENGINEERING/PRODUCT/CRITICAL without spec must be blocked."""
        result = check_invariant(
            "INV-PREFLIGHT-003",
            task_type=task_type, spec_artifact=spec_artifact, author=author, blocked=blocked,
        )
        # Invariant: if heavy + no spec + not author → must be blocked
        is_heavy = task_type in ("ENGINEERING", "PRODUCT", "CRITICAL")
        should_block = is_heavy and not spec_artifact and not author
        if should_block:
            assert result == blocked  # holds iff blocked is True
        else:
            assert result is True  # always holds when not in the blocking condition

    @given(
        reevaluate_only=st.booleans(),
        skipped_reevaluate=st.booleans(),
    )
    @settings(max_examples=50, deadline=2000)
    def test_inv_preflight_004_reevaluate_skips_spec(self, reevaluate_only, skipped_reevaluate):
        """INV-PREFLIGHT-004: reevaluate_only=True → spec check has skipped_reevaluate."""
        spec_check = {"skipped_reevaluate": skipped_reevaluate}
        result = check_invariant(
            "INV-PREFLIGHT-004",
            reevaluate_only=reevaluate_only, spec_check=spec_check,
        )
        if reevaluate_only:
            assert result == skipped_reevaluate
        else:
            assert result is True

    @given(
        has_classification=st.booleans(),
        extra_keys=st.lists(st.text(min_size=1, max_size=10), max_size=5, unique=True),
    )
    @settings(max_examples=50, deadline=2000)
    def test_inv_preflight_005_classification_present(self, has_classification, extra_keys):
        """INV-PREFLIGHT-005: classification always in checks dict."""
        checks = {k: {"ok": True} for k in extra_keys}
        if has_classification:
            checks["classification"] = {"ok": True, "task_type": "QUICK"}
        result = check_invariant("INV-PREFLIGHT-005", checks=checks)
        assert result == has_classification


# ============================================================================
# Pipeline Invariants — Property-Based
# ============================================================================

class TestPipelineInvariants:
    """Property-based verification for execution pipeline invariants."""

    @given(
        has_overall=st.booleans(),
        has_ready=st.booleans(),
        has_gates=st.booleans(),
    )
    @settings(max_examples=50, deadline=2000)
    def test_inv_pipeline_001_required_keys(self, has_overall, has_ready, has_gates):
        """INV-PIPELINE-001: result always has overall_status, ready_for_pr, gates."""
        result = {}
        if has_overall:
            result["overall_status"] = "done"
        if has_ready:
            result["ready_for_pr"] = True
        if has_gates:
            result["gates"] = {}
        invariant_holds = has_overall and has_ready and has_gates
        assert check_invariant("INV-PIPELINE-001", result=result) == invariant_holds

    @given(
        ready_for_pr=st.booleans(),
        overall_status=st_status_pipeline,
    )
    @settings(max_examples=50, deadline=2000)
    def test_inv_pipeline_002_ready_implies_not_error(self, ready_for_pr, overall_status):
        """INV-PIPELINE-002: ready_for_pr=True → overall_status != 'error'."""
        result = check_invariant(
            "INV-PIPELINE-002", ready_for_pr=ready_for_pr, overall_status=overall_status,
        )
        if ready_for_pr:
            assert result == (overall_status != "error")
        else:
            assert result is True

    @given(
        security_blocking=st.booleans(),
        ready_for_pr=st.booleans(),
    )
    @settings(max_examples=50, deadline=2000)
    def test_inv_pipeline_003_security_blocks_pr(self, security_blocking, ready_for_pr):
        """INV-PIPELINE-003: security blocking → ready_for_pr=False."""
        result = check_invariant(
            "INV-PIPELINE-003", security_blocking=security_blocking, ready_for_pr=ready_for_pr,
        )
        if security_blocking:
            assert result == (not ready_for_pr)
        else:
            assert result is True

    @given(
        changed_files=st.one_of(
            st.none(),
            st.lists(st.text(min_size=1, max_size=50), max_size=20),
            st.just("not-a-list"),
            st.just(42),
        ),
    )
    @settings(max_examples=50, deadline=2000)
    def test_inv_pipeline_004_changed_files_is_list(self, changed_files):
        """INV-PIPELINE-004: changed_files is always a list."""
        result = check_invariant("INV-PIPELINE-004", changed_files=changed_files)
        assert result == isinstance(changed_files, list)


# ============================================================================
# Delivery Invariants — Property-Based
# ============================================================================

class TestDeliveryInvariants:
    """Property-based verification for delivery invariants."""

    @given(
        sha_verified=st.booleans(),
        remote_sha=st.one_of(st.none(), st.just(""), st_sha),
    )
    @settings(max_examples=50, deadline=2000)
    def test_inv_delivery_001_verified_implies_remote(self, sha_verified, remote_sha):
        """INV-DELIVERY-001: sha_verified=True → remote_sha present."""
        result = check_invariant(
            "INV-DELIVERY-001", sha_verified=sha_verified, remote_sha=remote_sha,
        )
        if sha_verified:
            assert result == (remote_sha is not None and remote_sha != "")
        else:
            assert result is True

    @given(
        status=st_delivery_status,
        sha_verified=st.booleans(),
    )
    @settings(max_examples=50, deadline=2000)
    def test_inv_delivery_002_reconciled_implies_verified(self, status, sha_verified):
        """INV-DELIVERY-002: status='reconciled' → sha_verified=True."""
        result = check_invariant(
            "INV-DELIVERY-002", status=status, sha_verified=sha_verified,
        )
        if status == "reconciled":
            assert result == sha_verified
        else:
            assert result is True

    @given(
        commit_sha=st.one_of(st.none(), st.just(""), st_sha),
        branch=st.one_of(st.none(), st.just(""), st_branch),
    )
    @settings(max_examples=50, deadline=2000)
    def test_inv_delivery_003_intent_has_sha_and_branch(self, commit_sha, branch):
        """INV-DELIVERY-003: DeliveryIntent has commit_sha and branch."""
        result = check_invariant(
            "INV-DELIVERY-003", commit_sha=commit_sha, branch=branch,
        )
        expected = (commit_sha is not None and commit_sha != ""
                    and branch is not None and branch != "")
        assert result == expected


# ============================================================================
# Usage Honesty Invariants — Property-Based
# ============================================================================

class TestUsageHonestyInvariants:
    """Property-based verification for usage honesty invariants."""

    @given(
        usage_status=st_usage_status,
        input_tokens=st.one_of(st.none(), st.integers(min_value=0, max_value=100000)),
        output_tokens=st.one_of(st.none(), st.integers(min_value=0, max_value=100000)),
    )
    @settings(max_examples=50, deadline=2000)
    def test_inv_usage_001_unavailable_means_none_tokens(self, usage_status, input_tokens, output_tokens):
        """INV-USAGE-001: unavailable → both token counters None."""
        result = check_invariant(
            "INV-USAGE-001",
            usage_status=usage_status, input_tokens=input_tokens, output_tokens=output_tokens,
        )
        if usage_status == "unavailable":
            assert result == (input_tokens is None and output_tokens is None)
        else:
            assert result is True

    @given(
        usage_status=st_usage_status,
        input_tokens=st.one_of(st.none(), st.integers(min_value=0, max_value=100000)),
        output_tokens=st.one_of(st.none(), st.integers(min_value=0, max_value=100000)),
    )
    @settings(max_examples=50, deadline=2000)
    def test_inv_usage_002_measured_means_some_tokens(self, usage_status, input_tokens, output_tokens):
        """INV-USAGE-002: measured → at least one token counter not None."""
        result = check_invariant(
            "INV-USAGE-002",
            usage_status=usage_status, input_tokens=input_tokens, output_tokens=output_tokens,
        )
        if usage_status == "measured":
            assert result == (input_tokens is not None or output_tokens is not None)
        else:
            assert result is True

    @given(
        cost_status=st_cost_status,
        cost=st.one_of(st.none(), st.floats(min_value=0.0, max_value=1000.0, allow_nan=False)),
    )
    @settings(max_examples=50, deadline=2000)
    def test_inv_usage_003_measured_cost_not_none(self, cost_status, cost):
        """INV-USAGE-003: cost_status=measured → cost is not None."""
        result = check_invariant("INV-USAGE-003", cost_status=cost_status, cost=cost)
        if cost_status == "measured":
            assert result == (cost is not None)
        else:
            assert result is True

    @given(
        cost=st.one_of(st.none(), st.floats(min_value=-100.0, max_value=1000.0, allow_nan=False)),
    )
    @settings(max_examples=50, deadline=2000)
    def test_inv_usage_004_cost_never_negative(self, cost):
        """INV-USAGE-004: cost is never negative."""
        result = check_invariant("INV-USAGE-004", cost=cost)
        assert result == (cost is None or cost >= 0)


# ============================================================================
# Budget Invariants — Property-Based (with actual Budget class)
# ============================================================================

class TestBudgetInvariants:
    """Property-based verification for budget invariants, using the real Budget class."""

    @given(
        max_calls=st.integers(min_value=1, max_value=1000),
        n_attempts=st.integers(min_value=0, max_value=200),
    )
    @settings(max_examples=50, deadline=2000)
    def test_inv_budget_001_calls_never_exceed_max(self, max_calls, n_attempts):
        """INV-BUDGET-001: model_calls never exceeds max_model_calls."""
        b = budget_mod.Budget(max_model_calls=max_calls)
        for _ in range(n_attempts):
            try:
                b.charge_call()
            except budget_mod.BudgetExceeded:
                break
        assert check_invariant(
            "INV-BUDGET-001", model_calls=b.model_calls, max_model_calls=b.max_model_calls,
        )

    @given(
        max_calls=st.integers(min_value=1, max_value=1000),
        n_calls=st.integers(min_value=0, max_value=100),
    )
    @settings(max_examples=50, deadline=2000)
    def test_inv_budget_002_remaining_is_correct(self, max_calls, n_calls):
        """INV-BUDGET-002: remaining_calls() == max(0, max - current)."""
        b = budget_mod.Budget(max_model_calls=max_calls)
        actual_calls = min(n_calls, max_calls)
        for _ in range(actual_calls):
            b.charge_call()
        assert check_invariant(
            "INV-BUDGET-002",
            remaining_calls=b.remaining_calls(),
            max_model_calls=b.max_model_calls,
            model_calls=b.model_calls,
        )

    @given(
        max_calls=st.integers(min_value=1, max_value=100),
    )
    @settings(max_examples=50, deadline=2000)
    def test_inv_budget_003_exceeded_iff_at_ceiling(self, max_calls):
        """INV-BUDGET-003: BudgetExceeded raised iff model_calls >= max_model_calls."""
        b = budget_mod.Budget(max_model_calls=max_calls)
        # Fill up to ceiling
        for _ in range(max_calls):
            b.charge_call()
        assert b.model_calls == max_calls
        # Now the next call should raise
        raised = False
        try:
            b.charge_call()
        except budget_mod.BudgetExceeded:
            raised = True
        assert check_invariant(
            "INV-BUDGET-003",
            budget_exceeded_raised=raised,
            model_calls=b.model_calls,
            max_model_calls=max_calls,
        )
        assert raised is True  # at ceiling, must raise

    @given(
        max_calls=st.integers(min_value=1, max_value=100),
        n_calls=st.integers(min_value=0, max_value=50),
    )
    @settings(max_examples=50, deadline=2000)
    def test_budget_unlimited_never_raises(self, max_calls, n_calls):
        """Budget with no max_model_calls never raises BudgetExceeded."""
        b = budget_mod.Budget(max_model_calls=None)
        for _ in range(n_calls):
            b.charge_call()
        assert b.model_calls == n_calls
        assert b.remaining_calls() is None
        assert check_invariant(
            "INV-BUDGET-001", model_calls=b.model_calls, max_model_calls=None,
        )


# ============================================================================
# Cross-module integration: usage_ledger.check() vs invariants
# ============================================================================

class TestUsageLedgerIntegration:
    """Verify that usage_ledger.check() enforces the same invariants as our catalog."""

    @given(
        input_tokens=st.one_of(st.none(), st.integers(min_value=0, max_value=1000)),
        output_tokens=st.one_of(st.none(), st.integers(min_value=0, max_value=1000)),
    )
    @settings(max_examples=50, deadline=2000)
    def test_usage_ledger_check_catches_unavailable_with_tokens(self, input_tokens, output_tokens):
        """usage_ledger.check() flags unavailable records with non-None tokens."""
        import usage_ledger
        rec = {
            "usage_status": "unavailable",
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_status": "unavailable",
            "cost": None,
        }
        errors = usage_ledger.check(rec)
        inv_holds = check_invariant(
            "INV-USAGE-001",
            usage_status="unavailable",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        # If invariant is violated, ledger should report errors
        if not inv_holds:
            assert len(errors) > 0

    @given(
        input_tokens=st.one_of(st.none(), st.integers(min_value=0, max_value=1000)),
        output_tokens=st.one_of(st.none(), st.integers(min_value=0, max_value=1000)),
    )
    @settings(max_examples=50, deadline=2000)
    def test_usage_ledger_check_catches_measured_without_tokens(self, input_tokens, output_tokens):
        """usage_ledger.check() flags measured records with no tokens."""
        import usage_ledger
        rec = {
            "usage_status": "measured",
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_status": "measured",
            "cost": 0.01,
        }
        errors = usage_ledger.check(rec)
        inv_holds = check_invariant(
            "INV-USAGE-002",
            usage_status="measured",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        if not inv_holds:
            assert len(errors) > 0
