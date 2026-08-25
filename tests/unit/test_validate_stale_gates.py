"""Granular tests for validate_stale_gates (migrated from selftest)."""
from __future__ import annotations

import pytest

from validate_stale_gates import (  # noqa: F401
    Path,
    json,
    scan,
    sha256,
    tempfile,
)


@pytest.fixture
def gate_setup():
    """Create a temp directory with a gate and artifact."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        art = root / "change" / "requirements.md"
        art.parent.mkdir(parents=True)
        art.write_text("v1", encoding="utf-8")
        gate = root / "change" / "gates" / "requirements.gate.json"
        gate.parent.mkdir(parents=True)
        gate.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "gate": "requirements",
                    "status": "pass",
                    "blocking": True,
                    "owner": "requirements-reviewer",
                    "review_mode": "read-only",
                    "artifact_hashes": {
                        "change/requirements.md": "sha256:" + sha256(art)
                    },
                    "tested_revision": None,
                    "expires_at": None,
                }
            ),
            encoding="utf-8",
        )
        yield root, art, gate


@pytest.mark.unit
@pytest.mark.slow
class TestValidateStaleGates:
    """Detection of stale gates."""

    def test_fresh_gate_not_stale(self, gate_setup):
        root, art, gate = gate_setup
        _, stale_blocks, _, _ = scan(root)
        assert not stale_blocks

    def test_modified_artifact_becomes_stale(self, gate_setup):
        root, art, gate = gate_setup
        art.write_text("v2 — изменили требования", encoding="utf-8")
        _, stale_blocks, _, _ = scan(root)
        assert stale_blocks and "изменён" in stale_blocks[0][1][0]

    def test_expired_gate_becomes_stale(self, gate_setup):
        root, art, gate = gate_setup
        art.write_text("v1", encoding="utf-8")
        g = json.loads(gate.read_text(encoding="utf-8"))
        g["expires_at"] = "2000-01-01T00:00:00Z"
        gate.write_text(json.dumps(g), encoding="utf-8")
        _, stale_blocks, _, _ = scan(root)
        assert stale_blocks and any("expires_at" in r for r in stale_blocks[0][1])
