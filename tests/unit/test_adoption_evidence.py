"""Локальная целостность не равна provenance/authentication или verified adoption."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

from ai_ops_kit.engops import adoption as a
from ai_ops_kit.cli import adoption as cli
from _installer_helpers import _run_cli

pytestmark = pytest.mark.unit


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True,
                          text=True, timeout=10).stdout.strip()


def identify(root):
    git(root, "init", "-q")
    git(root, "config", "user.email", "private@example.test")
    git(root, "config", "user.name", "Private Owner")
    a.identity(root, create=True)
    git(root, "add", a.IDENTITY)
    git(root, "commit", "-qm", "test: identity")


def write_json(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "secret-person@example.test"
    root.mkdir()
    identify(root)
    managed = root / ".ai/managed"
    managed.mkdir()
    (managed / "VERSION").write_text("4.12.0\n")
    (managed / "engine.py").write_text("# real bytes for integrity\n")
    write_json(managed / ".checksums.json", {
        "schema_version": 1, "algorithm": "sha256", "managed_root": "managed",
        "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in managed.iterdir()}})
    write_json(managed / ".provenance.json", {
        "schema_version": 1, "package": "ai-first-system", "installed_version": "4.12.0",
        "managed_root": ".ai/managed", "checksums_file": ".checksums.json", "installed_at": None,
        "source": "https://private-person:secret@example.test/repo",
        "source_identity": {"path": str(tmp_path / "private-source"), "sha": "fake"},
        "note": "private@example.test"})
    a.consent(root, owner=True)
    return root


def inspect(root):
    return a.local_evidence(root, a._today(), a._today())


def report(root, **changes):
    doc = {"schema_version": 1, "command": "update", "status": "ok",
           "from_version": "4.11.0", "to_version": "4.12.0",
           "smoke_tests": [{"check": "private/path", "status": "pass"}]}
    doc.update(changes)
    write_json(root / ".ai/runtime/last-update-report.json", doc)


def test_consistent_bytes_are_local_only_not_source_authentication(project):
    result = inspect(project)
    installed = result["installation"]
    assert installed["state"] == "locally_consistent"
    assert installed["checked_files"] == 2 and installed["version"] == "4.12.0"
    assert installed["source_authentication"] == "unknown" and installed["source_at"] is None
    assert result["world_total_state"] == "unknown"


@pytest.mark.parametrize("source_day", ["2000-01-01", "2999-01-01", None])
def test_successful_update_report_is_undated_and_never_updated_in_window(project, source_day):
    source_day = source_day or a._today()
    report(project, observed_at=source_day, installed_at=source_day, source_at=source_day)
    path = project / ".ai/runtime/last-update-report.json"
    os.utime(path, None)
    update = inspect(project)["update"]
    assert update["state"] == "local_report_consistent"
    assert update["from_version"] == "4.11.0" and update["to_version"] == "4.12.0"
    assert update["source_at"] is None and update["updated_in_window"] == "unknown"


@pytest.mark.parametrize("change", [
    {"status": "rolled_back"}, {"status": "failed"}, {"status": "blocked"}, {"status": "skipped"},
    {"from_version": "4.12.0"}, {"to_version": "4.99.0"}, {"from_version": None},
    {"applied_in_place": False}, {"deferred_to_branch": "update-v4.12.0"},
    {"applied_in_place": 0}, {"applied_in_place": None}, {"applied_in_place": "false"},
    {"deferred_to_branch": None}, {"deferred_to_branch": ""},
    {"smoke_tests": []}, {"smoke_tests": [{"status": "fail"}]}, {"smoke_tests": ["pass"]},
    {"smoke_tests": [{"status": "pass"}]}, {"smoke_tests": [{"check": " ", "status": "pass"}]},
    {"schema_version": True}, {"command": "preview"},
])
def test_incomplete_failed_deferred_and_noop_updates_stay_unknown(project, change):
    report(project, **change)
    assert inspect(project)["update"]["state"] == "unknown"


@pytest.mark.parametrize("target,content", [
    ("engine.py", "changed"), ("new.txt", "extra"), (".checksums.json", "{}"),
    (".checksums.json", "[]"), (".provenance.json", "not json"),
    (".provenance.json", '{"schema_version":1,"installed_version":"4.11.0"}'),
])
def test_drift_incomplete_and_malformed_installation_stays_unknown(project, target, content):
    (project / ".ai/managed" / target).write_text(content)
    report(project)
    result = inspect(project)
    assert result["installation"]["state"] == result["update"]["state"] == "unknown"


def test_missing_tracked_managed_file_stays_unknown(project):
    (project / ".ai/managed/engine.py").unlink()
    assert inspect(project)["installation"]["state"] == "unknown"


@pytest.mark.parametrize("relative", ["../outside", "/tmp/outside", "a/../../outside", "C:\\outside"])
def test_unsafe_checksum_paths_do_not_read_outside(project, relative):
    path = project / ".ai/managed/.checksums.json"
    doc = json.loads(path.read_text())
    doc["files"][relative] = "0" * 64
    write_json(path, doc)
    assert inspect(project)["installation"]["state"] == "unknown"


@pytest.mark.parametrize("name", ["VERSION", ".checksums.json", ".provenance.json", "engine.py"])
def test_symlink_managed_artifacts_rejected(project, tmp_path, name):
    path = project / ".ai/managed" / name
    outside = tmp_path / "outside-secret"
    outside.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(outside)
    assert inspect(project)["installation"]["state"] == "unknown"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO unavailable")
def test_fifo_rejected_before_opening(project):
    path = project / ".ai/managed/engine.py"
    path.unlink()
    os.mkfifo(path)
    assert inspect(project)["installation"]["state"] == "unknown"


def test_oversized_evidence_rejected(project, monkeypatch):
    monkeypatch.setattr(a, "EVIDENCE_META_BYTES", 8)
    assert inspect(project)["installation"]["state"] == "unknown"


@pytest.mark.parametrize("name,limit", [("EVIDENCE_MAX_FILES", 1),
    ("EVIDENCE_FILE_BYTES", 8), ("EVIDENCE_TOTAL_BYTES", 8)])
def test_managed_count_and_byte_limits_fail_closed(project, monkeypatch, name, limit):
    monkeypatch.setattr(a, name, limit)
    assert inspect(project)["installation"]["state"] == "unknown"


def test_interpreter_artifacts_do_not_create_false_drift(project):
    path = project / ".ai/managed/__pycache__"
    path.mkdir()
    (path / "engine.pyc").write_bytes(b"interpreter")
    assert inspect(project)["installation"]["state"] == "locally_consistent"


def test_manual_dates_and_forged_run_do_not_become_verified_product_work(project):
    state = a._state(project)
    state["days"] = [a._today()]
    write_json(a._store(project) / "consent.json", state)
    write_json(project / ".ai/runtime/run-report.json", {
        "kind": "execution-pipeline", "ready_for_pr": True, "verified": True,
        "gates": {"evidence_verdict": "verified"}})
    result = inspect(project)
    assert result["activity"]["observed_dates_in_window"] == 1
    assert result["activity"]["source"] == "unattributed_local_dates"
    assert result["activity"]["verified_product_active"] == "unknown"
    assert result["imported_receipts_used"] is False


def test_forged_import_is_not_local_product_confirmation(project, tmp_path):
    path = tmp_path / "forged-receipt.json"
    doc = a.export(project, a._today(), a._today(), path)
    doc["activity"] = "observed"
    doc["checksum"] = a._checksum({k:v for k,v in doc.items() if k!="checksum"})
    write_json(path, doc)
    a.import_receipt(project, path, "external")
    result = inspect(project)
    assert result["activity"]["observed_dates_in_window"] == 0
    assert result["activity"]["verified_product_active"] == "unknown"
    assert result["imported_receipts_used"] is False


def test_no_active_consent_means_no_artifact_reads_or_writes(project, monkeypatch):
    a.consent(project, owner=True, revoke=True)
    def forbidden(*args, **kwargs):
        raise AssertionError("must not inspect or write")
    monkeypatch.setattr(a, "_installation_evidence", forbidden)
    monkeypatch.setattr(a, "_write", forbidden)
    assert inspect(project)["inspection"] == "not_permitted"


def test_read_only_no_network_no_private_values_and_legacy_receipt_unchanged(project, monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("network/write forbidden")
    before = (a._store(project) / "consent.json").read_bytes()
    old_receipt = a.export(project, a._today(), a._today(), tmp_path / "before.json")
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(a, "_write", forbidden)
    result = inspect(project)
    assert (a._store(project) / "consent.json").read_bytes() == before
    assert a.snapshot(project, a._today(), a._today()) == {k:v for k,v in old_receipt.items() if k!="checksum"}
    encoded = json.dumps(result)
    for private in (str(project), "private", "secret", "example.test", "source_identity", "sha", "note"):
        assert private not in encoded


def test_cli_evidence_defaults_to_thirty_days_and_refuses_without_consent(project, capsys):
    assert cli.main(["evidence", str(project)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["window"] == a.reporting_window()
    a.consent(project, owner=True, revoke=True)
    assert cli.main(["evidence", str(project)]) == 2
    assert json.loads(capsys.readouterr().out)["inspection"] == "not_permitted"


def test_real_isolated_installer_metadata_is_read_without_modification(tmp_path):
    root = tmp_path / "isolated-child"
    root.mkdir()
    git(root, "init", "-q")
    installed = _run_cli(root, "init", ".")
    assert installed.returncode == 0, installed.stdout[-1000:] + installed.stderr[-1000:]
    identify(root)
    a.consent(root, owner=True)
    before = {p.name: p.read_bytes() for p in (root / ".ai/managed").glob(".*json")}
    result = inspect(root)
    assert result["installation"]["state"] == "locally_consistent"
    assert result["installation"]["checked_files"] > 100
    assert result["update"]["state"] == "unknown"
    delivered = subprocess.run([sys.executable, "-m", "ai_ops_kit.cli.adoption", "evidence", ".",
        "--start", a._today(), "--end", a._today()],
        cwd=root, env=dict(os.environ, PYTHONPATH=str(root / ".ai/managed"), PYTHONDONTWRITEBYTECODE="1"),
        capture_output=True, text=True, timeout=30)
    assert delivered.returncode == 0, delivered.stderr
    assert json.loads(delivered.stdout) == result
    assert {p.name: p.read_bytes() for p in (root / ".ai/managed").glob(".*json")} == before
