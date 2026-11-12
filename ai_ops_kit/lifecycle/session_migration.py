"""Explicit pending-state migration; evidence is not approval or task acceptance."""
from __future__ import annotations

import base64
import contextlib
import copy
import json
from pathlib import Path
import re

import yaml

from ai_ops_kit.lifecycle import project_session as sessions
from ai_ops_kit.lifecycle import session_migration_store as store

PROTECTED = (".ai/runtime", "features", ".ai/runplan", "openspec/changes", ".git/ai-ops/claims")
INSTALLER_RUNTIME = (".ai/runtime/backups", ".ai/runtime/last-update-report.json",
                     ".ai/runtime/ci-templates.json", ".ai/runtime/skill-prints.json")
CI_PRINTS = ".ai/runtime/ci-templates.json"
INSTALL = (".ai/managed", ".ai-ops.yaml", "ai-ops", "AGENTS.md", "CLAUDE.md", ".codex", ".claude")
FIELDS = {"schema_version", "request_id", "session_id", "runtime", "turn_id", "prompt", "status",
          "binding", "intake", "blocker", "next_step", "input_receipts", "input_events", "input_latest"}


def protected_files(root):
    return store.inventory(root, PROTECTED, exclude=INSTALLER_RUNTIME)


def _root(root):
    root = sessions.project_root(root)
    if not (root / ".git").is_dir() or (root / ".git").is_symlink():
        raise ValueError("migration currently requires a standalone checkout, not a linked worktree")
    return root


def _external(root, path):
    path = Path(path).absolute()
    if path.resolve().is_relative_to(root):
        raise ValueError("private snapshot/preview must be outside the project")
    return path


def _checked(path, checksum):
    data = store.raw(store.read(path, atomic=True))
    if store.sha(data) != checksum:
        raise ValueError("migration evidence digest mismatch")
    return json.loads(data)


def _manifest(root):
    files = store.inventory(root, (".ai/managed",))
    expected = store.document(root / ".ai/managed/.checksums.json").get("files")
    actual = {key.removeprefix(".ai/managed/"): store.sha(store.raw(value)) for key, value in files.items()
              if Path(key).name not in (".checksums.json", ".provenance.json", ".update-lock", ".gitkeep")}
    if not isinstance(expected, dict) or expected != actual:
        raise ValueError("managed manifest/checksums mismatch")


