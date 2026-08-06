"""Unit tests for tools/spec_levels.py — spec level classification and coverage assessment."""
from __future__ import annotations

import pytest

import spec_levels


@pytest.mark.unit
class TestClassify:
    """Tests for classify(): deterministic spec level selection from signals."""

    def test_quick_task_is_l0(self):
        result = spec_levels.classify({"task_type": "QUICK"})
        assert result["level"] == 0
        assert result["level_name"] == "L0 QUICK"

    def test_engineering_task_is_l1(self):
        result = spec_levels.classify({"task_type": "ENGINEERING"})
        assert result["level"] == 1
        assert result["level_name"] == "L1 ENGINEERING"

    def test_product_task_is_l2(self):
        result = spec_levels.classify({"task_type": "PRODUCT"})
        assert result["level"] == 2
        assert result["level_name"] == "L2 PRODUCT"

    def test_critical_task_is_l3(self):
        result = spec_levels.classify({"task_type": "CRITICAL"})
        assert result["level"] == 3
        assert result["level_name"] == "L3 CRITICAL"

    def test_critical_risk_escalates_to_l3(self):
        result = spec_levels.classify({"task_type": "QUICK", "risk": "critical"})
        assert result["level"] == 3
        assert any("эскалация" in r for r in result["reason"])

    def test_secret_boundary_escalates_to_l3(self):
        result = spec_levels.classify({"task_type": "ENGINEERING", "secret_boundary": True})
        assert result["level"] == 3

    def test_user_facing_change_escalates_to_l2(self):
        result = spec_levels.classify({
            "task_type": "QUICK",
            "measurable_behavior": True,
            "user_facing_change": True,
        })
        assert result["level"] == 2

    def test_requested_lower_level_not_silent(self):
        """Requesting a lower level than signals require must NOT silently downgrade."""
        result = spec_levels.classify({"task_type": "ENGINEERING", "requested_level": 0})
        assert result["level"] == 1  # stays at L1
        assert result["escalated_from"] == 0

    def test_requested_higher_level_accepted(self):
        """Requesting a higher level is allowed (escalation up)."""
        result = spec_levels.classify({"task_type": "QUICK", "requested_level": 2})
        assert result["level"] == 2

    def test_default_task_type_is_quick(self):
        result = spec_levels.classify({})
        assert result["level"] == 0


@pytest.mark.unit
class TestRequiredSections:
    """Tests for required_sections(): cumulative section lists per level."""

    def test_l0_sections(self):
        sections = spec_levels.required_sections(0)
        assert "goal" in sections
        assert "scope" in sections
        assert "acceptance_criteria" in sections

    def test_l1_includes_l0(self):
        l0 = set(spec_levels.required_sections(0))
        l1 = set(spec_levels.required_sections(1))
        assert l0 <= l1
        assert "verification_strategy" in l1

    def test_l3_includes_all_levels(self):
        all_sections = set(spec_levels.required_sections(3))
        assert "goal" in all_sections           # L0
        assert "requirements" in all_sections   # L1
        assert "problem" in all_sections        # L2
        assert "threat_model" in all_sections   # L3


@pytest.mark.unit
class TestAssess:
    """Tests for assess(): spec coverage evaluation."""

    def test_empty_quick_has_blocking_missing(self):
        result = spec_levels.assess({"task_type": "QUICK"})
        assert result["blocking_missing"] != []
        assert result["ready_to_implement"] is False

    def test_full_l0_is_ready(self):
        provided = {s: {"status": "complete"} for s in spec_levels.LEVEL_SECTIONS[0]}
        result = spec_levels.assess({"task_type": "QUICK"}, provided)
        assert result["ready_to_implement"] is True
        assert result["blocking_missing"] == []

    def test_not_applicable_does_not_block(self):
        provided = {s: {"status": "not_applicable", "note": "N/A"} for s in spec_levels.LEVEL_SECTIONS[0]}
        result = spec_levels.assess({"task_type": "QUICK"}, provided)
        assert result["ready_to_implement"] is True

    def test_declined_without_note_is_form_error(self):
        provided = {s: {"status": "complete"} for s in spec_levels.LEVEL_SECTIONS[0]}
        provided["scope"] = {"status": "declined"}  # no note
        result = spec_levels.assess({"task_type": "QUICK"}, provided)
        assert result["form_errors"] != []
        assert result["ready_to_implement"] is False

    def test_needs_human_tracked(self):
        provided = {s: {"status": "complete"} for s in spec_levels.LEVEL_SECTIONS[0]}
        provided["constraints"] = {"status": "needs_human", "note": "needs owner"}
        result = spec_levels.assess({"task_type": "QUICK"}, provided)
        assert "constraints" in result["needs_human"]
