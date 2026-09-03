"""Unit tests for tools/lifecycle_store.py — durable I/O and fail-closed loading."""
from __future__ import annotations

import pytest
import yaml

from ai_ops_kit.shared import lifecycle_store


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


def _seed_journal(jn):
    """Append a Run -> Package -> Gate chain (3 events) into jn."""
    lifecycle_store.journal_append(jn, {"kind": "run_start", "run_id": "R1", "workitem_id": "w"})
    lifecycle_store.journal_append(jn, {"kind": "package_start", "run_id": "R1", "package_id": "WP1"})
    lifecycle_store.journal_append(
        jn, {"kind": "gate", "run_id": "R1", "package_id": "WP1", "gate": "security", "status": "pass"})


@pytest.mark.unit
class TestEventJournal:
    """journal_append/journal_read: append-only JSONL with a verified checksum chain."""

    def test_three_events_intact_chain(self, tmp_path):
        jn = tmp_path / "journal.jsonl"
        _seed_journal(jn)
        result = lifecycle_store.journal_read(jn)
        assert result["ok"] is True
        assert len(result["events"]) == 3

    def test_seq_monotonic(self, tmp_path):
        jn = tmp_path / "journal.jsonl"
        _seed_journal(jn)
        result = lifecycle_store.journal_read(jn)
        assert [e["seq"] for e in result["events"]] == [0, 1, 2]

    def test_run_package_gate_links_preserved(self, tmp_path):
        jn = tmp_path / "journal.jsonl"
        _seed_journal(jn)
        third = lifecycle_store.journal_read(jn)["events"][2]
        assert third["run_id"] == "R1"
        assert third["package_id"] == "WP1"
        assert third["gate"] == "security"

    def test_tampered_middle_line_detected(self, tmp_path):
        import json
        jn = tmp_path / "journal.jsonl"
        _seed_journal(jn)
        lines = jn.read_text(encoding="utf-8").splitlines()
        rec = json.loads(lines[1])
        rec["status"] = "HACKED"
        lines[1] = json.dumps(rec, ensure_ascii=False)
        jn.write_text("\n".join(lines) + "\n", encoding="utf-8")
        assert lifecycle_store.journal_read(jn)["ok"] is False

    def test_truncated_last_line_detected(self, tmp_path):
        jn = tmp_path / "journal.jsonl"
        lifecycle_store.journal_append(jn, {"kind": "run_start", "run_id": "R2"})
        with open(jn, "a", encoding="utf-8") as f:
            f.write('{"kind": "run_end", "run_i')  # truncated record, no newline
        assert lifecycle_store.journal_read(jn)["ok"] is False

    def test_append_to_broken_chain_refused(self, tmp_path):
        import json
        jn = tmp_path / "journal.jsonl"
        lifecycle_store.journal_append(jn, {"kind": "run_start", "run_id": "R3"})
        lifecycle_store.journal_append(jn, {"kind": "package_end", "run_id": "R3", "package_id": "P1"})
        lines = jn.read_text(encoding="utf-8").splitlines()
        rec = json.loads(lines[0])
        rec["run_id"] = "TAMPER"
        lines[0] = json.dumps(rec, ensure_ascii=False)
        jn.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = lifecycle_store.journal_append(jn, {"kind": "run_end", "run_id": "R3"})
        assert result["ok"] is False
        assert "повреждён" in result.get("error", "")

    def test_head_marker_written_on_intact_journal(self, tmp_path):
        jn = tmp_path / "journal.jsonl"
        lifecycle_store.journal_append(jn, {"kind": "run_start", "run_id": "R4"})
        lifecycle_store.journal_append(jn, {"kind": "run_end", "run_id": "R4"})
        assert lifecycle_store.journal_read(jn)["ok"] is True
        assert (tmp_path / "journal.jsonl.head").exists()

    def test_deleted_last_line_detected_via_head_marker(self, tmp_path):
        jn = tmp_path / "journal.jsonl"
        lifecycle_store.journal_append(jn, {"kind": "run_start", "run_id": "R4"})
        lifecycle_store.journal_append(jn, {"kind": "run_end", "run_id": "R4"})
        lines = jn.read_text(encoding="utf-8").splitlines()
        jn.write_text(lines[0] + "\n", encoding="utf-8")  # drop the whole last (valid-prefix) line
        result = lifecycle_store.journal_read(jn)
        assert result["ok"] is False
        assert "усечение" in (result.get("reason") or "")


@pytest.mark.unit
class TestValidateTrace:
    """validate_trace: events must carry the mandatory ids of their link."""

    def test_full_valid_trace_has_no_errors(self):
        events = [
            {"kind": "run_start", "run_id": "R", "workitem_id": "R", "attempt_id": "R#a1"},
            {"kind": "package_end", "run_id": "R", "workitem_id": "R", "package_id": "WP1"},
            {"kind": "delivery_receipt", "run_id": "R", "delivery_id": "d1"},
            {"kind": "run_end", "run_id": "R", "workitem_id": "R", "attempt_id": "R#a1", "status": "delivered"},
        ]
        assert lifecycle_store.validate_trace(events) == []

    def test_package_end_without_package_id_errors(self):
        errs = lifecycle_store.validate_trace(
            [{"kind": "package_end", "run_id": "R", "workitem_id": "R"}])
        assert any("package_id" in e for e in errs)

    def test_delivery_without_delivery_id_errors(self):
        errs = lifecycle_store.validate_trace([{"kind": "delivery", "run_id": "R"}])
        assert any("delivery_id" in e for e in errs)

    def test_run_start_without_attempt_id_errors(self):
        errs = lifecycle_store.validate_trace(
            [{"kind": "run_start", "run_id": "R", "workitem_id": "R"}])
        assert any("attempt_id" in e for e in errs)
