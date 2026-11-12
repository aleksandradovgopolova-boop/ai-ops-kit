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
from ai_ops_kit.engops import adoption_evidence as ae
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
    monkeypatch.setattr(ae, "EVIDENCE_META_BYTES", 8)
    assert inspect(project)["installation"]["state"] == "unknown"


@pytest.mark.parametrize("name,limit", [("EVIDENCE_MAX_FILES", 1),
    ("EVIDENCE_FILE_BYTES", 8), ("EVIDENCE_TOTAL_BYTES", 8)])
def test_managed_count_and_byte_limits_fail_closed(project, monkeypatch, name, limit):
    monkeypatch.setattr(ae, name, limit)
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


@pytest.fixture
def verified_project(project):
    from datetime import date, timedelta

    source_day = (date.fromisoformat(a._today()) - timedelta(days=3)).isoformat()
    os_env = dict(os.environ, GIT_AUTHOR_DATE=f"{source_day}T12:00:00Z", GIT_COMMITTER_DATE=f"{source_day}T12:00:00Z")

    def commit(message):
        git(project, "add", ".")
        subprocess.run(["git", "-C", str(project), "commit", "-qm", message], check=True, env=os_env)
        return git(project, "rev-parse", "HEAD")

    # Фиксируем identity в исторической дате до всех наблюдений.
    subprocess.run(["git", "-C", str(project), "commit", "--amend", "--no-edit", "--reset-author", "-q"],
                   check=True, env=os_env)
    anchor = git(project, "rev-parse", "HEAD")
    managed = project / ".ai/managed"
    (managed / "VERSION").write_text("4.11.0\n")
    prior = commit("test: prior version")
    (managed / "VERSION").write_text("4.12.0\n")
    manifest = json.loads((managed / ".checksums.json").read_text())
    manifest["files"]["VERSION"] = hashlib.sha256((managed / "VERSION").read_bytes()).hexdigest()
    write_json(managed / ".checksums.json", manifest)
    release = "f" * 40
    prov = json.loads((managed / ".provenance.json").read_text())
    prov["source_identity"] = {"tag": "v4.12.0", "sha": release[:12], "is_release": True}
    write_json(managed / ".provenance.json", prov)
    installed = commit("test: installed reviewed release")
    (project / "product.txt").write_text("product change")
    active = commit("test: deliver product change")
    assert git(project, "diff", "--name-only", installed, active) == "product.txt"
    state = a._state(project)
    proof = {state["project_id"]: {"kind": "product", "relationship": "external", "identity_commit": anchor,
                                   "observed_on": a._today(), "consent_ids": [state["consent_id"]],
                                   "installation": {"commit": installed, "version": "4.12.0", "release_commit": release,
                                                    "inventory_sha256": a._checksum(manifest["files"])},
                                   "activity": {"commit": active, "path": "product.txt"},
                                   "update": {"commit": installed, "from_version": "4.11.0",
                                              "from_tree_sha256": a._checksum(a._historical_inventory(project, prior))}}}
    return project, proof, source_day


def test_verified_report_deduplicates_and_separates_states(verified_project, tmp_path):
    project, proof, day = verified_project
    path = tmp_path / "independent.json"
    write_json(path, {"schema_version": 1, "projects": proof})
    args = ["report", str(project), "--external", str(project), "--project", str(project),
            "--verification", str(path), "--verification-sha256", hashlib.sha256(path.read_bytes()).hexdigest()]
    command = Path(a.__file__).resolve().parents[2] / "ai-ops"
    p = subprocess.run([str(command), "reach", "adoption", "report", *args[2:]], check=True,
                       env=dict(os.environ, AI_OPS_PYTHON=sys.executable), text=True, capture_output=True)
    data = json.loads(p.stdout)["verified_adoption"]
    assert data["lower_bounds"]["external"] == dict.fromkeys(("registered", "installed", "verified_active", "updated"), 1)
    assert data["coverage"]["local_checkouts_inspected"] == 2
    assert data["projects"][0]["verified_active"]["source_at"] == day
    assert data["global_exact_total"] is None
    assert str(project) not in p.stdout and "product.txt" not in p.stdout


def test_replay_date_not_refreshed(verified_project):
    project, proof, day = verified_project
    result = a.report(project, a._today(), a._today(), [(project, "external")], verification=proof)["verified_adoption"]
    assert day < a._today()
    assert result["lower_bounds"]["external"] == {"registered": 1, "installed": 1, "verified_active": 0, "updated": 0}
    assert result["projects"][0]["verified_active"]["state"] == "unknown"


