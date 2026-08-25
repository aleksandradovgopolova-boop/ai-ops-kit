"""Granular tests for validate_feature_learning (migrated from selftest)."""
from __future__ import annotations

import tempfile

import pytest

from validate_feature_learning import (
    DEFAULT_DIR,
    Path,
    SCHEMA,
    VERDICT,
    check,
    check_registry,
    json,
    yaml,
)


@pytest.fixture
def schema_example():
    """First example from the JSON schema."""
    return json.loads(SCHEMA.read_text(encoding="utf-8"))["examples"][0]


@pytest.fixture
def confirmed_example(schema_example):
    """Example with confirmed outcome."""
    return {**schema_example, "outcome": {"verdict": "confirmed", "expected": "e", "actual": "a"}}


# --- Schema & registry ---

class TestSchemaAndRegistry:
    @pytest.mark.unit
    def test_schema_example_is_valid(self, schema_example):
        assert check(schema_example) == []

    @pytest.mark.slow
    @pytest.mark.unit
    def test_real_product_learning_registry_is_consistent(self):
        reg_errs, ids = check_registry(DEFAULT_DIR)
        assert reg_errs == [], f"{len(ids)} FL checked"

    @pytest.mark.unit
    def test_enum_verdict_matches_schema(self):
        sch = json.loads(SCHEMA.read_text(encoding="utf-8"))
        assert set(sch["properties"]["outcome"]["properties"]["verdict"]["enum"]) == VERDICT


# --- Validation errors ---

class TestValidationErrors:
    @pytest.mark.unit
    def test_verdict_without_validation_done(self, schema_example):
        errs = check({**schema_example,
                       "validation": {"method": "m", "status": "running", "result": None},
                       "status": "open"})
        assert any("validation.status=done" in x for x in errs)

    @pytest.mark.unit
    def test_verdict_without_result(self, schema_example):
        errs = check({**schema_example,
                       "validation": {"method": "m", "status": "done", "result": ""}})
        assert any("result" in x for x in errs)

    @pytest.mark.unit
    def test_refuted_without_learnings(self, schema_example):
        errs = check({**schema_example,
                       "outcome": {"verdict": "refuted", "expected": "e", "actual": "a"},
                       "learnings": []})
        assert any("learnings" in x for x in errs)

    @pytest.mark.unit
    def test_status_validated_with_unfinished_check(self, schema_example):
        errs = check({**schema_example, "status": "validated",
                       "validation": {"method": "m", "status": "planned", "result": None},
                       "outcome": {"verdict": "pending"}})
        assert any("validated" in x for x in errs)

    @pytest.mark.unit
    def test_status_closed_with_pending_verdict(self, schema_example):
        errs = check({**schema_example, "status": "closed",
                       "outcome": {"verdict": "pending"}})
        assert any("closed" in x for x in errs)

    @pytest.mark.unit
    def test_broken_id(self, schema_example):
        errs = check({**schema_example, "id": "FL1"})
        assert any("id" in x for x in errs)

    @pytest.mark.unit
    def test_broken_decision_package(self, schema_example):
        errs = check({**schema_example, "decision_package": "108"})
        assert any("decision_package" in x for x in errs)

    @pytest.mark.unit
    def test_decision_package_null_is_valid(self, schema_example):
        assert check({**schema_example, "decision_package": None}) == []

    @pytest.mark.unit
    def test_broken_supersedes(self, schema_example):
        errs = check({**schema_example, "supersedes": "FL1"})
        assert any("supersedes" in x for x in errs)


# --- Registry edge cases ---

class TestRegistryEdgeCases:
    @pytest.mark.unit
    def test_registry_catches_filename_mismatch_with_id(self, schema_example):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "FL-050.yaml").write_text(
                yaml.safe_dump({**schema_example, "id": "FL-777"}), encoding="utf-8")
            e, _ = check_registry(Path(td))
            assert any("имя файла" in x for x in e)


# --- Completion semantics (v3.3.3) ---

class TestCompletionSemantics:
    @pytest.mark.unit
    def test_refuted_without_decision_change_stop_investigate(self, schema_example):
        errs = check({**schema_example,
                       "outcome": {"verdict": "refuted", "expected": "e", "actual": "a"},
                       "learnings": ["урок"], "decision": "continue"})
        assert any("refuted требует decision" in x for x in errs)

    @pytest.mark.unit
    def test_decision_scale_with_unconfirmed_verdict(self, schema_example):
        errs = check({**schema_example,
                       "outcome": {"verdict": "inconclusive", "expected": "e", "actual": "a"},
                       "decision": "scale"})
        assert any("verdict=confirmed" in x for x in errs)

    @pytest.mark.unit
    def test_decision_investigate_without_research_gap(self, schema_example):
        errs = check({**schema_example,
                       "outcome": {"verdict": "pending"},
                       "validation": {"method": "m", "status": "planned", "result": None},
                       "decision": "investigate", "status": "open"})
        assert any("research_gap" in x for x in errs)

    @pytest.mark.unit
    def test_decision_investigate_with_research_gap_is_valid(self, schema_example):
        assert check({**schema_example,
                       "outcome": {"verdict": "pending"},
                       "validation": {"method": "m", "status": "planned", "result": None},
                       "decision": "investigate", "research_gap": "нет измерения",
                       "status": "open"}) == []

    @pytest.mark.unit
    def test_outcome_achieved_true_with_unconfirmed(self, confirmed_example):
        errs = check({**confirmed_example,
                       "outcome": {"verdict": "inconclusive"},
                       "completion": {"outcome_achieved": True}})
        assert any("outcome_achieved" in x for x in errs)

    @pytest.mark.unit
    def test_status_closed_without_learning_complete(self, confirmed_example):
        errs = check({**confirmed_example, "status": "closed",
                       "decision": "scale",
                       "completion": {"learning_complete": False}})
        assert any("learning_complete" in x for x in errs)

    @pytest.mark.unit
    def test_status_closed_without_decision(self, confirmed_example):
        errs = check({**confirmed_example, "status": "closed",
                       "completion": {"learning_complete": True}})
        assert any("decision" in x for x in errs)

    @pytest.mark.unit
    def test_solution_options_without_exactly_one_chosen(self, confirmed_example):
        errs = check({**confirmed_example, "solution_options": [
            {"option": "a", "chosen": True, "reason": "r"},
            {"option": "b", "chosen": True, "reason": "r"}]})
        assert any("chosen=true" in x for x in errs)
