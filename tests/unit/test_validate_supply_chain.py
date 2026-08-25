"""Granular tests for validate_supply_chain (migrated from selftest)."""
from __future__ import annotations

import pytest

from validate_supply_chain import (  # noqa: F401
    DEFAULT,
    check,
    yaml,
)


@pytest.fixture
def good_scp():
    return {
        "schema_version": 1,
        "kind": "SupplyChainPinPolicy",
        "policy_id": "SCP-001",
        "dependencies": [
            {
                "name": "claude-sonnet",
                "kind": "model",
                "source": "anthropic",
                "pinned": {"type": "revision", "value": "claude-sonnet-5-20260101"},
            },
            {
                "name": "figma-mcp",
                "kind": "mcp",
                "source": "github.com/x/figma-mcp",
                "pinned": {"type": "hash", "value": "a1b2c3d4e5f6"},
                "install_verify": {"method": "sha256", "value": "deadbeefdeadbeef"},
            },
        ],
    }


@pytest.mark.unit
@pytest.mark.slow
class TestValidateSupplyChain:
    """Validation of supply-chain pin policies."""

    def test_valid_scp_passes(self, good_scp):
        assert check(good_scp) == []

    def test_floating_latest_produces_error(self, good_scp):
        assert any(
            "плавающ" in x
            for x in check(
                {
                    **good_scp,
                    "dependencies": [
                        {
                            "name": "m",
                            "kind": "model",
                            "source": "s",
                            "pinned": {"type": "revision", "value": "latest"},
                        }
                    ],
                }
            )
        )

    def test_mcp_without_install_verify_produces_error(self, good_scp):
        assert any(
            "install_verify" in x
            for x in check(
                {
                    **good_scp,
                    "dependencies": [
                        {
                            "name": "srv",
                            "kind": "mcp",
                            "source": "s",
                            "pinned": {"type": "hash", "value": "abcdef1"},
                        }
                    ],
                }
            )
        )

    def test_non_hex_hash_produces_error(self, good_scp):
        assert any(
            "hex-hash" in x
            for x in check(
                {
                    **good_scp,
                    "dependencies": [
                        {
                            "name": "m",
                            "kind": "model",
                            "source": "s",
                            "pinned": {"type": "hash", "value": "not-a-hash!"},
                        }
                    ],
                }
            )
        )

    def test_no_pinned_produces_error(self, good_scp):
        assert any(
            "pinned" in x
            for x in check(
                {
                    **good_scp,
                    "dependencies": [{"name": "m", "kind": "model", "source": "s"}],
                }
            )
        )

    def test_duplicate_dependency_produces_error(self, good_scp):
        assert any(
            "дубликат" in x
            for x in check(
                {**good_scp, "dependencies": good_scp["dependencies"] + [good_scp["dependencies"][0]]}
            )
        )

    def test_real_default_policy_is_valid(self):
        if DEFAULT.exists():
            errs = check(yaml.safe_load(DEFAULT.read_text(encoding="utf-8")))
            assert errs == []
