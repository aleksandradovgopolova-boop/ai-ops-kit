"""Granular tests for validate_run_handoff (migrated from selftest)."""
from __future__ import annotations

import pytest

from validate_run_handoff import (  # noqa: F401
    PKG,
    check,
    json,
    sys,
)


@pytest.fixture
def valid_handoff():
    return {
        "kind": "RunHandoff", "workitem_id": "x", "next_action": "продолжить",
        "verification": {"passed": ["a"], "failed": []},
        "completed": [], "decisions": [{"id": "d1", "summary": "s"}],
        "changed_files": [], "open_questions": [], "known_risks": [],
        "resume_from_revision": "a" * 40,
    }


@pytest.mark.unit
def test_valid_handoff_no_errors(valid_handoff):
    assert check(valid_handoff) == []


@pytest.mark.unit
def test_wrong_kind_raises():
    assert any("RunHandoff" in e for e in check({"kind": "x"}))


@pytest.mark.unit
def test_missing_next_action_raises(valid_handoff):
    no_next = json.loads(json.dumps(valid_handoff))
    del no_next["next_action"]
    assert any("next_action" in e for e in check(no_next))


@pytest.mark.unit
def test_verification_without_failed_raises(valid_handoff):
    bad_ver = json.loads(json.dumps(valid_handoff))
    bad_ver["verification"] = {"passed": []}
    assert any("verification" in e for e in check(bad_ver))


@pytest.mark.unit
def test_decision_without_id_raises(valid_handoff):
    bad_dec = json.loads(json.dumps(valid_handoff))
    bad_dec["decisions"] = [{"summary": "s"}]
    assert any("decisions[0]" in e for e in check(bad_dec))


@pytest.mark.unit
def test_null_resume_from_revision_is_valid(valid_handoff):
    null_rev = json.loads(json.dumps(valid_handoff))
    null_rev["resume_from_revision"] = None
    assert check(null_rev) == []


@pytest.mark.unit
def test_real_build_handoff_is_valid():
    from ai_ops_kit.engine import run_handoff
    h = run_handoff.build_handoff({
        "workitem_id": "f", "ready_for_pr": True,
        "commit": {"sha": "c" * 40, "branch": "ai-ops/f", "evidence_on_exact_sha": True},
        "loop": {"applied_writes": 1, "stopped": "done"},
        "gates": {"evaluated": ["requirements"], "unmet": []},
        "not_yet": [], "checks": {},
    })
    assert check(h) == []
