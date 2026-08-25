"""Granular tests for validate_key_lifecycle (migrated from selftest)."""
from __future__ import annotations

import pytest

from validate_key_lifecycle import (
    DEFAULT,
    check,
    yaml,
)


@pytest.fixture
def base_policy():
    return {
        "schema_version": 1,
        "kind": "KeyLifecyclePolicy",
        "policy_id": "KLP-001",
        "keys": [{"name": "anthropic", "env_ref": "ANTHROPIC_API_KEY",
                  "ttl_days": 90, "rotation_owner": "human"}],
        "per_agent_identity": {"supported": False,
                               "note": "единый ключ на движок; per-agent identity пока нет"},
    }


# --- Basic validation ---

class TestBasicValidation:
    @pytest.mark.unit
    def test_valid_policy_passes(self, base_policy):
        assert check(base_policy) == []

    @pytest.mark.unit
    def test_ttl_days_zero_is_error(self, base_policy):
        errs = check({**base_policy, "keys": [
            {"name": "k", "env_ref": "K", "ttl_days": 0, "rotation_owner": "human"}]})
        assert any("ttl_days" in x for x in errs)

    @pytest.mark.unit
    def test_missing_env_ref_is_error(self, base_policy):
        errs = check({**base_policy, "keys": [
            {"name": "k", "env_ref": "", "ttl_days": 30, "rotation_owner": "human"}]})
        assert any("env_ref" in x for x in errs)

    @pytest.mark.unit
    def test_secret_value_in_policy_is_error(self, base_policy):
        errs = check({**base_policy, "keys": [
            {"name": "k", "env_ref": "K", "ttl_days": 30, "rotation_owner": "human",
             "note": "sk-abcdefghijklmnop"}]})
        assert any("ЗНАЧЕНИЕ секрета" in x for x in errs)


# --- Per-agent identity ---

class TestPerAgentIdentity:
    @pytest.mark.unit
    def test_supported_true_without_evidence(self, base_policy):
        errs = check({**base_policy,
                       "per_agent_identity": {"supported": True, "note": "есть"}})
        assert any("без доказательства" in x for x in errs)

    @pytest.mark.unit
    def test_supported_true_with_evidence(self, base_policy):
        assert check({**base_policy,
                       "per_agent_identity": {"supported": True, "note": "mTLS per agent",
                                              "evidence": ["spiffe-id"]}}) == []

    @pytest.mark.unit
    def test_missing_per_agent_identity(self, base_policy):
        errs = check({k: v for k, v in base_policy.items() if k != "per_agent_identity"})
        assert any("per_agent_identity" in x for x in errs)


# --- Real file ---

class TestRealFile:
    @pytest.mark.slow
    @pytest.mark.unit
    def test_real_default_policy_is_valid(self):
        if DEFAULT.exists():
            errs = check(yaml.safe_load(DEFAULT.read_text(encoding="utf-8")))
            assert errs == [], "\n".join(str(x) for x in errs)
