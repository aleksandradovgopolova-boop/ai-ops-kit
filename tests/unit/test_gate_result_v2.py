"""Гранулярные тесты gate_result_v2 (мигрировано из test_gate_result_v2_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]

from ai_ops_kit.gates.gate_result_v2 import (
    STATUS_V2,
    calibrated_view,
    check,
    json,
    to_v1,
)


@pytest.mark.unit
class TestCheckAbstain:
    def test_valid_abstain_advisory(self):
        valid = {"schema_version": 2, "gate": "visual_regression", "status": "abstain",
                 "blocking": True, "applicability": "applicable", "enforcement": "advisory",
                 "evidence_mode": "deterministic", "owner": "r", "review_mode": "read-only",
                 "blockers": [], "warnings": ["w"]}
        assert check(valid) == []

    def test_abstain_blocking_without_pending_human(self):
        valid = {"schema_version": 2, "gate": "visual_regression", "status": "abstain",
                 "blocking": True, "applicability": "applicable", "enforcement": "advisory",
                 "evidence_mode": "deterministic", "owner": "r", "review_mode": "read-only",
                 "blockers": [], "warnings": ["w"]}
        assert any("blocking-abstain" in x for x in check({**valid, "enforcement": "blocking"}))

    def test_blocking_abstain_pending_human_valid(self):
        blocking = {"schema_version": 2, "gate": "accessibility_review", "status": "abstain",
                    "blocking": True, "applicability": "applicable", "enforcement": "blocking",
                    "evidence_mode": "hybrid", "owner": "a11y", "review_mode": "read-only",
                    "reviewer_outcome": "abstain", "resolution": "pending_human",
                    "delivery_allowed": False, "human_handoff": True,
                    "blockers": ["reviewer abstain x2 -> человек"], "warnings": []}
        assert check(blocking) == []

    def test_blocking_abstain_delivery_allowed_error(self):
        blocking = {"schema_version": 2, "gate": "accessibility_review", "status": "abstain",
                    "blocking": True, "applicability": "applicable", "enforcement": "blocking",
                    "evidence_mode": "hybrid", "owner": "a11y", "review_mode": "read-only",
                    "reviewer_outcome": "abstain", "resolution": "pending_human",
                    "delivery_allowed": False, "human_handoff": True,
                    "blockers": ["reviewer abstain x2 -> человек"], "warnings": []}
        assert any("blocking-abstain" in x for x in check({**blocking, "delivery_allowed": True}))

    def test_to_v1_blocking_abstain(self):
        blocking = {"schema_version": 2, "gate": "accessibility_review", "status": "abstain",
                    "blocking": True, "applicability": "applicable", "enforcement": "blocking",
                    "evidence_mode": "hybrid", "owner": "a11y", "review_mode": "read-only",
                    "reviewer_outcome": "abstain", "resolution": "pending_human",
                    "delivery_allowed": False, "human_handoff": True,
                    "blockers": ["reviewer abstain x2 -> человек"], "warnings": []}
        v1 = to_v1(blocking)
        assert v1["status"] == "fail" and v1["blockers"]


@pytest.mark.unit
class TestCheckNotApplicable:
    def test_valid_not_applicable(self):
        na = {"schema_version": 2, "gate": "ux_review", "status": "not_applicable", "blocking": True,
              "applicability": "not_applicable", "enforcement": "advisory", "owner": "r",
              "review_mode": "read-only"}
        assert check(na) == []

    def test_not_applicable_wrong_applicability(self):
        na = {"schema_version": 2, "gate": "ux_review", "status": "not_applicable", "blocking": True,
              "applicability": "not_applicable", "enforcement": "advisory", "owner": "r",
              "review_mode": "read-only"}
        assert any("not_applicable" in x for x in check({**na, "applicability": "applicable"}))


@pytest.mark.unit
class TestCheckFail:
    def test_valid_fail_with_blockers(self):
        fail = {"schema_version": 2, "gate": "ux_review", "status": "fail", "blocking": True,
                "applicability": "applicable", "enforcement": "blocking", "owner": "r",
                "review_mode": "read-only", "blockers": ["нет состояний экрана"]}
        assert check(fail) == []

    def test_fail_without_blockers(self):
        fail = {"schema_version": 2, "gate": "ux_review", "status": "fail", "blocking": True,
                "applicability": "applicable", "enforcement": "blocking", "owner": "r",
                "review_mode": "read-only", "blockers": ["нет состояний экрана"]}
        assert any("blockers" in x for x in check({**fail, "blockers": []}))

    def test_extra_key_error(self):
        fail = {"schema_version": 2, "gate": "ux_review", "status": "fail", "blocking": True,
                "applicability": "applicable", "enforcement": "blocking", "owner": "r",
                "review_mode": "read-only", "blockers": ["нет состояний экрана"]}
        assert any("лишний" in x for x in check({**fail, "junk": 1}))


@pytest.mark.unit
class TestToV1:
    def test_not_applicable_none(self):
        na = {"schema_version": 2, "gate": "ux_review", "status": "not_applicable", "blocking": True,
              "applicability": "not_applicable", "enforcement": "advisory", "owner": "r",
              "review_mode": "read-only"}
        assert to_v1(na) is None

    def test_abstain_to_warn(self):
        abstain = {"schema_version": 2, "gate": "visual_regression", "status": "abstain",
                   "blocking": True, "applicability": "applicable", "enforcement": "advisory",
                   "evidence_mode": "deterministic", "owner": "r", "review_mode": "read-only",
                   "blockers": [], "warnings": ["w"]}
        v1 = to_v1(abstain)
        assert v1["status"] == "warn" and v1["schema_version"] == 1

    def test_fail_to_fail(self):
        fail = {"schema_version": 2, "gate": "ux_review", "status": "fail", "blocking": True,
                "applicability": "applicable", "enforcement": "blocking", "owner": "r",
                "review_mode": "read-only", "blockers": ["нет состояний экрана"]}
        v1 = to_v1(fail)
        assert v1["status"] == "fail" and v1["blockers"]


@pytest.mark.unit
class TestCalibratedView:
    def test_advisory_abstain(self):
        from ai_ops_kit.gates import gate_policy
        dec = {d["gate"]: d for d in gate_policy.candidate_policy(
            {"ui_changed": True, "ui_impact": "internal"})}["ux_review"]
        view = calibrated_view("ux_review", True, dec, "warn", "advisory",
                               "internal low-risk -> advisory")
        assert view["status"] == "abstain" and check(view) == []

    def test_block_fail(self):
        from ai_ops_kit.gates import gate_policy
        dec = {d["gate"]: d for d in gate_policy.candidate_policy(
            {"ui_changed": True, "ui_impact": "user_facing"})}["ux_review"]
        view = calibrated_view("ux_review", True, dec, "warn", "block",
                               "fail-closed", blockers=["no evidence"])
        assert view["status"] == "fail" and check(view) == [] and view["blockers"]


@pytest.mark.unit
class TestDriftGuard:
    def test_status_enum_matches_schema(self):
        sch = json.loads((PKG_ROOT / "schemas"
                          / "gate-result-v2.schema.json").read_text(encoding="utf-8"))
        enum = set(sch["properties"]["status"]["enum"])
        assert enum == STATUS_V2
