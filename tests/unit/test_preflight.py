"""Unit tests for tools/preflight.py — pre-execution checks.

Tests the deterministic preflight gates: classification, context payload,
spec sufficiency, atomicity, context budget, approvals, lifecycle errors,
and economic budget. Complements test_property_based.py without duplication.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT / "tools"))

import preflight


@pytest.mark.critical_path
@pytest.mark.unit
class TestPreflightClean:
    """Tests for clean preflight — no blockers."""

    def test_clean_quick_atomic(self, child_root):
        """QUICK atomic task with no issues should pass preflight."""
        signals = {
            "task_type": "QUICK",
            "work_package_id": "root",
            "size": "small",
        }
        result = preflight.assess(
            signals=signals,
            child_root=child_root,
            wid="test-wid",
        )
        assert result["ok"] is True
        assert result["blocked"] is False
        assert len(result["reasons"]) == 0


@pytest.mark.critical_path
@pytest.mark.unit
class TestSpecSufficiency:
    """Tests for spec-first gate — blocks heavy tasks without spec."""

    def test_quick_without_spec_not_blocked(self, child_root):
        """QUICK task without spec should not block (light task)."""
        signals = {
            "task_type": "QUICK",
            "work_package_id": "root",
        }
        result = preflight.assess(
            signals=signals,
            child_root=child_root,
            wid="test-wid",
        )
        assert result["ok"] is True


@pytest.mark.critical_path
@pytest.mark.unit
class TestAtomicity:
    """Tests for atomic gate — non-atomic tasks need decomposition confirmation."""

    def test_atomic_task_passes(self, child_root):
        """Atomic task with work_package_id should pass atomic gate."""
        signals = {
            "task_type": "QUICK",
            "work_package_id": "root",
        }
        result = preflight.assess(
            signals=signals,
            child_root=child_root,
            wid="test-wid",
        )
        assert result["ok"] is True


@pytest.mark.critical_path
@pytest.mark.unit
class TestContextBudget:
    """Tests for context budget overflow gate."""

    def test_overflow_blocked(self, child_root):
        """Context overflow should block execution."""
        signals = {
            "task_type": "ENGINEERING",
            "work_package_id": "root",
        }
        bundle = {"overflow": True}
        result = preflight.assess(
            signals=signals,
            child_root=child_root,
            wid="test-wid",
            bundle=bundle,
            author=True,
        )
        assert result["blocked"] is True
        assert any("context" in r.lower() or "budget" in r.lower() for r in result["reasons"])


@pytest.mark.critical_path
@pytest.mark.unit
class TestApprovals:
    """Tests for human approval gates — secret_boundary and destructive."""

    def test_secret_boundary_without_approval_blocked(self, child_root):
        """secret_boundary=True without ApprovalRecord should block."""
        signals = {
            "task_type": "ENGINEERING",
            "work_package_id": "root",
            "secret_boundary": True,
        }
        result = preflight.assess(
            signals=signals,
            child_root=child_root,
            wid="test-wid",
            author=True,
        )
        assert result["blocked"] is True
        assert any("approval" in r.lower() or "human" in r.lower() for r in result["reasons"])

    def test_destructive_without_approval_blocked(self, child_root):
        """destructive=True without ApprovalRecord should block."""
        signals = {
            "task_type": "ENGINEERING",
            "work_package_id": "root",
            "destructive": True,
        }
        result = preflight.assess(
            signals=signals,
            child_root=child_root,
            wid="test-wid",
            author=True,
        )
        assert result["blocked"] is True
        assert any("destructive" in r.lower() for r in result["reasons"])


@pytest.mark.critical_path
@pytest.mark.unit
class TestLifecycleErrors:
    """Tests for lifecycle error gate — fail-closed for heavy tasks."""

    def test_lifecycle_error_heavy_blocked(self, child_root):
        """Heavy task with lifecycle errors should block (fail-closed)."""
        signals = {
            "task_type": "ENGINEERING",
            "work_package_id": "root",
        }
        result = preflight.assess(
            signals=signals,
            child_root=child_root,
            wid="test-wid",
            author=True,
            lifecycle_errors=["Compiler failed"],
        )
        assert result["blocked"] is True
        assert any("lifecycle" in r.lower() for r in result["reasons"])

    def test_lifecycle_error_quick_not_blocked(self, child_root):
        """QUICK task with lifecycle errors should not block (light task)."""
        signals = {
            "task_type": "QUICK",
            "work_package_id": "root",
        }
        result = preflight.assess(
            signals=signals,
            child_root=child_root,
            wid="test-wid",
            lifecycle_errors=["Compiler failed"],
        )
        assert result["ok"] is True


@pytest.mark.critical_path
@pytest.mark.unit
class TestReevaluateOnly:
    """Tests for reevaluate_only mode — bypasses some gates."""

    def test_reevaluate_bypasses_spec(self, child_root):
        """reevaluate_only=True should bypass spec-first gate."""
        signals = {
            "task_type": "ENGINEERING",
            "work_package_id": "root",
        }
        result = preflight.assess(
            signals=signals,
            child_root=child_root,
            wid="test-wid",
            reevaluate_only=True,
        )
        # Spec gate should not block
        spec_check = result["checks"].get("spec", {})
        assert not spec_check.get("blocking") or spec_check.get("skipped_reevaluate")

    def test_reevaluate_does_not_bypass_approvals(self, child_root):
        """reevaluate_only=True should NOT bypass approval gates."""
        signals = {
            "task_type": "ENGINEERING",
            "work_package_id": "root",
            "destructive": True,
        }
        result = preflight.assess(
            signals=signals,
            child_root=child_root,
            wid="test-wid",
            reevaluate_only=True,
        )
        assert result["blocked"] is True
        assert any("approval" in r.lower() or "destructive" in r.lower() for r in result["reasons"])
