"""Granular tests for validate_workflow_gates (migrated from selftest)."""
from __future__ import annotations

import pytest

from validate_workflow_gates import (  # noqa: F401
    check,
    load,
    track_errors,
)


@pytest.fixture(scope="module")
def real_gates():
    """Load the real package gate/workflow data once."""
    gates, wfs, mvp, track_gates, tracks = load()
    return gates, wfs, mvp, track_gates, tracks


@pytest.mark.unit
@pytest.mark.slow
class TestRealPackageConsistency:
    """Real-package consistency checks."""

    def test_real_package_workflow_gate_consistent(self, real_gates):
        gates, wfs, mvp, track_gates, tracks = real_gates
        e, wn = check(gates, wfs, mvp, track_gates)
        assert e == []

    def test_real_package_zero_warns(self, real_gates):
        gates, wfs, mvp, track_gates, tracks = real_gates
        e, wn = check(gates, wfs, mvp, track_gates)
        assert wn == []


@pytest.mark.unit
@pytest.mark.slow
class TestGateApplicability:
    """Synthetic gate applicability checks."""

    def test_gate_outside_applicability_produces_error(self):
        g = {"g1": {"applicability": ["ENGINEERING"], "blocking": True}}
        w = {"VISUAL": {"quality_gates": ["g1"]}, "ENGINEERING": {}}
        e2, _ = check(g, w)
        assert any("g1" in x and "applicability" in x for x in e2)

    def test_applicability_all_no_errors(self):
        g3 = {"g2": {"applicability": ["all"], "blocking": False}}
        w3 = {"VISUAL": {"quality_gates": ["g2"]}}
        e3, _ = check(g3, w3)
        assert e3 == []

    def test_nonexistent_gate_produces_error(self):
        e4, _ = check({}, {"QUICK": {"quality_gates": ["ghost"]}})
        assert any("ghost" in x for x in e4)

    def test_applicability_unknown_workflow_produces_error(self):
        e5, _ = check(
            {"g5": {"applicability": ["GHOSTWF"], "blocking": True}}, {"QUICK": {}}
        )
        assert any("GHOSTWF" in x and "неизвестный" in x for x in e5)


@pytest.mark.unit
@pytest.mark.slow
class TestMvpBlocking:
    """MVP-blocking gate reachability checks."""

    def test_mvp_blocking_unreachable_produces_error(self):
        e6, _ = check(
            {"gm": {"applicability": ["QUICK"], "blocking": True}},
            {"QUICK": {"quality_gates": []}},
            mvp={"gm"},
            track_gates=set(),
        )
        assert any("gm" in x and "НЕдостижим" in x for x in e6)

    def test_mvp_blocking_via_track_no_error(self):
        e7, w7 = check(
            {"gm": {"applicability": ["QUICK"], "blocking": True}},
            {"QUICK": {"quality_gates": []}},
            mvp={"gm"},
            track_gates={"gm"},
        )
        assert e7 == []

    def test_non_mvp_blocking_not_covered_is_warn(self):
        e8, w8 = check(
            {"gw": {"applicability": ["QUICK"], "blocking": True}},
            {"QUICK": {"quality_gates": []}},
            mvp=set(),
            track_gates=set(),
        )
        assert e8 == []
        assert any("gw" in x for x in w8)

    def test_enforced_by_reachable_from_outside(self):
        e9, w9 = check(
            {
                "go": {
                    "applicability": ["QUICK"],
                    "blocking": True,
                    "enforced_by": "openspec-ci-guard",
                }
            },
            {"QUICK": {"quality_gates": []}},
            mvp={"go"},
            track_gates=set(),
        )
        assert e9 == [] and w9 == []


@pytest.mark.unit
@pytest.mark.slow
class TestTrackRegistry:
    """Track registry validation."""

    def test_real_track_registry_no_errors(self, real_gates):
        gates, wfs, mvp, track_gates, tracks = real_gates
        assert track_errors(tracks) == []

    def test_empty_track_registry_produces_error(self):
        assert any("треков нет" in e for e in track_errors({}))

    def test_conditional_without_skip_reason_produces_error(self):
        assert any(
            "skip_reason" in e
            for e in track_errors(
                {"t": {"signal": "s", "kind": "conditional", "gates": ["g"]}}
            )
        )
