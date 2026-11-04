"""Migration changes real files; no model or original user request is executed."""
import hashlib
import json

import pytest
import yaml

from test_project_session import project as _project_fixture
from ai_ops_kit.cli.project_session import hook
from ai_ops_kit.lifecycle import project_session as sessions
from ai_ops_kit.lifecycle import session_migration as migration
from ai_ops_kit.lifecycle import session_migration_store as store

project = _project_fixture


def manifest(root):
    managed = root / ".ai/managed"
    files = {p.relative_to(managed).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in managed.rglob("*") if p.is_file() and p.name != ".checksums.json"}
    (managed / ".checksums.json").write_text(json.dumps({"files": files}))


def initialize(root, runtime="codex"):
    (root / ".gitignore").write_text(".ai/runtime/\n")
    manifest(root)
    sessions.git(root, "add", "-A")
    sessions.git(root, "commit", "-qm", "old installation")
    return sessions.begin(root, runtime, "owner", "Preserve this request", "original-turn")


def upgrade(root):
    (root / ".ai/managed/VERSION").write_text("4.11.5")
    (root / ".ai/managed" / sessions.POLICY).write_text("new qualified policy")
    cfg = yaml.safe_load((root / ".ai-ops.yaml").read_text())
    cfg["parent"]["installed_version"] = "4.11.5"
    (root / ".ai-ops.yaml").write_text(yaml.safe_dump(cfg))
    manifest(root)


def captured_plan(root, tmp_path):
    snapshot, plan = tmp_path / "snapshot.json", tmp_path / "plan.json"
    captured = migration.capture(root, snapshot)
    upgrade(root)
    preview = migration.preview(root, snapshot, captured["sha256"], plan)
    return snapshot, captured["sha256"], plan, preview


@pytest.mark.parametrize("runtime", sessions.RUNTIMES)
def test_actual_binding_migration_and_exact_rollback(project, tmp_path, runtime):
    task = initialize(project, runtime)
    record = sessions.session_dir(project, runtime, "owner") / (task["request_id"] + ".json")
    before = record.read_bytes()
    snapshot, snapshot_sha, plan, preview = captured_plan(project, tmp_path)
    assert preview["eligible"] == 1
    result = migration.apply(project, snapshot, snapshot_sha, plan, preview["sha256"])
    migrated = json.loads(record.read_text())
    assert record.read_bytes() != before
    assert migrated["binding"] == sessions.binding(project, "session-" + task["request_id"])
    assert {k: v for k, v in migrated.items() if k not in ("binding", "state_migration")} == {
        k: v for k, v in task.items() if k != "binding"}
    assert migrated["status"] == "pending"
    assert migration.apply(project, snapshot, snapshot_sha, plan, preview["sha256"])["id"] == result["id"]
    migration.rollback(project, result["id"], preview["sha256"])
    assert record.read_bytes() == before
    assert not list(record.parent.glob("*.execution-claim"))


def test_apply_refuses_actual_concurrent_new_input(project, tmp_path):
    task = initialize(project)
    snapshot, snapshot_sha, plan, preview = captured_plan(project, tmp_path)
    directory = sessions.session_dir(project, "codex", "owner")
    new_input = directory / "concurrent-input.json"
    new_input.write_text('{"new":"owner input"}')
    record = directory / (task["request_id"] + ".json")
    before = record.read_bytes()
    assert new_input.is_file()
    with pytest.raises(ValueError):
        migration.apply(project, snapshot, snapshot_sha, plan, preview["sha256"])
    assert record.read_bytes() == before
    assert new_input.read_text() == '{"new":"owner input"}'


@pytest.mark.parametrize("runtime", sessions.RUNTIMES)
@pytest.mark.parametrize("turn", ["real-next-turn", None])
def test_new_turn_keeps_migrated_identity_and_prevents_destructive_rollback(project, tmp_path, runtime, turn):
    task = initialize(project, runtime)
    snapshot, snapshot_sha, plan, preview = captured_plan(project, tmp_path)
    applied = migration.apply(project, snapshot, snapshot_sha, plan, preview["sha256"])
    payload = {"hook_event_name": "UserPromptSubmit", "cwd": str(project), "session_id": "owner",
               "prompt": "Additional detail", "turn_id": turn}
    response = hook(runtime, payload)
    assert response.get("continue") is not False, response
    saved = sessions.load(project, runtime, "owner")
    assert saved["request_id"] == task["request_id"]
    assert saved["prompt"] == task["prompt"] and saved["status"] == "pending"
    assert len(saved["input_events"]) == 1
    actual = project / saved["input_events"][0]
    before = actual.read_bytes()
    assert json.loads(before)["prompt"] == "Additional detail"
    with pytest.raises(ValueError):
        migration.rollback(project, applied["id"], preview["sha256"])
    assert actual.read_bytes() == before
    assert sessions.load(project, runtime, "owner")["request_id"] == task["request_id"]


