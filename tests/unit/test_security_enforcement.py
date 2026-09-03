"""Гранулярные тесты security_enforcement (мигрировано из test_security_enforcement_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.security.security_enforcement import (
    PKG,
    enforce_memory_entry,
    hashlib,
    key_preflight,
    verify_artifact,
)


@pytest.mark.unit
class TestVerifyArtifact:
    def test_matching_sha256_ok(self):
        data = b"skill-bytes-v1"
        digest = hashlib.sha256(data).hexdigest()
        ok, _ = verify_artifact(data, {"kind": "skill", "install_verify": {"method": "sha256", "value": digest}})
        assert ok is True

    def test_tampered_bytes_fail(self):
        data = b"skill-bytes-v1"
        digest = hashlib.sha256(data).hexdigest()
        ok, _ = verify_artifact(b"tampered", {"kind": "skill", "install_verify": {"method": "sha256", "value": digest}})
        assert ok is False

    def test_signature_offline_blocked(self):
        data = b"skill-bytes-v1"
        ok, _ = verify_artifact(data, {"kind": "mcp", "install_verify": {"method": "signature", "value": "x"}})
        assert ok is False

    def test_no_install_verify_blocked(self):
        ok, _ = verify_artifact(b"", {"kind": "mcp"})
        assert ok is False

    def test_model_without_install_verify_ok(self):
        ok, _ = verify_artifact(b"", {"kind": "model"})
        assert ok is True


@pytest.mark.unit
class TestEnforceMemoryEntry:
    def test_valid_entry_ok(self):
        good = {"id": "m1", "provenance": {"origin": "user", "source_type": "human"},
                "expiry": {"mode": "ttl_days", "value": 30}, "self_ingested": False}
        ok, _ = enforce_memory_entry(good)
        assert ok is True

    def test_self_ingested_without_confirm_rejected(self):
        bad = {"id": "m2", "provenance": {"origin": "agent", "source_type": "system"},
               "expiry": {"mode": "ttl_days", "value": 7}, "self_ingested": True}
        ok, viol = enforce_memory_entry(bad)
        assert ok is False
        assert viol


@pytest.mark.unit
class TestKeyPreflight:
    @pytest.fixture
    def klp(self):
        return {"keys": [
            {"name": "a", "env_ref": "AKEY", "ttl_days": 90, "rotation_owner": "human"},
            {"name": "b", "env_ref": "BKEY", "ttl_days": 30, "rotation_owner": "human"},
        ]}

    def test_non_critical_missing_key_warning(self, klp):
        rep = key_preflight(klp, {"AKEY": "x"}, critical=False)
        assert rep["ready"]
        assert rep["warnings"]

    def test_critical_missing_key_blocks(self, klp):
        rep = key_preflight(klp, {"AKEY": "x"}, critical=True)
        assert rep["ready"] is False
        assert rep["blocks"]

    def test_critical_all_keys_ready(self, klp):
        rep = key_preflight(klp, {"AKEY": "x", "BKEY": "y"}, critical=True)
        assert rep["ready"] is True


@pytest.mark.unit
class TestKeyPreflightTTL:
    @pytest.fixture
    def klp_ttl(self):
        return {"keys": [{"name": "K", "env_ref": "AKEY", "next_rotation_at": "2026-01-01"}]}

    def test_overdue_rotation_blocks(self, klp_ttl):
        r = key_preflight(klp_ttl, {"AKEY": "x"}, critical=True, now="2026-07-28")
        assert r["ready"] is False
        assert any("ротация просрочена" in b for b in r["blocks"])

    def test_before_deadline_ready(self, klp_ttl):
        assert key_preflight(klp_ttl, {"AKEY": "x"}, critical=True, now="2025-12-01")["ready"] is True

    def test_without_now_no_check(self, klp_ttl):
        assert key_preflight(klp_ttl, {"AKEY": "x"}, critical=True)["ready"] is True


@pytest.mark.unit
class TestRealDemoPolicy:
    def test_real_klp_preflight_non_critical(self):
        import yaml
        kd = PKG / "examples" / "key-lifecycle-demo" / "KLP-001.yaml"
        if kd.exists():
            klp = yaml.safe_load(kd.read_text(encoding="utf-8"))
            assert isinstance(key_preflight(klp, {}, critical=False)["checked"], list)
        else:
            pytest.skip("KLP-001 demo not found")
