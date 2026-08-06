"""Unit tests for tools/contracts.py — TypedDict contract verification."""
from __future__ import annotations

import pytest

import contracts


@pytest.mark.unit
class TestTypedDictContracts:
    """Tests that all TypedDicts are proper dict subclasses with annotations."""

    @pytest.mark.parametrize("cls", [
        contracts.UsageRecord,
        contracts.PreflightResult,
        contracts.GateResultV2,
        contracts.RunReport,
        contracts.DeliveryIntent,
        contracts.DeliveryReceipt,
        contracts.ContextBundle,
        contracts.WorkItemState,
    ])
    def test_all_typedicts_are_dict_subclass(self, cls):
        """All TypedDicts must be dict subclasses at runtime (backwards compatible)."""
        assert issubclass(cls, dict)

    @pytest.mark.parametrize("cls", [
        contracts.UsageRecord,
        contracts.PreflightResult,
        contracts.GateResultV2,
        contracts.RunReport,
        contracts.DeliveryIntent,
        contracts.DeliveryReceipt,
        contracts.ContextBundle,
        contracts.WorkItemState,
    ])
    def test_all_typedicts_have_annotations(self, cls):
        """All TypedDicts must have non-empty __annotations__."""
        assert len(cls.__annotations__) > 0


@pytest.mark.unit
class TestUsageRecord:
    """Tests for UsageRecord contract fields."""

    def test_usage_record_has_required_fields(self):
        annotations = contracts.UsageRecord.__annotations__
        assert "usage_status" in annotations
        assert "input_tokens" in annotations
        assert "output_tokens" in annotations
        assert "cost" in annotations
        assert "cost_status" in annotations
        assert "provider" in annotations
        assert "model" in annotations
        assert "role" in annotations
        assert "run_id" in annotations

    def test_usage_record_has_context_fields(self):
        annotations = contracts.UsageRecord.__annotations__
        assert "task_type" in annotations
        assert "workflow" in annotations
        assert "writer_tier" in annotations


@pytest.mark.unit
class TestPreflightResult:
    """Tests for PreflightResult contract fields."""

    def test_preflight_result_has_required_fields(self):
        annotations = contracts.PreflightResult.__annotations__
        assert "ok" in annotations
        assert "blocked" in annotations
        assert "checks" in annotations
        assert "reasons" in annotations
        assert "kind" in annotations


@pytest.mark.unit
class TestGateResultV2:
    """Tests for GateResultV2 contract fields."""

    def test_gate_result_v2_has_required_fields(self):
        annotations = contracts.GateResultV2.__annotations__
        assert "schema_version" in annotations
        assert "gate" in annotations
        assert "status" in annotations
        assert "blocking" in annotations
        assert "checks" in annotations
        assert "blockers" in annotations
        assert "delivery_allowed" in annotations

    def test_gate_result_v2_has_v2_statuses(self):
        """v2 adds not_applicable and abstain statuses."""
        annotations = contracts.GateResultV2.__annotations__
        assert "applicability" in annotations
        assert "enforcement" in annotations


@pytest.mark.unit
class TestRunReport:
    """Tests for RunReport contract fields."""

    def test_run_report_has_required_fields(self):
        annotations = contracts.RunReport.__annotations__
        assert "workitem_id" in annotations
        assert "run_id" in annotations
        assert "overall_status" in annotations
        assert "ready_for_pr" in annotations
        assert "gates" in annotations
        assert "checks" in annotations
        assert "delivery" in annotations

    def test_run_report_has_cost_fields(self):
        annotations = contracts.RunReport.__annotations__
        assert "total_cost_usd" in annotations
        assert "total_tokens_in" in annotations
        assert "total_tokens_out" in annotations
        assert "call_count" in annotations


@pytest.mark.unit
class TestDeliveryContracts:
    """Tests for Delivery-related contracts."""

    def test_delivery_receipt_has_sha_verified(self):
        assert "sha_verified" in contracts.DeliveryReceipt.__annotations__

    def test_delivery_intent_has_required_fields(self):
        annotations = contracts.DeliveryIntent.__annotations__
        assert "delivery_id" in annotations
        assert "workitem_id" in annotations
        assert "repository" in annotations
        assert "branch" in annotations
        assert "commit_sha" in annotations