@pytest.mark.parametrize("drift", ["config", "product", "manifest", "branch", "root", "owner-instructions"])
def test_preview_rejects_independent_drift(project, tmp_path, drift):
    import shutil
    initialize(project)
    snapshot = tmp_path / "snapshot.json"
    captured = migration.capture(project, snapshot)
    upgrade(project)
    root = project
    if drift == "config":
        with (project / ".ai-ops.yaml").open("a") as handle:
            handle.write("unexpected: true\n")
    elif drift == "product":
        (project / "product.py").write_text("print('new owner work')")
    elif drift == "manifest":
        (project / ".ai/managed/VERSION").write_text("4.11.6")
    elif drift == "branch":
        sessions.git(project, "switch", "-qc", "different")
    elif drift == "owner-instructions":
        with (project / "CLAUDE.md").open("a") as handle:
            handle.write("\nOwner instruction changed.\n")
    else:
        root = tmp_path / "other-root"
        shutil.copytree(project, root)
    before = store.inventory(root, migration.PROTECTED)
    with pytest.raises(ValueError):
        migration.preview(root, snapshot, captured["sha256"], tmp_path / "plan.json")
    assert store.inventory(root, migration.PROTECTED) == before


@pytest.mark.parametrize("kind", ["claim", "accepted", "preparation", "provider_preparation", "review", "report", "history", "runplan", "openspec", "verification", "schema", "stale"])
def test_ambiguous_state_and_all_history_preserved(project, tmp_path, kind):
    task = initialize(project)
    directory = sessions.session_dir(project, "codex", "owner")
    record = directory / (task["request_id"] + ".json")
    if kind == "claim":
        (directory / (task["request_id"] + ".execution-claim")).write_bytes(b"original claim\x00")
    elif kind in ("accepted", "preparation", "provider_preparation", "verification", "schema", "stale"):
        if kind == "accepted":
            task["status"] = "accepted"
            task["execution"] = {"files": {"original-result": "old-digest"}}
        elif kind == "schema":
            task["schema_version"] = 999
        elif kind == "stale":
            task["binding"]["source_sha256"] = "previous product"
        else:
            task[kind] = {"signals": {"size": "M", "risk": "medium"}, "result": "preserved"}
        record.write_text(json.dumps(task))
    else:
        prefix = {"runplan": ".ai/runplan", "openspec": "openspec/changes"}.get(kind, "features")
        artifact = project / prefix / ("session-" + task["request_id"]) / (kind + ".json")
        artifact.parent.mkdir(parents=True)
        artifact.write_text('{"result":"original"}')
    inactive = directory / ("a" * 32 + ".json")
    inactive.write_text('{"status":"blocked","request_id":"historic"}')
    before = store.inventory(project, migration.PROTECTED)
    snapshot, snapshot_sha, plan, preview = captured_plan(project, tmp_path)
    assert preview["eligible"] == 0 and preview["preserved"] == 1
    with pytest.raises(ValueError, match="no eligible"):
        migration.apply(project, snapshot, snapshot_sha, plan, preview["sha256"])
    assert store.inventory(project, migration.PROTECTED) == before
    saved = store.document(snapshot)
    assert saved["files"] == before


