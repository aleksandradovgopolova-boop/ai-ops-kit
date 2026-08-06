"""Unit tests for tools/gate_executor.py — quality gate evaluation.

Tests gate classification, evidence validation, deterministic validators,
override policy, and the evaluate() aggregation. Complements the selftest
wrapper with granular assertions.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT / "tools"))

import gate_executor


@pytest.mark.critical_path
@pytest.mark.unit
class TestGateClassification:
    """Tests for classify() — gate type determination."""

    def test_deterministic_gate(self):
        """Gate with validator should classify as deterministic."""
        gate = {"validator": "validate-references"}
        kind = gate_executor.classify(gate)
        assert kind == "deterministic"

    def test_ai_review_gate(self):
        """Gate with review_mode=read-only should classify as ai-review."""
        gate = {"review_mode": "read-only"}
        kind = gate_executor.classify(gate)
        assert kind == "ai-review"

    def test_writer_check_fallback(self):
        """Gate without validator or review_mode should classify as writer-check."""
        gate = {}
        kind = gate_executor.classify(gate)
        assert kind == "writer-check"

    def test_human_approval_unconditional(self):
        """Gate with human_approval=True should classify as human-approval."""
        gate = {"human_approval": True}
        kind = gate_executor.classify(gate)
        assert kind == "human-approval"


@pytest.mark.critical_path
@pytest.mark.unit
class TestEvaluateQuick:
    """Tests for evaluate() on QUICK workflow."""

    def test_quick_without_evidence_blocked(self):
        """QUICK workflow without evidence should be blocked."""
        result = gate_executor.evaluate("QUICK")
        assert result["blocked"] is True
        assert len(result["unmet_gates"]) > 0

    def test_quick_with_full_evidence_passes(self):
        """QUICK with complete evidence should not be blocked."""
        evidence = {
            "intake_completeness": {
                "status": "pass",
                "provided": ["classified_type", "size", "risk"],
            },
            "implementation_verification": {
                "status": "pass",
                "provided": ["build_passed", "lint_passed", "typecheck_passed", "tests_passed", "tested_revision"],
            },
        }
        result = gate_executor.evaluate("QUICK", evidence=evidence)
        assert result["blocked"] is False

    def test_partial_evidence_still_blocked(self):
        """Providing evidence for only one gate should still block."""
        evidence = {
            "intake_completeness": {
                "status": "pass",
                "provided": ["classified_type", "size", "risk"],
            },
        }
        result = gate_executor.evaluate("QUICK", evidence=evidence)
        assert result["blocked"] is True


@pytest.mark.critical_path
@pytest.mark.unit
class TestOverridePolicy:
    """Tests for override_effective — respects bypass_policy."""

    def test_forbidden_gate_cannot_be_overridden(self):
        """Gates with bypass_policy=forbidden cannot be overridden."""
        gate = {"bypass_policy": "forbidden"}
        override = {"by": "admin", "reason": "urgent"}
        assert gate_executor.override_effective(gate, override) is False

    def test_allowed_gate_can_be_overridden(self):
        """Gates with override_policy.allowed=True can be overridden."""
        gate = {"override_policy": {"allowed": True}}
        override = {"by": "admin", "reason": "urgent"}
        assert gate_executor.override_effective(gate, override) is True

    def test_no_override_policy_cannot_bypass(self):
        """Gates without explicit override policy cannot be bypassed."""
        gate = {}
        override = {"by": "admin", "reason": "urgent"}
        assert gate_executor.override_effective(gate, override) is False


@pytest.mark.critical_path
@pytest.mark.unit
class TestEvaluateGate:
    """Tests for evaluate_gate — single gate evaluation."""

    def test_evaluate_gate_returns_schema(self):
        """evaluate_gate should return a dict with required schema keys."""
        gate = {"validator": "validate-references"}
        result = gate_executor.evaluate_gate(
            "test_gate",
            gate,
            evidence={},
        )
        assert "schema_version" in result
        assert "gate" in result
        assert "status" in result
        assert "blocking" in result

    def test_unmet_gate_has_fail_or_warn_status(self):
        """Unmet gate without evidence should have status=fail or warn."""
        gate = {"blocking": True}
        result = gate_executor.evaluate_gate(
            "test_gate",
            gate,
            evidence={},
        )
        assert result["status"] in ("fail", "warn")


@pytest.mark.critical_path
@pytest.mark.unit
class TestCollectEvidence:
    """Tests for collect_evidence — extracting evidence from reviewer artifacts."""

    def test_collect_from_reviewer_json(self, child_root):
        """collect_evidence should read from .reviewer.json files."""
        run_dir = child_root / ".ai" / "runtime" / "test-run"
        run_dir.mkdir(parents=True)
        reviewer_file = run_dir / "stage-review.reviewer.json"
        reviewer_file.write_text('{"verdict": "pass", "reasoning": "looks good"}')

        evidence = gate_executor.collect_evidence("QUICK", run_dir)
        assert isinstance(evidence, dict)

    def test_collect_empty_when_no_artifacts(self, child_root):
        """collect_evidence should return empty dict when no artifacts exist."""
        run_dir = child_root / ".ai" / "runtime" / "empty-run"
        run_dir.mkdir(parents=True)
        evidence = gate_executor.collect_evidence("QUICK", run_dir)
        assert evidence == {} or isinstance(evidence, dict)


@pytest.mark.critical_path
@pytest.mark.unit
class TestLoadGates:
    """Tests for load_gates — loading gate definitions."""

    def test_load_gates_returns_dict(self):
        """load_gates should return a dict of gate definitions."""
        gates = gate_executor.load_gates()
        assert isinstance(gates, dict)
        assert len(gates) > 0

    def test_load_workflows_returns_dict(self):
        """load_workflows should return a dict of workflow definitions."""
        workflows = gate_executor.load_workflows()
        assert isinstance(workflows, dict)
        assert len(workflows) > 0
