"""Гранулярные тесты gate_policy (мигрировано из test_gate_policy_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.gates.gate_policy import (
    SAFETY_UI_GATES,
    UI_GATES,
    _effective,
    candidate_blocking_gates,
    candidate_policy,
    current_policy,
    derive_ui_impact,
    effective_review_outcome,
    shadow_diff,
)


@pytest.mark.unit
class TestDeriveUiImpact:
    def test_explicit_ui_impact_respected(self):
        assert derive_ui_impact({"ui_impact": "internal"}) == "internal"

    def test_legacy_ui_changed(self):
        assert derive_ui_impact({"ui_changed": True}) == "user_facing"

    def test_no_ui(self):
        assert derive_ui_impact({"task_type": "QUICK"}) == "none"

    def test_bogus_impact_falls_to_legacy(self):
        assert derive_ui_impact({"ui_impact": "bogus", "ui_changed": True}) == "user_facing"


@pytest.mark.unit
class TestCurrentPolicy:
    def test_ui_changed_all_blocking(self):
        cur = current_policy({"ui_changed": True})
        assert all(d["applicability"] == "applicable" and d["enforcement"] == "blocking" for d in cur)
        assert {d["gate"] for d in cur} == set(UI_GATES)

    def test_no_ui_all_not_applicable(self):
        cur = current_policy({"task_type": "QUICK"})
        assert all(d["applicability"] == "not_applicable" for d in cur)


@pytest.mark.unit
class TestCandidatePolicy:
    def test_candidate_none(self):
        cand = candidate_policy({"ui_impact": "none"})
        assert all(d["applicability"] == "not_applicable" for d in cand)

    def test_candidate_internal_advisory(self):
        cand = {d["gate"]: d for d in candidate_policy({"ui_changed": True, "ui_impact": "internal"})}
        assert all(cand[g]["enforcement"] == "advisory"
                   for g in ("ux_review", "visual_regression", "design_system_usage"))

    def test_candidate_internal_accessibility_blocking(self):
        cand = {d["gate"]: d for d in candidate_policy({"ui_changed": True, "ui_impact": "internal"})}
        assert cand["accessibility_review"]["enforcement"] == "blocking"

    def test_candidate_user_facing_all_blocking(self):
        cand = candidate_policy({"ui_changed": True, "ui_impact": "user_facing"})
        assert all(d["enforcement"] == "blocking" and d["applicability"] == "applicable" for d in cand)

    def test_candidate_critical_human_signoff(self):
        cand = {d["gate"]: d for d in candidate_policy({"ui_changed": True, "ui_impact": "critical"})}
        assert all(d["enforcement"] == "blocking" for d in cand.values())
        assert cand["ux_review"]["human_signoff"] and cand["accessibility_review"]["human_signoff"]


@pytest.mark.unit
class TestSafetyInvariant:
    def test_candidate_not_softer_user_facing(self):
        def _softer(a, b):
            rank = {"blocks": 2, "advises": 1, "skipped": 0}
            return rank[a] < rank[b]
        sig = {"ui_changed": True, "ui_impact": "user_facing"}
        cur_m = {d["gate"]: _effective(d) for d in current_policy(sig)}
        cand_m = {d["gate"]: _effective(d) for d in candidate_policy(sig)}
        assert not any(_softer(cand_m[g], cur_m[g]) for g in UI_GATES)

    def test_candidate_not_softer_critical(self):
        def _softer(a, b):
            rank = {"blocks": 2, "advises": 1, "skipped": 0}
            return rank[a] < rank[b]
        sig = {"ui_changed": True, "ui_impact": "critical"}
        cur_m = {d["gate"]: _effective(d) for d in current_policy(sig)}
        cand_m = {d["gate"]: _effective(d) for d in candidate_policy(sig)}
        assert not any(_softer(cand_m[g], cur_m[g]) for g in UI_GATES)

    def test_internal_only_non_safety_softened(self):
        def _softer(a, b):
            rank = {"blocks": 2, "advises": 1, "skipped": 0}
            return rank[a] < rank[b]
        sig = {"ui_changed": True, "ui_impact": "internal"}
        cur_i = {d["gate"]: _effective(d) for d in current_policy(sig)}
        cand_i = {d["gate"]: _effective(d) for d in candidate_policy(sig)}
        softened = {g for g in UI_GATES if _softer(cand_i[g], cur_i[g])}
        assert softened and not (softened & set(SAFETY_UI_GATES))


@pytest.mark.unit
class TestShadowDiff:
    def test_internal_would_unblock(self):
        sh = shadow_diff({"ui_changed": True, "ui_impact": "internal", "ui_change_kind": "component"})
        assert {d["gate"] for d in sh["differences"] if d["effect"] == "would_unblock"} == \
               {"ux_review", "visual_regression", "design_system_usage"}

    def test_user_facing_no_softening(self):
        sh = shadow_diff({"ui_changed": True, "ui_impact": "user_facing"})
        assert not [d for d in sh["differences"] if d["effect"] in ("would_unblock", "would_skip")]

    def test_none_no_differences(self):
        sh = shadow_diff({"ui_impact": "none"})
        assert not sh["differences"]


@pytest.mark.unit
class TestCandidateBlockingGates:
    def test_internal_blocking_set(self):
        sig = {"ui_changed": True, "ui_impact": "internal"}
        assert candidate_blocking_gates(sig) == {"accessibility_review"}

    def test_user_facing_blocking_set(self):
        assert candidate_blocking_gates({"ui_changed": True, "ui_impact": "user_facing"}) == set(UI_GATES)


@pytest.mark.unit
class TestEffectiveReviewOutcome:
    def test_evidence_fail_blocks_internal(self):
        assert effective_review_outcome("visual_regression",
                                        {"ui_changed": True, "ui_impact": "internal"},
                                        "warn", "fail")[0] == "block"

    def test_reviewer_fail_blocks(self):
        assert effective_review_outcome("ux_review",
                                        {"ui_changed": True, "ui_impact": "user_facing"},
                                        "fail", "not_run")[0] == "block"

    def test_internal_ux_warn_advisory(self):
        assert effective_review_outcome("ux_review",
                                        {"ui_changed": True, "ui_impact": "internal"},
                                        "warn", "not_run")[0] == "advisory"

    def test_internal_accessibility_warn_blocks(self):
        assert effective_review_outcome("accessibility_review",
                                        {"ui_changed": True, "ui_impact": "internal"},
                                        "warn", "not_run")[0] == "block"

    def test_user_facing_warn_evidence_pass_advisory(self):
        assert effective_review_outcome("visual_regression",
                                        {"ui_changed": True, "ui_impact": "user_facing"},
                                        "warn", "pass")[0] == "advisory"

    def test_user_facing_warn_no_evidence_blocks(self):
        assert effective_review_outcome("ux_review",
                                        {"ui_changed": True, "ui_impact": "user_facing"},
                                        "warn", "not_run")[0] == "block"

    def test_legacy_ui_changed_blocks(self):
        assert effective_review_outcome("ux_review", {"ui_changed": True},
                                        "warn", "not_run")[0] == "block"

    def test_user_facing_accessibility_evidence_pass(self):
        assert effective_review_outcome("accessibility_review",
                                        {"ui_changed": True, "ui_impact": "user_facing"},
                                        "warn", "pass")[0] == "advisory"

    def test_user_facing_accessibility_evidence_fail(self):
        assert effective_review_outcome("accessibility_review",
                                        {"ui_changed": True, "ui_impact": "user_facing"},
                                        "warn", "fail")[0] == "block"

    def test_critical_ux_evidence_pass_blocks(self):
        crit = {"ui_changed": True, "ui_impact": "critical"}
        assert effective_review_outcome("ux_review", crit, "warn", "pass")[0] == "block"

    def test_critical_accessibility_evidence_pass_blocks(self):
        crit = {"ui_changed": True, "ui_impact": "critical"}
        assert effective_review_outcome("accessibility_review", crit, "warn", "pass")[0] == "block"

    def test_critical_visual_evidence_pass_advisory(self):
        crit = {"ui_changed": True, "ui_impact": "critical"}
        assert effective_review_outcome("visual_regression", crit, "warn", "pass")[0] == "advisory"