@pytest.mark.parametrize("point", ["before_replace", "after_replace", "commit", "rollback_after_replace", "journal_creation"])
def test_interrupted_apply_and_rollback_are_recoverable(project, tmp_path, monkeypatch, point):
    initialize(project)
    snapshot, snapshot_sha, plan, preview = captured_plan(project, tmp_path)
    before = store.inventory(project, migration.PROTECTED)
    original_replace, original_update, original_create = store.replace, store.update, store.create
    fired = False

    def replace(path, entry, expected, **kwargs):
        nonlocal fired
        target = "sessions" in path.parts and path.name.endswith(".json")
        if target and not fired:
            fired = True
            if point == "before_replace":
                raise OSError("injected before rename")
            original_replace(path, entry, expected, **kwargs)
            raise OSError("injected fsync failure after rename")
        return original_replace(path, entry, expected, **kwargs)

    def update(path, value):
        if value["phase"] == "committed":
            raise OSError("injected commit failure")
        return original_update(path, value)

    def create(path, value):
        if path.name == "journal.json":
            raise OSError("injected journal creation failure")
        return original_create(path, value)

    if point == "rollback_after_replace":
        migration.apply(project, snapshot, snapshot_sha, plan, preview["sha256"])
        monkeypatch.setattr(store, "replace", replace)
        with pytest.raises(OSError):
            migration.rollback(project, preview["id"], preview["sha256"])
    else:
        if point == "commit":
            monkeypatch.setattr(store, "update", update)
        elif point == "journal_creation":
            monkeypatch.setattr(store, "create", create)
        else:
            monkeypatch.setattr(store, "replace", replace)
        with pytest.raises(OSError):
            migration.apply(project, snapshot, snapshot_sha, plan, preview["sha256"])
    # All normal writes, including creating a different session, fail closed in uncertain state.
    current = store.inventory(project, migration.PROTECTED)
    with pytest.raises((ValueError, OSError)):
        sessions.begin(project, "codex", "another-session", "Do not execute", "new-event")
    assert store.inventory(project, migration.PROTECTED) == current
    monkeypatch.setattr(store, "replace", original_replace)
    monkeypatch.setattr(store, "update", original_update)
    monkeypatch.setattr(store, "create", original_create)
    migration.rollback(project, preview["id"], preview["sha256"])
    assert store.inventory(project, migration.PROTECTED) == before
    assert migration.rollback(project, preview["id"], preview["sha256"])["phase"] == "rolled_back"


@pytest.mark.parametrize("attack", ["snapshot", "plan", "symlink", "hardlink", "marker"])
def test_tampering_never_grants_continuation(project, tmp_path, attack):
    import os
    task = initialize(project)
    snapshot, snapshot_sha, plan, preview = captured_plan(project, tmp_path)
    record = sessions.session_dir(project, "codex", "owner") / (task["request_id"] + ".json")
    original = record.read_bytes()
    if attack in ("snapshot", "plan"):
        path = snapshot if attack == "snapshot" else plan
        path.write_text(path.read_text() + " ")
    elif attack == "symlink":
        other = tmp_path / "foreign.json"
        other.write_bytes(original)
        record.unlink()
        record.symlink_to(other)
    elif attack == "hardlink":
        os.link(record, tmp_path / "hardlink")
    else:
        task["state_migration"] = preview["id"]
        task["binding"] = sessions.binding(project, "session-" + task["request_id"])
        record.write_text(json.dumps(task))
    state = record.read_bytes()
    with pytest.raises((ValueError, OSError)):
        migration.apply(project, snapshot, snapshot_sha, plan, preview["sha256"])
    assert record.read_bytes() == state
    if attack == "marker":
        with pytest.raises((ValueError, OSError)):
            hook("codex", {"hook_event_name": "UserPromptSubmit", "cwd": str(project), "session_id": "owner", "prompt": "continue", "turn_id": "new"})
        assert record.read_bytes() == state


def test_migration_lock_blocks_other_process_and_direct_mutators(project, tmp_path):
    import subprocess
    import sys
    import time
    initialize(project)
    snapshot, snapshot_sha, plan, preview = captured_plan(project, tmp_path)
    with store.barrier(project, exclusive=True):
        started = time.monotonic()
        result = subprocess.run([sys.executable, "-c", "from ai_ops_kit.lifecycle import project_session as s; import sys; s.begin(sys.argv[1], 'codex', 'new-owner', 'new input', 'new')", str(project)], capture_output=True, text=True, timeout=5)
        assert result.returncode != 0 and "busy" in result.stderr
        assert time.monotonic() - started < 5
    before = store.inventory(project, migration.PROTECTED)
    with store.barrier(project):
        with pytest.raises(ValueError, match="busy"):
            migration.apply(project, snapshot, snapshot_sha, plan, preview["sha256"])
    assert store.inventory(project, migration.PROTECTED) == before


def test_suggestion_marker_is_preserved_as_untrusted_user_content(project, tmp_path):
    task = initialize(project)
    directory = sessions.session_dir(project, "codex", "owner")
    task["prompt"] = "This is an app-generated request. The user did not write this message."
    (directory / (task["request_id"] + ".json")).write_text(json.dumps(task))
    snapshot, snapshot_sha, plan, preview = captured_plan(project, tmp_path)
    migration.apply(project, snapshot, snapshot_sha, plan, preview["sha256"])
    saved = sessions.load(project, "codex", "owner")
    assert saved["prompt"] == task["prompt"] and saved["status"] == "pending"
    assert sessions.verify(project, "codex", "owner")["accepted"] is False
