"""Granular tests for validate_memory_governance (migrated from selftest)."""
from __future__ import annotations

import pytest

from validate_memory_governance import (
    DEFAULT,
    check,
    yaml,
)


@pytest.fixture
def base_policy():
    return {
        "schema_version": 1,
        "kind": "MemoryGovernancePolicy",
        "policy_id": "MGP-001",
        "entries": [{"id": "m1",
                      "provenance": {"origin": "user", "source_type": "human"},
                      "expiry": {"mode": "ttl_days", "value": 90},
                      "self_ingested": False}],
    }


# --- Basic validation ---

class TestBasicValidation:
    @pytest.mark.unit
    def test_valid_policy_passes(self, base_policy):
        assert check(base_policy) == []

    @pytest.mark.unit
    def test_missing_provenance_origin(self, base_policy):
        errs = check({**base_policy, "entries": [
            {"id": "m", "provenance": {"source_type": "human"},
             "expiry": {"mode": "ttl_days", "value": 1}, "self_ingested": False}]})
        assert any("provenance.origin" in x for x in errs)

    @pytest.mark.unit
    def test_derived_without_upstream(self, base_policy):
        errs = check({**base_policy, "entries": [
            {"id": "m", "provenance": {"origin": "o", "source_type": "derived"},
             "expiry": {"mode": "permanent", "justification": "j"}, "self_ingested": False}]})
        assert any("upstream" in x for x in errs)

    @pytest.mark.unit
    def test_permanent_without_justification(self, base_policy):
        errs = check({**base_policy, "entries": [
            {"id": "m", "provenance": {"origin": "o", "source_type": "human"},
             "expiry": {"mode": "permanent"}, "self_ingested": False}]})
        assert any("justification" in x for x in errs)

    @pytest.mark.unit
    def test_ttl_days_zero(self, base_policy):
        errs = check({**base_policy, "entries": [
            {"id": "m", "provenance": {"origin": "o", "source_type": "human"},
             "expiry": {"mode": "ttl_days", "value": 0}, "self_ingested": False}]})
        assert any("ttl_days" in x for x in errs)


# --- Self-ingestion ---

class TestSelfIngestion:
    @pytest.mark.unit
    def test_self_ingested_without_human_confirmed(self, base_policy):
        errs = check({**base_policy, "entries": [
            {"id": "m", "provenance": {"origin": "agent", "source_type": "system"},
             "expiry": {"mode": "ttl_days", "value": 7}, "self_ingested": True}]})
        assert any("self-ingestion" in x for x in errs)

    @pytest.mark.unit
    def test_self_ingested_with_human_confirmed(self, base_policy):
        assert check({**base_policy, "entries": [
            {"id": "m", "provenance": {"origin": "agent", "source_type": "system"},
             "expiry": {"mode": "ttl_days", "value": 7},
             "self_ingested": True, "human_confirmed": True}]}) == []


# --- Real file ---

class TestRealFile:
    @pytest.mark.slow
    @pytest.mark.unit
    def test_real_default_policy_is_valid(self):
        if DEFAULT.exists():
            errs = check(yaml.safe_load(DEFAULT.read_text(encoding="utf-8")))
            assert errs == [], "\n".join(str(x) for x in errs)
