"""Реальные git-копии, согласие, недоверенный импорт и отсутствие внешних side effects."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import socket
import subprocess

import pytest

from ai_ops_kit.engops import adoption as a
from ai_ops_kit.cli import adoption as adoption_cli
from ai_ops_kit.shared.events import emit

pytestmark = pytest.mark.unit


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          capture_output=True, text=True, timeout=10).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "secret-project-person@example.test"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.email", "private@example.test")
    git(root, "config", "user.name", "Private Owner")
    a.identity(root, create=True)
    managed = root / ".ai/managed"
    managed.mkdir(parents=True)
    (managed / "VERSION").write_text("4.12.0\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "test: identity")
    return root


def window():
    return a._today(), a._today()


@pytest.mark.parametrize("today,start", [
    ("2026-01-01", "2025-12-03"),
    ("2028-03-01", "2028-02-01"),
    ("2026-03-01", "2026-01-31"),
])
def test_default_window_includes_thirty_utc_calendar_dates(monkeypatch, today, start):
    monkeypatch.setattr(a, "_today", lambda: today)
    assert a.reporting_window() == {"start": start, "end": today}


def test_explicit_window_is_preserved():
    assert a.reporting_window("2000-01-01", "2000-01-03") == {
        "start": "2000-01-01", "end": "2000-01-03"}


@pytest.mark.parametrize("start,end", [("2000-01-01", None), (None, "2000-01-03"),
    ("2000-01-03", "2000-01-01"), ("2999-01-01", "2999-01-03"), ("", "2000-01-03")])
def test_reporting_window_rejects_incomplete_or_invalid_dates(start, end):
    with pytest.raises(ValueError):
        a.reporting_window(start, end)


def test_default_report_is_read_only_without_consent(repo, monkeypatch, capsys):
    monkeypatch.setattr(a, "_today", lambda: "2026-01-01")
    assert adoption_cli.main(["report", str(repo)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["window"] == {"start": "2025-12-03", "end": "2026-01-01"}
    assert result["world_total_state"] == "unknown"
    assert not a._store(repo).exists()


def test_default_preview_and_export_show_same_window(repo, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(a, "_today", lambda: "2026-01-01")
    a.consent(repo, owner=True)
    assert adoption_cli.main(["preview", str(repo)]) == 0
    preview = json.loads(capsys.readouterr().out)
    path = tmp_path / "default-export.json"
    assert adoption_cli.main(["export", str(repo), "--output", str(path)]) == 0
    exported = json.loads(capsys.readouterr().out)
    assert preview["window"] == exported["window"] == {
        "start": "2025-12-03", "end": "2026-01-01"}
    assert a.validate_receipt(json.loads(path.read_text())) == exported


@pytest.mark.parametrize("flag", ["--start", "--end"])
def test_incomplete_window_export_does_not_write_or_change_consent(repo, tmp_path, capsys, flag):
    a.consent(repo, owner=True)
    state_path = a._store(repo) / "consent.json"
    before = state_path.read_bytes()
    path = tmp_path / "not-exported.json"
    assert adoption_cli.main(["export", str(repo), flag, a._today(), "--output", str(path)]) == 2
    assert "error" in json.loads(capsys.readouterr().out)
    assert not path.exists()
    assert state_path.read_bytes() == before


def observe(root):
    rep = {"kind": "execution-pipeline", "provider": "test-live", "cost": {"calls": 1}}
    a.observe_completed({"child_root": str(root), "report": rep,
                         "timestamp": a._today() + "T00:00:00+00:00"})
    return rep


def exported(root, path):
    return a.export(root, *window(), path)


def test_default_status_and_event_do_not_write(repo):
    assert a.status(repo)["consent"] == "disabled"
    observe(repo)
    assert not a._store(repo).exists()


def test_identity_does_not_grant_consent(repo):
    assert a.identity(repo)
    with pytest.raises(ValueError, match="не включал"):
        a.snapshot(repo, *window())


def test_owner_choice_required(repo):
    with pytest.raises(ValueError, match="владельца"):
        a.consent(repo)
    assert not (a._store(repo) / "consent.json").exists()


def test_uncommitted_id_is_not_accepted(repo):
    (repo / a.IDENTITY).write_text('{"schema_version":1,"project_id":"11111111-1111-4111-8111-111111111111"}')
    with pytest.raises(ValueError, match="HEAD"):
        a.consent(repo, owner=True)


def test_event_records_real_local_side_effect_once_per_day(repo, monkeypatch):
    a.consent(repo, owner=True)
    writes = []
    original = a._write
    def counted_write(path, doc):
        writes.append(path)
        return original(path, doc)
    monkeypatch.setattr(a, "_write", counted_write)
    observe(repo)
    observe(repo)
    state = json.loads((a._store(repo) / "consent.json").read_text())
    assert state["days"] == [a._today()]
    assert len(writes) == 1
    snap = a.snapshot(repo, *window())
    assert snap["installation"] == snap["activity"] == "observed"


def test_subscribed_event_is_wired(repo):
    a.consent(repo, owner=True)
    rep = {"kind": "execution-pipeline", "provider": "test-live", "cost": {"calls": 1}}
    emit("run_completed", {"child_root": str(repo), "report": rep,
                           "timestamp": a._today() + "T00:00:00+00:00"})
    assert rep["adoption_observation"] == "recorded_locally"
    assert a.snapshot(repo, *window())["activity"] == "observed"


@pytest.mark.parametrize("rep", [{}, {"cost": {"calls": 0}}, {"cost": "forged"},
    {"kind": "execution-pipeline", "provider": "mock", "cost": {"calls": 1}},
    {"kind": "execution-pipeline", "provider": "live", "cost": {"calls": True}}])
def test_preview_mock_missing_and_zero_calls_are_not_activity(repo, rep):
    a.consent(repo, owner=True)
    a.observe_completed({"child_root": str(repo), "report": rep,
                         "timestamp": a._today() + "T00:00:00+00:00"})
    assert a.snapshot(repo, *window())["activity"] == "unknown"


def test_no_evidence_and_old_window_stay_unknown(repo):
    a.consent(repo, owner=True)
    assert a.snapshot(repo, *window())["activity"] == "unknown"
    observe(repo)
    assert a.snapshot(repo, "2000-01-01", "2000-01-02")["activity"] == "unknown"


def test_copied_old_event_does_not_refresh_local_activity(repo, monkeypatch):
    monkeypatch.setattr(a, "_today", lambda: "2026-01-01")
    a.consent(repo, owner=True)
    rep = {"kind": "execution-pipeline", "provider": "test-live", "cost": {"calls": 1}}
    event = {"child_root": str(repo), "report": rep, "timestamp": "2026-01-01T00:00:00+00:00"}
    a.observe_completed(event)
    state_path = a._store(repo) / "consent.json"
    before = state_path.read_bytes()
    monkeypatch.setattr(a, "_today", lambda: "2026-01-02")
    a.observe_completed(dict(event, report=dict(rep)))
    assert state_path.read_bytes() == before
    assert a.snapshot(repo, "2026-01-02", "2026-01-02")["activity"] == "unknown"


@pytest.mark.parametrize("stamp", [None, False, "", "not-a-date", "2026-01-02",
    "2026-01-02T00:00:00", "2026-01-01T23:59:59Z", "2026-01-03T00:00:00Z",
    "2026-01-02T13:00:00Z", "2026-01-02T01:00:00+03:00",
    "0001-01-01T00:00:00+01:00", "9999-12-31T23:59:59-01:00"])
def test_legacy_invalid_old_future_or_previous_utc_day_event_does_not_write(repo, monkeypatch, stamp):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 1, 2, 12, tzinfo=timezone.utc).astimezone(tz)
    monkeypatch.setattr(a, "datetime", Clock)
    a.consent(repo, owner=True)
    before = (a._store(repo) / "consent.json").read_bytes()
    rep = {"kind": "execution-pipeline", "provider": "test-live", "cost": {"calls": 1}}
    event = {"child_root": str(repo), "report": rep}
    if stamp is not None:
        event["timestamp"] = stamp
    a.observe_completed(event)
    assert rep["adoption_observation"] == "unavailable"
    assert (a._store(repo) / "consent.json").read_bytes() == before
    assert a.snapshot(repo, "2026-01-02", "2026-01-02")["activity"] == "unknown"


def test_event_offset_uses_utc_day_not_local_calendar_day(repo, monkeypatch):
    monkeypatch.setattr(a, "_today", lambda: "2026-01-02")
    a.consent(repo, owner=True)
    rep = {"kind": "execution-pipeline", "provider": "test-live", "cost": {"calls": 1}}
    a.observe_completed({"child_root": str(repo), "report": rep,
                         "timestamp": "2026-01-01T22:00:00-02:00"})
    assert a._state(repo)["days"] == ["2026-01-02"]


def test_real_kernel_finalizer_emits_source_time_to_adoption_subscriber(repo, monkeypatch, tmp_path):
    from ai_ops_kit.engine import ai_ops_run_lifecycle as facade
    from ai_ops_kit.engine import ai_ops_run_lifecycle_stages as stages
    from ai_ops_kit.shared import events
    a.consent(repo, owner=True)
    monkeypatch.setattr(stages.active_work, "finish_cmd", lambda *a, **k: 0)
    monkeypatch.setattr(stages._ls, "journal_append", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(stages._ls, "merge_bookkeeping_losses", lambda *a, **k: 0)
    monkeypatch.setattr(facade, "_run_start_audience", lambda *a, **k: "technical")
    received = []
    events.subscribe("run_completed", received.append)
    rep = {"kind": "execution-pipeline", "provider": "test-live", "cost": {"calls": 1},
           "ready_for_pr": True}
    before = datetime.now(timezone.utc)
    try:
        assert stages._finalize_run(rep, "fixture", repo, str(tmp_path / "journal"), "fixture#a1",
                                    tmp_path / "active.yaml") is rep
    finally:
        events.unsubscribe("run_completed", received.append)
    stamp = datetime.fromisoformat(received[0]["timestamp"])
    assert before <= stamp <= datetime.now(timezone.utc)
    assert stamp.utcoffset().total_seconds() == 0
    assert rep["adoption_observation"] == "recorded_locally"
    assert a._state(repo)["days"] == [stamp.date().isoformat()]


def test_revoke_purges_days_and_stops_recording(repo):
    first = a.consent(repo, owner=True)
    observe(repo)
    assert a._state(repo)["days"]
    a.consent(repo, owner=True, revoke=True)
    observe(repo)
    assert a._state(repo)["days"] == []
    assert a.snapshot(repo, *window())["consent"] == "revoked"
    assert a.consent(repo, owner=True)["consent_id"] != first["consent_id"]


def test_revoke_works_without_id_on_branch(repo):
    a.consent(repo, owner=True)
    (repo / a.IDENTITY).unlink()
    assert a.consent(repo, owner=True, revoke=True)["consent"] == "revoked"


def test_clone_deduplication_and_consent_not_inherited(repo, tmp_path):
    a.consent(repo, owner=True)
    observe(repo)
    clone = tmp_path / "copy"
    subprocess.run(["git", "clone", "--local", str(repo), str(clone)], check=True,
                   capture_output=True, timeout=10)
    assert a.identity(clone) == a.identity(repo)
    assert a.status(clone)["consent"] == "disabled"
    a.consent(clone, owner=True)
    result = a.report(repo, *window(), [(repo, "owned"), (clone, "owned")])
    assert result["local_observed"]["owned"] == {"projects": 1, "installed": 1, "active": 1}


def test_worktree_and_branch_share_identity_and_revoke(repo, tmp_path):
    a.consent(repo, owner=True)
    worktree = tmp_path / "worktree"
    git(repo, "worktree", "add", "-b", "other", str(worktree))
    assert a.identity(worktree) == a.identity(repo)
    assert a.status(worktree)["consent"] == "granted"
    a.consent(worktree, owner=True, revoke=True)
    assert a.status(repo)["consent"] == "revoked"


def test_same_history_different_project_uuid_does_not_merge(repo, tmp_path):
    other = tmp_path / "fork"
    subprocess.run(["git", "clone", "--local", str(repo), str(other)], check=True,
                   capture_output=True, timeout=10)
    git(other, "config", "user.email", "test@example.test")
    git(other, "config", "user.name", "Test")
    (other / a.IDENTITY).unlink()
    a.identity(other, create=True)
    git(other, "add", a.IDENTITY)
    git(other, "commit", "-m", "test: separate product")
    a.consent(repo, owner=True)
    a.consent(other, owner=True)
    result = a.report(repo, *window(), [(repo, "owned"), (other, "external")])
    assert result["local_observed"]["owned"]["projects"] == 1
    assert result["local_observed"]["external"]["projects"] == 1


def test_export_has_no_names_paths_personal_data_or_code(repo, tmp_path):
    a.consent(repo, owner=True)
    observe(repo)
    path = tmp_path / "export.json"
    doc = exported(repo, path)
    assert path.is_file() and a.validate_receipt(json.loads(path.read_text())) == doc
    content = path.read_text()
    for private in (repo.name, str(repo), "example", "Private", "provider", "test-live", "calls", "task"):
        assert private not in content


def test_export_cannot_overwrite_existing_file(repo):
    a.consent(repo, owner=True)
    before = (repo / a.IDENTITY).read_bytes()
    with pytest.raises(FileExistsError):
        exported(repo, repo / a.IDENTITY)
    assert (repo / a.IDENTITY).read_bytes() == before


def test_import_is_idempotent_and_never_authenticated(repo, tmp_path):
    a.consent(repo, owner=True)
    observe(repo)
    path = tmp_path / "export.json"
    exported(repo, path)
    for _ in range(2):
        assert a.import_receipt(repo, path, "external")["trust"] == "self_reported"
    result = a.report(repo, *window())
    assert result["external_self_reported_unverified"]["external"]["active"] == 1
    assert result["local_observed"]["external"]["active"] == 0
    assert len(list((a._store(repo) / "imports").glob("*.json"))) == 1


def test_forged_valid_receipt_cannot_raise_confirmed_count(repo, tmp_path):
    a.consent(repo, owner=True)
    path = tmp_path / "forged.json"
    doc = exported(repo, path)
    doc["activity"] = "observed"
    doc["checksum"] = a._checksum({k: v for k, v in doc.items() if k != "checksum"})
    path.write_text(json.dumps(doc))
    a.import_receipt(repo, path)
    result = a.report(repo, *window())
    assert result["local_observed"]["unknown"]["active"] == 0
    assert result["external_self_reported_unverified"]["unknown"]["active"] == 1


@pytest.mark.parametrize("change", [{"project_id": "../../escape"}, {"checksum": "fake"},
    {"secret": "bad"}, {"observed_on": "2999-01-01"}, {"schema_version": True},
    {"window": []}, {"activity": 1}])
def test_tampered_import_fails_before_write(repo, tmp_path, change):
    a.consent(repo, owner=True)
    path = tmp_path / "tampered.json"
    doc = exported(repo, path)
    doc.update(change)
    path.write_text(json.dumps(doc))
    with pytest.raises((ValueError, TypeError)):
        a.import_receipt(repo, path)
    assert not (a._store(repo) / "imports").exists()


def test_revocation_tombstone_prevents_replay(repo, tmp_path):
    a.consent(repo, owner=True)
    observe(repo)
    old = tmp_path / "grant.json"
    exported(repo, old)
    a.import_receipt(repo, old)
    a.consent(repo, owner=True, revoke=True)
    revoked = tmp_path / "revoke.json"
    exported(repo, revoked)
    a.import_receipt(repo, revoked)
    assert a.import_receipt(repo, old)["state"] == "revoked"
    assert a.report(repo, *window())["external_self_reported_unverified"]["unknown"]["projects"] == 0


def test_reconsent_has_new_token_and_can_be_imported(repo, tmp_path):
    a.consent(repo, owner=True)
    a.consent(repo, owner=True, revoke=True)
    path = tmp_path / "revoked.json"
    exported(repo, path)
    a.import_receipt(repo, path)
    a.consent(repo, owner=True)
    fresh = tmp_path / "fresh.json"
    exported(repo, fresh)
    a.import_receipt(repo, fresh)
    assert a.report(repo, *window())["external_self_reported_unverified"]["unknown"]["projects"] == 1


def test_remote_copy_of_local_project_not_double_counted(repo, tmp_path):
    a.consent(repo, owner=True)
    path = tmp_path / "export.json"
    exported(repo, path)
    a.import_receipt(repo, path, "external")
    result = a.report(repo, *window(), [(repo, "owned")])
    assert result["local_observed"]["owned"]["projects"] == 1
    assert result["external_self_reported_unverified"]["external"]["projects"] == 0


def test_conflicting_relationship_becomes_unknown(repo):
    a.consent(repo, owner=True)
    result = a.report(repo, *window(), [(repo, "owned"), (repo, "external")])
    assert result["local_observed"]["unknown"]["projects"] == 1


def test_incomplete_and_corrupt_data_do_not_become_world_zero(repo):
    result = a.report(repo, *window(), [(repo, "owned")])
    assert result["errors"] == ["local_observation_unavailable"]
    assert result["world_total"] is None
    assert result["observation_completeness"] == "partial"
    a.consent(repo, owner=True)
    (a._store(repo) / "consent.json").write_text("{")
    assert a.report(repo, *window(), [(repo, "owned")])["errors"]


def test_no_network_or_remote_identifiers_for_all_operations(repo, tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("network attempted")
    monkeypatch.setattr(socket, "socket", forbidden)
    original = a.git
    def local_git(root, *args, **kwargs):
        assert args[0] in ("rev-parse", "show")
        return original(root, *args, **kwargs)
    monkeypatch.setattr(a, "git", local_git)
    a.consent(repo, owner=True)
    observe(repo)
    path = tmp_path / "export.json"
    exported(repo, path)
    a.import_receipt(repo, path)
    assert a.report(repo, *window(), [(repo, "owned")])["local_observed"]["owned"]["active"] == 1
    a.consent(repo, owner=True, revoke=True)
    assert a.CAPABILITIES == {"network": False, "sends": False}


def test_cli_reach_status_does_not_enable_consent(repo, capsys):
    from ai_ops_kit.cli import ai_ops_cli
    assert ai_ops_cli.main(["reach", "adoption", str(repo), "--json"]) == 0
    assert '"consent": "disabled"' in capsys.readouterr().out
    assert not a._store(repo).exists()


def test_cli_errors_are_sanitized(repo, capsys):
    assert adoption_cli.main(["consent", str(repo)]) == 2
    output = capsys.readouterr().out
    assert repo.name not in output
    assert '"error"' in output


def test_preview_shows_export_fields_without_saving(repo, capsys):
    a.consent(repo, owner=True)
    before = set(a._store(repo).rglob("*"))
    assert adoption_cli.main(["preview", str(repo), "--start", window()[0], "--end", window()[1]]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["project_id"] == a.identity(repo)
    assert set(a._store(repo).rglob("*")) == before


def test_import_preserves_different_windows(repo, tmp_path):
    a.consent(repo, owner=True)
    observe(repo)
    first = tmp_path / "first.json"
    exported(repo, first)
    a.import_receipt(repo, first)
    second = tmp_path / "second.json"
    a.export(repo, "2000-01-01", "2000-01-02", second)
    a.import_receipt(repo, second)
    result = a.report(repo, *window())
    assert result["external_self_reported_unverified"]["unknown"]["active"] == 1


def test_fifo_import_rejected_without_open(repo, tmp_path):
    import os
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    with pytest.raises(ValueError, match="небезопасный"):
        a.import_receipt(repo, fifo)


def test_direct_revocation_overrides_stale_import(repo, tmp_path):
    a.consent(repo, owner=True)
    path = tmp_path / "granted.json"
    exported(repo, path)
    a.import_receipt(repo, path)
    a.consent(repo, owner=True, revoke=True)
    result = a.report(repo, *window(), [(repo, "owned")])
    assert result["external_self_reported_unverified"]["unknown"]["projects"] == 0
