"""Unit tests for tools/lifecycle_store.py — durable I/O and fail-closed loading."""
from __future__ import annotations

import pytest
import yaml

import lifecycle_store


@pytest.mark.unit
@pytest.mark.critical_path
class TestDurableWrite:
    """Tests for durable_write(): atomic YAML write with validation."""

    def test_durable_write_creates_file(self, tmp_path):
        p = tmp_path / "sub" / "out.yaml"
        result = lifecycle_store.durable_write(p, {"kind": "test", "value": 42})
        assert result["ok"] is True
        assert p.is_file()
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        assert data["value"] == 42

    def test_durable_write_atomic_replaces_valid(self, tmp_path):
        """Second write replaces first with new content."""
        p = tmp_path / "data.yaml"
        lifecycle_store.durable_write(p, {"kind": "test", "v": 1})
        lifecycle_store.durable_write(p, {"kind": "test", "v": 2})
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        assert data["v"] == 2

    def test_durable_write_rejects_invalid_yaml(self, tmp_path):
        """Non-dict data must be rejected (ok=False)."""
        p = tmp_path / "data.yaml"
        result = lifecycle_store.durable_write(p, "not a dict")
        assert result["ok"] is False
        assert "dict" in result["error"].lower() or "не dict" in result["error"]

    def test_durable_write_require_keys(self, tmp_path):
        """Missing required keys must fail the write."""
        p = tmp_path / "data.yaml"
        result = lifecycle_store.durable_write(p, {"kind": "test"}, require_keys=("kind", "missing_key"))
        assert result["ok"] is False
        assert "missing_key" in result["error"]

    def test_durable_write_require_keys_met(self, tmp_path):
        """All required keys present -> ok."""
        p = tmp_path / "data.yaml"
        result = lifecycle_store.durable_write(p, {"kind": "test", "id": "x"}, require_keys=("kind", "id"))
        assert result["ok"] is True

    def test_durable_write_no_temp_leftover(self, tmp_path):
        """No .tmp files should remain after write."""
        p = tmp_path / "data.yaml"
        lifecycle_store.durable_write(p, {"kind": "test"})
        temps = list(tmp_path.glob("*.tmp"))
        assert temps == []

    def test_durable_write_invalid_does_not_overwrite_valid(self, tmp_path):
        """Failed write must NOT corrupt the existing valid file."""
        p = tmp_path / "data.yaml"
        lifecycle_store.durable_write(p, {"kind": "test", "n": 1}, require_keys=("kind", "n"))
        original = p.read_text(encoding="utf-8")
        lifecycle_store.durable_write(p, {"kind": "test"}, require_keys=("kind", "n"))  # missing 'n'
        assert p.read_text(encoding="utf-8") == original

    def test_durable_write_keep_backup(self, tmp_path):
        """keep_backup=True creates a .bak file."""
        p = tmp_path / "data.yaml"
        lifecycle_store.durable_write(p, {"kind": "test", "v": 1})
        lifecycle_store.durable_write(p, {"kind": "test", "v": 2}, keep_backup=True)
        bak = p.with_suffix(p.suffix + ".bak")
        assert bak.is_file()
        bak_data = yaml.safe_load(bak.read_text(encoding="utf-8"))
        assert bak_data["v"] == 1


@pytest.mark.unit
@pytest.mark.critical_path
class TestLoadGuarded:
    """Tests for load_guarded(): fail-closed reading with state discrimination."""

    def test_load_guarded_returns_ok_for_valid(self, tmp_path):
        p = tmp_path / "data.yaml"
        lifecycle_store.durable_write(p, {"kind": "test", "value": 42})
        result = lifecycle_store.load_guarded(p, required_keys=("kind", "value"))
        assert result["state"] == "ok"
        assert result["data"]["value"] == 42

    def test_load_guarded_returns_absent_for_missing(self, tmp_path):
        p = tmp_path / "nonexistent.yaml"
        result = lifecycle_store.load_guarded(p)
        assert result["state"] == "absent"

    def test_load_guarded_returns_corrupt_for_empty(self, tmp_path):
        p = tmp_path / "empty.yaml"
        p.write_text("", encoding="utf-8")
        result = lifecycle_store.load_guarded(p)
        assert result["state"] == "corrupt"

    def test_load_guarded_returns_corrupt_for_bad_yaml(self, tmp_path):
        p = tmp_path / "bad.yaml"
        p.write_text("a: [1, 2\n  b: {", encoding="utf-8")
        result = lifecycle_store.load_guarded(p)
        assert result["state"] == "corrupt"

    def test_load_guarded_returns_corrupt_for_non_dict(self, tmp_path):
        p = tmp_path / "scalar.yaml"
        p.write_text("just a string\n", encoding="utf-8")
        result = lifecycle_store.load_guarded(p)
        assert result["state"] == "corrupt"

    def test_load_guarded_checks_kind(self, tmp_path):
        p = tmp_path / "data.yaml"
        lifecycle_store.durable_write(p, {"kind": "test"})
        result = lifecycle_store.load_guarded(p, kind="other")
        assert result["state"] == "corrupt"
        assert "kind" in result["reason"]

    def test_load_guarded_checks_required_keys(self, tmp_path):
        p = tmp_path / "data.yaml"
        lifecycle_store.durable_write(p, {"kind": "test"})
        result = lifecycle_store.load_guarded(p, required_keys=("kind", "missing"))
        assert result["state"] == "corrupt"


@pytest.mark.unit
class TestDurableWriteJson:
    """Tests for durable_write_json(): atomic JSON write."""

    def test_json_roundtrip(self, tmp_path):
        p = tmp_path / "data.json"
        result = lifecycle_store.durable_write_json(p, {"kind": "report", "status": "ok"},
                                                    require_keys=("kind", "status"))
        assert result["ok"] is True
        import json
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data["status"] == "ok"

    def test_json_require_keys(self, tmp_path):
        p = tmp_path / "data.json"
        result = lifecycle_store.durable_write_json(p, {"kind": "x"}, require_keys=("kind", "missing"))
        assert result["ok"] is False