def _kit_ci_prints(root):
    """Отпечатки CI-файлов, которые записал сам кит: {имя шаблона: sha256 текста}.

    Обновление кита освежает НЕТРОНУТЫЙ владельцем workflow (`stale-ours`) и записывает новый
    отпечаток. Без этого знания миграция принимала такое освежение за «независимую правку продукта»
    и отказывала при первом же изменении шаблона CI (#1512). Битый файл — пусто: тогда всё
    сравнивается побайтно, как раньше (строже, а не мягче).
    """
    try:
        prints = json.loads((root / CI_PRINTS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in prints.items() if isinstance(v, str)} if isinstance(prints, dict) else {}


def _product(root):
    files = sessions.git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0")
    kit_ci = _kit_ci_prints(root)
    result = {}
    for name in sorted(set(files)):
        if not name or name == ".ai-ops.yaml" or name.startswith((".ai/runtime/", ".ai/managed/", ".ai/generated/", ".ai/usage/", ".ai/worktrees/")):
            continue
        try:
            entry = store.read(root / name)
            content = store.raw(entry)
            if name == "CLAUDE.md":
                # Stock deliver_assets removes exactly these two blank separator lines.
                # Owner text, all other whitespace and file mode remain checked.
                boundary = b"<!-- AI-OPS-COMMUNICATION-POLICY:END -->\n"
                following = b"<!-- AI-OPS-PROJECT-SESSION:BEGIN -->"
                content = content.replace(boundary + b"\n\n" + following, boundary + following, 1)
            digest = store.sha(content)
            if name.startswith(".github/") and kit_ci.get(Path(name).name) == digest:
                digest = "kit-ci-template"     # содержимое ровно то, что записал кит, — не правка владельца
            result[name] = [digest, entry["mode"]]
        except FileNotFoundError:
            result[name] = None
    return result


def _context(root):
    _manifest(root)
    return {"binding": sessions.binding(root), "product": _product(root),
            "config": yaml.safe_load((root / ".ai-ops.yaml").read_text())}


def _unchanged_install(before, after):
    for key in ("root", "branch", "head"):
        if before["binding"][key] != after["binding"][key]:
            raise ValueError("root/branch/HEAD changed; migration refused")
    versions = [context["binding"]["version"] for context in (before, after)]
    if any(not re.fullmatch(r"\d+\.\d+\.\d+", version) for version in versions) or versions[0].split(".")[0] != versions[1].split(".")[0]:
        raise ValueError("migration supports a same-major stable-version transition only")
    configs = [copy.deepcopy(context["config"]) for context in (before, after)]
    for config, version in zip(configs, versions):
        if config["parent"].pop("installed_version") != version:
            raise ValueError("installer version mismatch")
    if configs[0] != configs[1] or before["product"] != after["product"]:
        raise ValueError("independent product/config change; migration refused")


def _tasks(root):
    for active in sorted((root / ".ai/runtime/sessions").glob("project-*/active.json")):
        request = store.document(active).get("request_id")
        if not isinstance(request, str) or not re.fullmatch("[a-f0-9]{32}", request):
            raise ValueError("invalid active identity")
        path = active.parent / (request + ".json")
        task = store.document(path)
        if (task.get("request_id") != request or sessions.session_dir(root, task.get("runtime"), task.get("session_id")) != active.parent):
            raise ValueError("request identity/path mismatch")
        yield path.relative_to(root).as_posix(), task


def capture(root, output):
    root = _root(root)
    output = _external(root, output)
    with store.barrier(root, exclusive=True), _old_locks(root):
        before = _context(root)
        files = protected_files(root)
        install = store.inventory(root, INSTALL)
        bindings = {path: sessions.binding(root, "session-" + task["request_id"]) for path, task in _tasks(root)}
        if files != protected_files(root) or before != _context(root):
            raise ValueError("state changed during capture; no snapshot created")
        snapshot = {"kind": "session-state-snapshot", "schema_version": 1, "context": before,
                    "files": files, "install": install, "bindings": bindings}
        return {"sha256": store.create(output, snapshot), "files": len(files), "active": len(bindings)}


def _eligible(root, task, captured_binding):
    if task.get("schema_version") != 1 or set(task) - FIELDS or task.get("status") != "pending":
        return "preserved: execution/preparation/unknown state requires separate disposition"
    if task.get("binding") != captured_binding:
        return "preserved: original binding already stale"
    fid = "session-" + task["request_id"]
    directory = sessions.session_dir(root, task["runtime"], task["session_id"])
    # No previous execution, review, specification or result is promoted to new-code evidence.
    artifacts = sessions.artifact_inputs(root, fid)
    if any(not name.startswith(".ai/runtime/sessions/") for name in artifacts):
        return "preserved: existing task artifacts require separate disposition"
    permitted = {task["request_id"] + ".json", task["request_id"] + ".inputs"}
    if any(path.name not in permitted for path in directory.glob(task["request_id"] + "*")):
        return "preserved: claim/history/verification remnants"
    return None


def _plan(root, snapshot, snapshot_sha):
    if snapshot.get("kind") != "session-state-snapshot" or snapshot.get("schema_version") != 1:
        raise ValueError("unsupported migration snapshot")
    context = _context(root)
    _unchanged_install(snapshot["context"], context)
    files = protected_files(root)
    if files != snapshot["files"]:
        raise ValueError("session/artifact/claim state changed since capture")
    transaction = store.sha(store.encoded([snapshot_sha, context]))
    changes, preserved = {}, {}
    for path, task in _tasks(root):
        reason = _eligible(root, task, snapshot["bindings"].get(path))
        if reason:
            preserved[path] = reason
            continue
        new = copy.deepcopy(task)
        new["binding"] = sessions.binding(root, "session-" + task["request_id"])
        new["state_migration"] = transaction
        changes[path] = {"before": files[path], "after": {
            "data": base64.b64encode(store.encoded(new)).decode(), "mode": files[path]["mode"]}}
    if files != protected_files(root) or context != _context(root):
        raise ValueError("state changed during preview")
    return {"kind": "session-state-migration", "schema_version": 1, "id": transaction,
            "snapshot_sha256": snapshot_sha, "context": context, "files": files,
            "changes": changes, "preserved": preserved}


def preview(root, snapshot_path, snapshot_sha, output):
    root = _root(root)
    output = _external(root, output)
    with store.barrier(root, exclusive=True), _old_locks(root):
        plan = _plan(root, _checked(snapshot_path, snapshot_sha), snapshot_sha)
        return {"sha256": store.create(output, plan), "id": plan["id"],
                "eligible": len(plan["changes"]), "preserved": len(plan["preserved"])}


def _transaction(root, transaction):
    if not isinstance(transaction, str) or not re.fullmatch("[a-f0-9]{64}", transaction):
        raise ValueError("invalid migration transaction id")
    return root / store.AREA / transaction


def _state(root, plan, *, mixed=False):
    files = protected_files(root)
    expected = dict(plan["files"])
    for path, change in plan["changes"].items():
        current = files.get(path)
        allowed = (change["before"], change["after"]) if mixed else (change["after"],)
        if current not in allowed:
            raise ValueError("migration target diverged; preserve new inputs and inspect")
        expected[path] = current
    if files != expected:
        raise ValueError("concurrent input/artifact/claim detected; rollback cannot erase it")
    if _context(root) != plan["context"]:
        raise ValueError("installation/product context changed; state operation refused")
    return files


@contextlib.contextmanager
def _old_locks(root):
    # Cooperating old runners use these locks; old begin implementations still require quiescence.
    with contextlib.ExitStack() as stack:
        for directory in sorted((root / ".ai/runtime/sessions").glob("project-*")):
            if directory.is_symlink() or not directory.is_dir():
                raise ValueError("unsafe session directory")
            for name in ("preparation", "requests"):
                stack.enter_context(sessions.session_lock(directory / name))
        yield


def apply(root, snapshot_path, snapshot_sha, plan_path, plan_sha):
    root = _root(root)
    plan = _checked(plan_path, plan_sha)
    directory = _transaction(root, plan["id"])
    with store.barrier(root, exclusive=True), _old_locks(root):
        if (directory / "journal.json").exists():
            existing = _checked(directory / "plan.json", plan_sha)
            if existing != plan or store.document(directory / "journal.json", atomic=True).get("phase") != "committed":
                raise ValueError("transaction exists with another outcome; inspect, do not repeat")
            _state(root, plan)
            return {"id": plan["id"], "phase": "committed", "changed": len(plan["changes"])}
        expected = _plan(root, _checked(snapshot_path, snapshot_sha), snapshot_sha)
        if plan != expected:
            raise ValueError("preview no longer matches revalidated migration")
        if not plan["changes"]:
            raise ValueError("no eligible pending states; preserved records need separate disposition")
        # Intent is durable before the first replacement. Partial creation fails closed.
        store.create(directory / "plan.json", plan)
        journal = {"id": plan["id"], "plan_sha256": plan_sha, "phase": "applying"}
        store.create(directory / "journal.json", journal)
        for path, change in plan["changes"].items():
            _state(root, plan, mixed=True)
            store.replace(root / path, change["after"], change["before"], staging=directory / "staging")
        _state(root, plan)
        journal["phase"] = "committed"
        store.update(directory / "journal.json", journal)
        return {"id": plan["id"], "phase": "committed", "changed": len(plan["changes"])}


def rollback(root, transaction, plan_sha, plan_path=None):
    root = _root(root)
    directory = _transaction(root, transaction)
    with store.barrier(root, exclusive=True, recovery=True), _old_locks(root):
        try:
            plan = _checked(directory / "plan.json", plan_sha)
        except FileNotFoundError:
            if plan_path is None:
                raise ValueError("interrupted evidence creation: rollback needs original --plan and digest") from None
            plan = _checked(plan_path, plan_sha)
            if plan.get("id") != transaction:
                raise ValueError("recovery plan identity mismatch") from None
            _state(root, plan, mixed=True)
            store.create(directory / "plan.json", plan)
        try:
            journal = store.document(directory / "journal.json", atomic=True)
        except FileNotFoundError:
            # Plan creation can commit before journal creation fails. No task write precedes it.
            journal = {"id": transaction, "plan_sha256": plan_sha, "phase": "prepared"}
            _state(root, plan, mixed=True)
            store.create(directory / "journal.json", journal)
        if plan["id"] != transaction or journal.get("plan_sha256") != plan_sha:
            raise ValueError("rollback identity mismatch")
        files = _state(root, plan, mixed=True)  # ALL conflicts checked before ANY replacement.
        if journal.get("phase") == "rolled_back":
            if files != plan["files"]:
                raise ValueError("rolled back transaction diverged")
            return {"id": transaction, "phase": "rolled_back"}
        journal["phase"] = "rolling_back"
        store.update(directory / "journal.json", journal)
        for path, change in plan["changes"].items():
            current = _state(root, plan, mixed=True)[path]
            if current == change["after"]:
                store.replace(root / path, change["before"], current, staging=directory / "staging")
        if protected_files(root) != plan["files"]:
            raise ValueError("rollback incomplete; preserve journal and inspect")
        journal["phase"] = "rolled_back"
        store.update(directory / "journal.json", journal)
        return {"id": transaction, "phase": "rolled_back"}


def continuation(root, task):
    """Verify migration against immutable plan; input additions cannot grant acceptance."""
    directory = _transaction(Path(root), task.get("state_migration"))
    journal = store.document(directory / "journal.json", atomic=True)
    if journal.get("phase") != "committed":
        raise ValueError("migration has not committed")
    plan = _checked(directory / "plan.json", journal["plan_sha256"])
    path = str((sessions.session_dir(root, task["runtime"], task["session_id"]) / (task["request_id"] + ".json")).relative_to(root))
    expected = json.loads(store.raw(plan["changes"][path]["after"]))
    mutable = ("input_receipts", "input_events", "input_latest")
    if {k: v for k, v in task.items() if k not in mutable} != {k: v for k, v in expected.items() if k not in mutable}:
        raise ValueError("migrated request changed beyond append-only user input")
    prior = expected.get("input_events", [])
    if task.get("input_events", [])[:len(prior)] != prior or any(task.get("input_receipts", {}).get(k) != v for k, v in expected.get("input_receipts", {}).items()):
        raise ValueError("migration input history changed")
    sessions.pending(root, task["runtime"], task["session_id"])
    artifacts = sessions.artifact_inputs(root, "session-" + task["request_id"])
    if any(not name.startswith(".ai/runtime/sessions/") for name in artifacts):
        raise ValueError("new task artifacts require normal preparation, not migration continuation")