@pytest.mark.parametrize("field,value,metric", [
    ("installation.inventory_sha256", "0" * 64, "installed"),
    ("installation.release_commit", "0" * 40, "installed"),
    ("activity.path", "unmodified.txt", "verified_active"),
    ("activity.path", ".ai/managed/VERSION", "verified_active"),
    ("update.from_version", "4.10.0", "updated"),
    ("identity_commit", "0" * 40, "registered"),
])
def test_invalid_evidence_does_not_verify(verified_project, field, value, metric):
    project, proof, day = verified_project
    target = next(iter(proof.values()))
    keys = field.split(".")
    if len(keys) == 2:
        target = target[keys[0]]
    target[keys[-1]] = value
    result = a.report(project, day, day, [(project, "external")], verification=proof)["verified_adoption"]
    assert result["lower_bounds"]["external"][metric] == 0


def test_revoke_and_regrant_do_not_reactivate_old_proof(verified_project):
    project, proof, day = verified_project
    a.consent(project, owner=True, revoke=True)
    a.consent(project, owner=True)
    data = a.report(project, day, day, [(project, "external")], verification=proof)["verified_adoption"]
    assert data["lower_bounds"]["external"]["registered"] == 0
    assert data["quarantine"][0]["reason"] == "consent_not_bound_to_review"


def test_fixture_and_unconsented_parent_excluded(verified_project, tmp_path):
    project, proof, day = verified_project
    next(iter(proof.values()))["kind"] = "fixture"
    parent = tmp_path / "kit"
    for name in ("VERSION", "installer/ai_ops.py", "manifest/ai-ops-manifest.yaml"):
        path = parent / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    result = a.report(project, day, day, [(project, "external"), (parent, "owned")], verification=proof)
    assert result["errors"] == []
    assert result["verified_adoption"]["excluded"] == {"fixture": 1, "parent": 1}
    assert result["verified_adoption"]["projects"] == []


def test_report_reads_only_and_cannot_fetch(verified_project, monkeypatch):
    project, proof, day = verified_project
    before = {p: p.read_bytes() for p in project.rglob("*") if p.is_file()}
    original = a._run_git

    def restricted(root, *args, env, **kwargs):
        assert env["GIT_NO_LAZY_FETCH"] == "1" and env["GIT_ALLOW_PROTOCOL"] == ""
        return original(root, *args, env=env, **kwargs)

    monkeypatch.setattr(a, "_run_git", restricted)
    monkeypatch.setattr(socket, "socket", lambda *args, **kw: pytest.fail("network call"))
    data = a.report(project, day, day, [(project, "external")], verification=proof)["verified_adoption"]
    assert data["lower_bounds"]["external"]["verified_active"] == 1
    assert {p: p.read_bytes() for p in project.rglob("*") if p.is_file()} == before


def test_same_project_worktree_counts_once(verified_project, tmp_path):
    project, proof, day = verified_project
    worktree = tmp_path / "other-worktree"
    git(project, "worktree", "add", "--detach", str(worktree))
    assert worktree != project and a._store(worktree) == a._store(project)
    data = a.report(project, day, day, [(project, "external"), (worktree, "external")],
                    verification=proof)["verified_adoption"]
    assert data["lower_bounds"]["external"]["verified_active"] == 1
    assert data["coverage"]["local_checkouts_inspected"] == 2


def test_imported_tombstone_suppresses_pinned_proof(verified_project, tmp_path):
    project, proof, day = verified_project
    aggregator = tmp_path / "aggregator"
    aggregator.mkdir()
    git(aggregator, "init", "-q")
    receipt = a.snapshot(project, day, day)
    receipt.update(consent="revoked", installation="unknown", activity="unknown")
    receipt["checksum"] = a._checksum(receipt)
    tombstone = tmp_path / "tombstone.json"
    write_json(tombstone, receipt)
    assert a.import_receipt(aggregator, tombstone)["state"] == "revoked"
    data = a.report(aggregator, day, day, [(project, "external")], verification=proof)["verified_adoption"]
    assert data["lower_bounds"]["external"]["registered"] == 0


def test_hash_mismatch_rejected_before_reading_projects(verified_project, tmp_path, monkeypatch):
    project, proof, _ = verified_project
    path = tmp_path / "proof.json"
    write_json(path, {"schema_version": 1, "projects": proof})
    monkeypatch.setattr(a, "report", lambda *args, **kw: pytest.fail("unverified input reached report"))
    assert cli.main(["report", str(project), "--verification", str(path), "--verification-sha256", "0" * 64]) == 2


def test_current_bytes_do_not_authenticate_old_version_marker(verified_project):
    project, proof, _ = verified_project
    git(project, "rm", "--cached", ".ai/managed/engine.py")
    git(project, "commit", "-qm", "test: remove tracked runtime")
    assert (project / ".ai/managed/engine.py").is_file()
    assert not git(project, "ls-tree", "HEAD", ".ai/managed/engine.py")
    next(iter(proof.values()))["installation"]["commit"] = git(project, "rev-parse", "HEAD")
    row = a.report(project, a._today(), a._today(), [(project, "external")], verification=proof)["verified_adoption"]
    assert row["lower_bounds"]["external"]["installed"] == 0


