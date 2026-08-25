"""Granular tests for validate_security_domains (migrated from selftest)."""
from __future__ import annotations

import pytest

from validate_security_domains import (  # noqa: F401
    PKG,
    REQUIRED_DOMAINS,
    check,
    yaml,
)


@pytest.mark.unit
@pytest.mark.slow
class TestValidateSecurityDomains:
    """Validation of security-domains YAML structure."""

    def test_real_security_domains_yaml_is_valid(self):
        real = PKG / "security" / "security-domains.yaml"
        if real.exists():
            assert check(yaml.safe_load(real.read_text(encoding="utf-8"))) == []

    def test_synthetic_full_domain_set_is_valid(self):
        good = {
            "kind": "security-domains",
            "allowed_evidence_sources": ["secret_scan", "security_reviewer"],
            "domains": [
                {
                    "id": d,
                    "applicability": {"signals": [], "file_patterns": [".*"]},
                    "required_evidence": ["secret_scan"],
                    "severity_policy": {"default": "high"},
                    "remediation_template": {"summary": "fix"},
                }
                for d in REQUIRED_DOMAINS
            ],
        }
        assert check(good) == []

    def test_wrong_kind_produces_error(self):
        assert any("security-domains" in e for e in check({"kind": "x"}))

    def test_required_evidence_outside_allowed_produces_error(self):
        bad_ev = {
            "kind": "security-domains",
            "allowed_evidence_sources": ["secret_scan"],
            "domains": [
                {
                    "id": "secrets",
                    "applicability": {"file_patterns": [".*"]},
                    "required_evidence": ["magic"],
                    "severity_policy": {"default": "high"},
                    "remediation_template": {"summary": "x"},
                }
            ],
        }
        assert any("magic" in e for e in check(bad_ev))

    def test_unknown_severity_produces_error(self):
        bad_sev = {
            "kind": "security-domains",
            "allowed_evidence_sources": ["secret_scan"],
            "domains": [
                {
                    "id": "secrets",
                    "applicability": {"file_patterns": [".*"]},
                    "required_evidence": ["secret_scan"],
                    "severity_policy": {"default": "meh"},
                    "remediation_template": {"summary": "x"},
                }
            ],
        }
        assert any("severity_policy" in e for e in check(bad_sev))

    def test_incomplete_domain_set_produces_error(self):
        bad_sev = {
            "kind": "security-domains",
            "allowed_evidence_sources": ["secret_scan"],
            "domains": [
                {
                    "id": "secrets",
                    "applicability": {"file_patterns": [".*"]},
                    "required_evidence": ["secret_scan"],
                    "severity_policy": {"default": "meh"},
                    "remediation_template": {"summary": "x"},
                }
            ],
        }
        assert any("не хватает" in e for e in check(bad_sev))
