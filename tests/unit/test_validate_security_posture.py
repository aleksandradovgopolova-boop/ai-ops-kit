"""Granular tests for validate_security_posture (migrated from selftest)."""
from __future__ import annotations

import pytest

from validate_security_posture import (  # noqa: F401
    PKG,
    POSTURE,
    check,
    yaml,
)


@pytest.fixture(scope="module")
def real_posture():
    """Load the real posture YAML once."""
    return yaml.safe_load(POSTURE.read_text(encoding="utf-8"))


@pytest.mark.unit
@pytest.mark.slow
class TestValidateSecurityPosture:
    """Validation of security posture YAML."""

    def test_real_posture_is_valid_and_evidence_resolves(self, real_posture):
        e, tally = check(real_posture, PKG)
        assert e == []

    def test_real_posture_covers_all_13_areas(self, real_posture):
        assert len(real_posture.get("areas") or []) == 13

    def test_invalid_status_produces_error(self):
        bad = {
            "areas": [
                {
                    "id": "x",
                    "title": "t",
                    "status": "выдумка",
                    "severity": "high",
                    "evidence": ["nope/missing.md"],
                }
            ]
        }
        e2, _ = check(bad, PKG)
        assert any("status" in x for x in e2)

    def test_broken_evidence_path_produces_error(self):
        bad = {
            "areas": [
                {
                    "id": "x",
                    "title": "t",
                    "status": "выдумка",
                    "severity": "high",
                    "evidence": ["nope/missing.md"],
                }
            ]
        }
        e2, _ = check(bad, PKG)
        assert any("не резолвится" in x for x in e2)
