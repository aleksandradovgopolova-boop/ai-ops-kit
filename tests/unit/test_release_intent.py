"""Необязательное намерение выпуска: факты/параметры, без объявленной готовности."""
from copy import deepcopy

import pytest

from ai_ops_kit.planning import plan_model, plan_validate


def plan(intent=None, *, present=True):
    data = {
        "schema_version": 1, "kind": "delivery-plan",
        "goals": [{"id": "ship", "status": "active", "freeze_relation": "run_condition",
                   "outcome": {"verified": False}}], "work": [],
    }
    if present:
        data["release_intent"] = deepcopy(intent)
    return data


def test_absent_intent_preserves_legacy_plan():
    data = plan(present=False)
    assert plan_model.release_intent(data) is None
    assert not plan_validate.validate(data)["errors"]


def test_intent_is_a_validated_parameter_block_not_a_status():
    intent = {"id": "kit-next-release", "milestone": "Проверенный выпуск",
              "candidate_limit": 0,
              "deferred": {"cycle_version": "4.12.0", "issues": [1412, 1439]}}
    data = plan(intent)
    assert plan_model.release_intent(data) == intent
    assert not plan_validate.validate(data)["errors"]


@pytest.mark.parametrize("intent", [None, False, [], "ready", {},
    {"id": "bad/id", "milestone": "x", "candidate_limit": 0},
    {"id": "kit", "milestone": "", "candidate_limit": 0},
    {"id": "kit", "milestone": "x", "candidate_limit": False},
    {"id": "kit", "milestone": "x", "candidate_limit": -1},
    {"id": "kit", "milestone": "x", "candidate_limit": 1},
    {"id": "kit", "milestone": "x", "candidate_limit": 0, "ready": True},
    {"id": "kit", "milestone": "x", "candidate_limit": 0,
     "deferred": {"cycle_version": "4.12.0", "issues": [True]}},
    {"id": "kit", "milestone": "x", "candidate_limit": 0,
     "deferred": {"cycle_version": "4.12.0", "issues": [2, 2]}},
    {"id": "kit", "milestone": "x", "candidate_limit": 0,
     "deferred": {"cycle_version": "latest", "issues": [2]}},
])
def test_malformed_present_intent_fails_closed(intent):
    before = deepcopy(intent)
    errors = plan_validate.validate(plan(intent))["errors"]
    assert any("release_intent" in error for error in errors)
    assert intent == before


def test_validation_has_no_write_or_status_side_effect(tmp_path):
    target = tmp_path / "owner.txt"
    target.write_text("не менять")
    data = plan({"id": "kit", "milestone": "x", "candidate_limit": 0})
    before = deepcopy(data)
    assert not plan_validate.validate(data)["errors"]
    assert data == before
    assert target.read_text() == "не менять"
    assert list(tmp_path.iterdir()) == [target]
