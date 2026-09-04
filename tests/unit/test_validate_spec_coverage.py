"""Granular tests for validate_spec_coverage (migrated from selftest)."""
from __future__ import annotations

import pytest

from validate_spec_coverage import (  # noqa: F401
    PKG,
    check,
    json,
    sys,
)


@pytest.fixture
def good_coverage():
    return {
        "kind": "SpecCoverage",
        "level": 1,
        "escalated_from": None,
        "sections": [
            {"id": "goal", "status": "complete", "note": None},
            {"id": "scope", "status": "not_applicable", "note": "нет"},
        ],
        "blocking_missing": [],
        "form_errors": [],
        "ready_to_implement": True,
    }


@pytest.mark.unit
@pytest.mark.slow
class TestValidateSpecCoverage:
    """Validation of SpecCoverage documents."""

    def test_valid_coverage_no_errors(self, good_coverage):
        assert check(good_coverage) == []

    def test_wrong_kind_produces_error(self):
        assert any("SpecCoverage" in e for e in check({"kind": "x"}))

    def test_declined_without_note_produces_error(self, good_coverage):
        bad_dec = json.loads(json.dumps(good_coverage))
        bad_dec["sections"].append({"id": "x", "status": "declined"})
        assert any("declined" in e for e in check(bad_dec))

    def test_missing_not_in_blocking_missing_produces_error(self, good_coverage):
        bad_bm = json.loads(json.dumps(good_coverage))
        bad_bm["sections"].append({"id": "y", "status": "missing"})
        assert any("blocking_missing" in e for e in check(bad_bm))

    def test_ready_to_implement_true_with_missing_produces_error(self):
        bad_ready = {
            "kind": "SpecCoverage",
            "level": 0,
            "sections": [{"id": "goal", "status": "missing"}],
            "blocking_missing": ["goal"],
            "ready_to_implement": True,
        }
        assert any("ready_to_implement" in e for e in check(bad_ready))

    def test_escalated_from_gte_level_produces_error(self, good_coverage):
        bad_esc = json.loads(json.dumps(good_coverage))
        bad_esc["escalated_from"] = 2
        assert any("escalated_from" in e for e in check(bad_esc))

    def test_real_full_engineering_coverage_is_valid(self):
        from ai_ops_kit.gates import spec_levels

        cov = spec_levels.assess(
            {"task_type": "ENGINEERING"},
            {s: {"status": "complete"} for s in spec_levels.required_sections(1)},
        )
        assert check(cov) == []

    def test_real_empty_quick_coverage_is_valid_by_form(self):
        from ai_ops_kit.gates import spec_levels

        cov2 = spec_levels.assess({"task_type": "QUICK"})
        assert check(cov2) == []