def test_local_revocation_suppresses_stale_copy_of_same_consent(verified_project, tmp_path):
    import shutil

    project, proof, day = verified_project
    stale = tmp_path / "stale"
    shutil.copytree(project, stale)
    assert a._state(stale)["consent_id"] == a._state(project)["consent_id"]
    a.consent(project, owner=True, revoke=True)
    copies = [(project, "external"), (stale, "external")]
    data = a.report(project, day, day, copies, verification=proof)
    assert data["verified_adoption"]["lower_bounds"]["external"]["registered"] == 0
    assert data["local_observed"]["external"]["projects"] == 0
    a.consent(project, owner=True)
    assert a._state(stale)["consent_id"] != a._state(project)["consent_id"]
    data = a.report(project, day, day, copies, verification=proof)
    assert data["verified_adoption"]["lower_bounds"]["external"]["registered"] == 0


def test_unreviewed_copy_does_not_hide_same_uuid_history_conflict(verified_project, tmp_path):
    project, proof, day = verified_project
    conflicting = tmp_path / "conflicting"
    conflicting.mkdir()
    identify(conflicting)
    write_json(conflicting / a.IDENTITY, {"schema_version": 1, "project_id": a.identity(project)})
    git(conflicting, "add", a.IDENTITY)
    git(conflicting, "commit", "-qm", "test: conflicting identity")
    a.consent(conflicting, owner=True)
    assert a._state(conflicting)["consent_id"] != a._state(project)["consent_id"]
    data = a.report(project, day, day, [(project, "external"), (conflicting, "external")],
                    verification=proof)["verified_adoption"]
    assert data["lower_bounds"]["external"]["registered"] == 0
    assert data["quarantine"][0]["reason"] == "identity_or_evidence_conflict"


def test_grafts_cannot_turn_product_commit_into_version_transition(verified_project):
    project, proof, day = verified_project
    row = next(iter(proof.values()))
    install = row["installation"]["commit"]
    activity = row["activity"]["commit"]
    prior = git(project, "rev-parse", f"{install}^1")
    row["update"]["commit"] = activity
    graft = project / ".git/info/grafts"
    graft.write_text(f"{activity} {prior} {install}\n")
    assert git(project, "rev-parse", f"{activity}^1") == prior
    data = a.report(project, day, day, [(project, "external")], verification=proof)["verified_adoption"]
    assert data["lower_bounds"]["external"]["installed"] == 1
    assert data["lower_bounds"]["external"]["updated"] == 0


def test_tombstone_from_aggregation_root_applies_to_selected_backup(verified_project, tmp_path):
    import shutil

    project, proof, day = verified_project
    stale = tmp_path / "backup"
    shutil.copytree(project, stale)
    old = a._state(project)
    a.consent(project, owner=True, revoke=True)
    assert a._revocation_path(project, old["project_id"], old["consent_id"]).is_file()
    data = a.report(project, day, day, [(stale, "external")], verification=proof)
    assert data["local_observed"]["external"]["projects"] == 0
    assert data["verified_adoption"]["lower_bounds"]["external"]["registered"] == 0


def test_new_project_id_does_not_hide_old_tombstone_in_selected_store(verified_project, tmp_path):
    import shutil

    project, proof, day = verified_project
    stale = tmp_path / "backup"
    shutil.copytree(project, stale)
    old_id = a.identity(project)
    a.consent(project, owner=True, revoke=True)
    (project / a.IDENTITY).unlink()
    new_id = a.identity(project, create=True)
    git(project, "add", a.IDENTITY)
    git(project, "commit", "-qm", "test: new identity after old opt-in revoked")
    a.consent(project, owner=True)
    assert new_id != old_id
    aggregator = tmp_path / "aggregator"
    aggregator.mkdir()
    git(aggregator, "init", "-q")
    data = a.report(aggregator, day, day, [(project, "external"), (stale, "external")], verification=proof)
    assert data["local_observed"]["external"]["projects"] == 1
    assert data["verified_adoption"]["lower_bounds"]["external"]["registered"] == 0


def test_local_tombstone_excludes_import_without_selected_checkout(project, tmp_path):
    day = a._today()
    path = tmp_path / "old-receipt.json"
    a.export(project, day, day, path)
    a.import_receipt(project, path, "external")
    assert a.report(project, day, day)["external_self_reported_unverified"]["external"]["projects"] == 1
    a.consent(project, owner=True, revoke=True)
    a.consent(project, owner=True)
    assert a.report(project, day, day)["external_self_reported_unverified"]["external"]["projects"] == 0


def test_corrupt_terminal_record_fails_closed_for_import(project, tmp_path):
    day = a._today()
    path = tmp_path / "old-receipt.json"
    receipt = a.export(project, day, day, path)
    a.import_receipt(project, path, "external")
    terminal = a._revocation_path(project, receipt["project_id"], receipt["consent_id"])
    write_json(terminal, {"malformed": True})
    result = a.report(project, day, day)
    assert result["errors"] == ["local_revocations_unavailable"]
    assert result["external_self_reported_unverified"]["external"]["projects"] == 0
