"""Гранулярные тесты gate_runtime (мигрировано из test_gate_runtime_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import pytest

from gate_runtime import (
    can_deliver,
    decide,
    gate_result_v2,
)


def _valid(r):
    return gate_result_v2.check(r) == []


@pytest.mark.unit
class TestDecide:
    def test_pass(self):
        uf = {"ui_changed": True, "ui_impact": "user_facing"}
        r, m = decide("ux_review", uf, ["pass"])
        assert r["status"] == "pass" and _valid(r) and not m["human_handoff"]

    def test_fail(self):
        uf = {"ui_changed": True, "ui_impact": "user_facing"}
        r, m = decide("ux_review", uf, ["fail"])
        assert r["status"] == "fail" and r["enforcement"] == "blocking" and r["blockers"] and _valid(r)

    def test_warn_internal_advisory(self):
        intn = {"ui_changed": True, "ui_impact": "internal"}
        r, m = decide("ux_review", intn, ["warn"])
        assert r["status"] == "abstain" and r["enforcement"] == "advisory" and _valid(r)
        assert m["terminal"] == "abstain-advisory"

    def test_warn_user_facing_no_evidence(self):
        uf = {"ui_changed": True, "ui_impact": "user_facing"}
        r, m = decide("ux_review", uf, ["warn"], evidence_status="not_run")
        assert r["status"] == "fail" and _valid(r)

    def test_warn_evidence_pass(self):
        uf = {"ui_changed": True, "ui_impact": "user_facing"}
        r, m = decide("visual_regression", uf, ["warn"], evidence_status="pass")
        assert r["status"] == "abstain" and _valid(r)

    def test_abstain_retry_pass(self):
        uf = {"ui_changed": True, "ui_impact": "user_facing"}
        r, m = decide("ux_review", uf, ["abstain", "pass"], max_retries=1)
        assert r["status"] == "pass" and m["retries"] == 1

    def test_repeated_abstain_blocking_handoff(self):
        uf = {"ui_changed": True, "ui_impact": "user_facing"}
        r, m = decide("ux_review", uf, ["abstain", "abstain"], max_retries=1)
        assert r["status"] == "abstain" and r["enforcement"] == "blocking"
        assert r["resolution"] == "pending_human" and r["delivery_allowed"] is False
        assert r["human_handoff"] is True and m["human_handoff"] is True and _valid(r)

    def test_to_v1_blocking_abstain_fail(self):
        uf = {"ui_changed": True, "ui_impact": "user_facing"}
        r, m = decide("ux_review", uf, ["abstain", "abstain"], max_retries=1)
        assert gate_result_v2.to_v1(r)["status"] == "fail"

    def test_no_verdict_blocking_handoff(self):
        uf = {"ui_changed": True, "ui_impact": "user_facing"}
        r, m = decide("ux_review", uf, [])
        assert m["human_handoff"] is True and r["enforcement"] == "blocking"
        assert r["delivery_allowed"] is False and _valid(r)

    def test_not_applicable(self):
        r, m = decide("ux_review", {"ui_impact": "none"}, ["warn"])
        assert r["status"] == "not_applicable" and r["applicability"] == "not_applicable" and _valid(r)

    def test_to_v1_abstain_warn(self):
        intn = {"ui_changed": True, "ui_impact": "internal"}
        r, _ = decide("ux_review", intn, ["warn"])
        v1 = gate_result_v2.to_v1(r)
        assert v1 and v1["status"] == "warn"


@pytest.mark.unit
class TestTestedRevision:
    def test_revision_stamped(self):
        uf = {"ui_changed": True, "ui_impact": "user_facing"}
        r, _ = decide("ux_review", uf, ["pass"], tested_revision="sha1", evidence=["reviewed @ sha1"])
        assert r["tested_revision"] == "sha1" and r["evidence"] == ["reviewed @ sha1"]

    def test_revision_matches(self):
        uf = {"ui_changed": True, "ui_impact": "user_facing"}
        r, _ = decide("ux_review", uf, ["pass"], tested_revision="sha1", evidence=["reviewed @ sha1"])
        ok, bl = can_deliver([r], expected_revision="sha1")
        assert ok is True

    def test_revision_mismatch(self):
        uf = {"ui_changed": True, "ui_impact": "user_facing"}
        r, _ = decide("ux_review", uf, ["pass"], tested_revision="sha1", evidence=["reviewed @ sha1"])
        ok, bl = can_deliver([r], expected_revision="sha2")
        assert ok is False and any("другом SHA" in b for b in bl)

    def test_no_revision_with_expected(self):
        uf = {"ui_changed": True, "ui_impact": "user_facing"}
        p, _ = decide("ux_review", uf, ["pass"])
        ok, bl = can_deliver([p], expected_revision="sha1")
        assert ok is False and any("не привязан к SHA" in b for b in bl)


@pytest.mark.unit
class TestCanDeliver:
    def test_pass_and_advisory(self):
        uf = {"ui_changed": True, "ui_impact": "user_facing"}
        intn = {"ui_changed": True, "ui_impact": "internal"}
        p, _ = decide("ux_review", uf, ["pass"])
        adv, _ = decide("ux_review", intn, ["warn"])
        ok, bl = can_deliver([p, adv])
        assert ok is True and bl == []

    def test_blocking_abstain_forbids(self):
        uf = {"ui_changed": True, "ui_impact": "user_facing"}
        p, _ = decide("ux_review", uf, ["pass"])
        ba, _ = decide("accessibility_review", uf, ["abstain", "abstain"])
        ok, bl = can_deliver([p, ba])
        assert ok is False and any("pending_human" in b for b in bl)
