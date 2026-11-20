"""Explicit prepared-session disposition; original review base never becomes runtime state."""
from __future__ import annotations

import base64
import contextlib
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import shutil
import stat
import sys
import tempfile
import venv

import yaml

from ai_ops_kit.lifecycle import project_session as sessions
from ai_ops_kit.lifecycle import session_migration as pending
from ai_ops_kit.lifecycle import session_migration_store as store

RUNTIME_KEYS = ("root", "branch", "version", "managed_sha256", "config_sha256")
KIND = "prepared-session-update-snapshot"
PREPARED_UPDATE_PROTOCOL = 1


def _git_path(root, *args):
    path = Path(sessions.git(root, "rev-parse", *args))
    return (root / path).resolve() if not path.is_absolute() else path.resolve()


def git_identity(root):
    """Linked worktrees have their own index and shared configuration/claims."""
    gitdir = _git_path(root, "--git-dir")
    common = _git_path(root, "--git-common-dir")
    if not gitdir.is_dir() or not common.is_dir():
        raise ValueError("invalid Git worktree identity")
    files = {}
    for path in (root / ".git", gitdir / "HEAD", gitdir / "index", gitdir / "commondir",
                 gitdir / "config.worktree", common / "config", common / "packed-refs"):
        if path.is_file():
            files[str(path)] = store.read(path)
    # Claim ownership and shared refs are never part of the install projection.
    return {"gitdir": str(gitdir), "common": str(common), "files": files,
            "claims": store.inventory(common, ("ai-ops", "refs"))}


def _task(root, runtime, session):
    directory = sessions.session_dir(root, runtime, session)
    active = store.document(directory / "active.json")
    request = active.get("request_id")
    if not isinstance(request, str) or len(request) != 32 or any(c not in "0123456789abcdef" for c in request):
        raise ValueError("invalid prepared request identity")
    path = directory / (request + ".json")
    task = store.document(path)
    if (task.get("schema_version") != 1 or task.get("request_id") != request
            or task.get("runtime") != runtime or task.get("session_id") != session
            or task.get("status") not in ("running", "blocked")):
        raise ValueError("not an active prepared request")
    execution = task.get("execution") or {}
    if (execution.get("mode") != "current-session" or execution.get("prepared") is not True
            or execution.get("verification_ready") or execution.get("completion_binding")):
        raise ValueError("prepared current-session disposition only; never accepted execution")
    verification = task.get("verification")
    if verification and verification.get("phase") not in ("finished", "failed"):
        raise ValueError("verification outcome unknown or worker active; disposition refused")
    if store.raw(store.read(directory / (request + ".execution-claim"))) != b"":
        raise ValueError("invalid execution claim")
    return path, task


def capture(root, runtime, session, output):
    root = sessions.project_root(root)
    output = pending._external(root, output)
    with store.barrier(root, exclusive=True), pending._old_locks(root), sessions.reading():
        path, task = _task(root, runtime, session)
        context = pending._context(root)
        expected = runtime_binding(root, task)
        if any(context["binding"].get(k) != expected.get(k) for k in RUNTIME_KEYS):
            raise ValueError("original runtime binding already stale")
        for relative, checksum in task["execution"]["files"].items():
            if store.sha(store.raw(store.read(sessions.within(root, relative)))) != checksum:
                raise ValueError("prepared artifact changed")
        artifacts = sessions.artifact_inputs(root, "session-" + task["request_id"])
        snapshot = {"kind": KIND, "schema_version": 1, "runtime": runtime, "session": session,
                    "path": path.relative_to(root).as_posix(), "task": store.read(path),
                    "context": context, "git": git_identity(root), "artifacts": artifacts,
                    "files": pending.protected_files(root), "install": store.inventory(root, pending.INSTALL + (".github",))}
        if (context != pending._context(root) or snapshot["git"] != git_identity(root)
                or snapshot["files"] != pending.protected_files(root)):
            raise ValueError("state changed during capture")
        return {"sha256": store.create(output, snapshot), "request_id": task["request_id"]}


def runtime_binding(root, task):
    """Journal authorizes runtime context only, never a new product review base."""
    transaction = task.get("prepared_update")
    if not transaction:
        return task["binding"]
    directory = pending._transaction(Path(root), transaction)
    journal = store.document(directory / "journal.json", atomic=True)
    if journal.get("phase") != "committed" or journal.get("kind") != "prepared-session-update":
        raise ValueError("prepared update is not committed")
    plan = pending._checked(directory / "plan.json", journal["plan_sha256"])
    original = json.loads(store.raw(plan["task"]["after"]))
    immutable = ("schema_version", "request_id", "session_id", "runtime", "turn_id", "prompt", "binding")
    if (plan["id"] != transaction or plan["root"] != str(Path(root))
            or any(task.get(k) != original.get(k) for k in immutable)
            or task.get("execution", {}).get("mode") != "current-session"):
        raise ValueError("prepared update identity or original review base mismatch")
    return plan["context"]["binding"]


def _snapshot(root, path, checksum):
    saved = pending._checked(path, checksum)
    if saved.get("kind") != KIND or saved.get("schema_version") != 1:
        raise ValueError("unsupported prepared snapshot")
    if saved["context"]["binding"]["root"] != str(root):
        raise ValueError("snapshot belongs to another project")
    return saved


def _unchanged(root, saved):
    if (saved["context"] != pending._context(root) or saved["git"] != git_identity(root)
            or saved["files"] != pending.protected_files(root)
            or saved["install"] != store.inventory(root, pending.INSTALL + (".github",))):
        raise ValueError("project, prepared state or installation changed after capture")
    path, task = _task(root, saved["runtime"], saved["session"])
    if store.read(path) != saved["task"]:
        raise ValueError("prepared task changed after capture")
    return path, task


def _source(source, revision):
    source = Path(source).resolve()
    if (sessions.git(source, "rev-parse", "--show-toplevel") != str(source)
            or sessions.git(source, "rev-parse", "HEAD") != revision
            or sessions.git(source, "status", "--porcelain", "--untracked-files=all")):
        raise ValueError("stock source must be a clean checkout of the exact reviewed revision")
    if (not (source / "installer/ai_ops.py").is_file()
            or (source / "installer/ai_ops.py").is_symlink()
            or any(line.startswith("120000 ") for line in sessions.git(source, "ls-files", "--stage").splitlines())):
        raise ValueError("stock installer entry point absent")
    return source


def _environment(source, executable=None):
    env = dict({k: v for k, v in os.environ.items() if not k.startswith("PYTHON")},
               PYTHONPATH=str(source), PYTHONDONTWRITEBYTECODE="1",
               PYTHONNOUSERSITE="1", GIT_OPTIONAL_LOCKS="0")
    # Stock supports global prompt delivery when set; this operation is project-only.
    env.pop("CODEX_HOME", None)
    if executable:
        env.update(AI_OPS_PYTHON=str(executable), VIRTUAL_ENV=str(Path(executable).parent.parent),
                   PYTHONPYCACHEPREFIX=str(Path(executable).parent.parent / "private-bytecode"))
    return env


@contextlib.contextmanager
def _python():
    """Private interpreter/dependency copy, without parent editable/.pth/site packages."""
    with tempfile.TemporaryDirectory(prefix="ai-ops-prepared-python-") as temporary:
        directory = Path(temporary).resolve()
        venv.EnvBuilder(with_pip=False, system_site_packages=False).create(directory)
        site = directory / "lib" / ("python" + str(sys.version_info.major) + "." + str(sys.version_info.minor)) / "site-packages"
        dependency = Path(yaml.__file__).resolve().parent
        shutil.copytree(dependency, site / "yaml", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        yield directory / "bin/python"


PROBE = """
import importlib.util, json, hashlib, sys, tempfile, shutil
from pathlib import Path
entry = Path(sys.argv[1]) / 'installer/ai_ops.py'
spec = importlib.util.spec_from_file_location('prepared_stock_installer', entry)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
core = module._core()
from ai_ops_kit.lifecycle import session_prepared_update
if session_prepared_update.PREPARED_UPDATE_PROTOCOL != 1:
 raise ValueError('source does not support the prepared continuation protocol')
from ai_ops_kit.engine import run_plan
for name, loaded in tuple(sys.modules.items()):
 if name == 'ai_ops_kit' or name.startswith('ai_ops_kit.'):
  origin = Path(loaded.__file__).resolve()
  if not origin.is_relative_to(Path(sys.argv[1]).resolve() / 'ai_ops_kit'):
   raise ValueError('source import origin mismatch: ' + name)
task = json.loads(Path(sys.argv[2]).read_text())
plan = run_plan.build_plan(dict(task['execution']['signals'], task_text=task['prompt']),
                          workitem_id='session-' + task['request_id'])
driver = module._plan_merge_setup()
hook_changes = []
with tempfile.TemporaryDirectory(prefix='ai-ops-hook-preview-') as preview:
 target = Path(preview).resolve()
 names = ('.ai-ops.yaml', 'AGENTS.md', 'CLAUDE.md', '.codex/hooks.json', '.claude/settings.json')
 before = {}
 for name in names:
  path = Path.cwd() / name
  before[name] = path.read_bytes() if path.is_file() else None
  if before[name] is not None:
   (target / name).parent.mkdir(parents=True, exist_ok=True)
   shutil.copy2(path, target / name)
 core.ensure_team_session(target)
 module._lint_hook_setup().ensure_lint_hook(target)
 module._lint_hook_setup().ensure_lint_hook(target, runtime='codex',
             active='codex' in (core._configured_runtimes() or []))
 for name in ('.codex/hooks.json', '.claude/settings.json'):
  path = target / name
  after = path.read_bytes() if path.is_file() else None
  if after != before[name]:
   hook_changes.append(name)
paths = core._footprint_paths() + [Path.cwd() / '.ai/runtime/last-update-report.json',
                                 Path.cwd() / '.ai/runtime/backups']
print(json.dumps({'paths': [str(p.relative_to(Path.cwd())) for p in paths],
 'version': core.pkg_version(),
 'hook_changes': hook_changes,
 'plan': {k: plan[k] for k in ('workitem_id', 'base_workflow', 'gates', 'task_hash')},
 'merge_driver': {'merge.' + driver.DRIVER_NAME + '.name': 'AI Ops: структурное слияние planning/plan.yaml',
                  'merge.' + driver.DRIVER_NAME + '.driver': 'python3 ' + driver.DELIVERED + ' %O %A %B'},
 'managed': {rel: hashlib.sha256(core.managed_content(rel, p.read_bytes())).hexdigest()
             for p, rel in core.managed_set()}}))
"""


def _check_driver(root, directory, settings):
    # Git serializes a setting on write even if its parsed value is identical.
    original = store.raw(store.read(_git_path(root, "--git-common-dir") / "config"))
    preview = directory / "config.preview"
    preview.write_bytes(original)
    for key, value in settings.items():
        check = subprocess.run(["git", "-C", str(root), "config", "--local", "--null", "--get-all", key],
                               capture_output=True, timeout=10)
        if check.returncode or check.stdout != os.fsencode(value) + b"\0":
            raise ValueError("shared merge-driver differs; separate owner disposition required before update")
        write = subprocess.run(["git", "config", "--file", str(preview), key, value],
                               capture_output=True, timeout=10)
        if write.returncode:
            raise ValueError("could not rehearse the shared Git config write")
    if preview.read_bytes() != original:
        raise ValueError("stock merge-driver registration would rewrite shared Git config")


def _probe(root, source, directory, timeout, task, executable):
    payload = directory / "task.json"
    store.create(payload, task)
    result = sessions.run_process([str(executable), "-P", "-c", PROBE, str(source), str(payload)], root,
                                  directory, timeout=timeout, env=_environment(source, executable))
    if result.returncode:
        raise ValueError("stock footprint probe failed")
    # run_process returns bounded tails; the complete private stdout contains the manifest.
    description = store.document(directory / "process.stdout.log")
    if description["hook_changes"]:
        raise ValueError("new hook definitions/settings require separate approval before update")
    for name in description["paths"]:
        if (not name or Path(name).is_absolute() or ".." in Path(name).parts
                or name == ".git" or name.startswith(".git/")):
            raise ValueError("stock footprint outside the project")
    _check_driver(root, directory, description["merge_driver"])
    before_version = runtime_binding(root, task)["version"]
    versions = (before_version, description["version"])
    if (not all(isinstance(v, str) and re.fullmatch(r"\d+\.\d+\.\d+", v) for v in versions)
            or before_version.split(".")[0] != description["version"].split(".")[0]):
        raise ValueError("same-major stock update only")
    actual = yaml.safe_load(store.raw(store.read(root / "features" / ("session-" + task["request_id"]) / "run-plan.yaml")))
    if any(actual.get(k) != v for k, v in description["plan"].items()):
        raise ValueError("new source changes the prepared RunPlan contract; update refused")
    return description


def _preserved(root, saved, description):
    context = pending._context(root)
    if (saved["git"] != git_identity(root) or saved["files"] != pending.protected_files(root)
            or any(context["binding"][k] != saved["context"]["binding"][k] for k in ("root", "head", "branch"))):
        raise ValueError("Git, session, claim or task artifacts changed during stock update")
    configs = [copy.deepcopy(c["config"]) for c in (saved["context"], context)]
    for cfg in configs:
        cfg["parent"].pop("installed_version")
    if configs[0] != configs[1]:
        raise ValueError("owner configuration changed during stock update")
    if context["binding"]["version"] != description["version"]:
        raise ValueError("installed version differs from pinned stock")
    for name in (".codex/hooks.json", ".codex/config.toml", ".claude/settings.json"):
        actual = store.read(root / name) if (root / name).exists() else None
        if actual != saved["install"].get(name):
            raise ValueError("hook/trust/settings change needs a separate approved operation")
    allowed = tuple(description["paths"])
    outside = lambda files: {k: v for k, v in files.items()
                            if not any(k == p or k.startswith(p + "/") for p in allowed)}
    if outside(saved["context"]["product"]) != outside(context["product"]):
        raise ValueError("owner files outside stock footprint changed")
    manifest = store.document(root / ".ai/managed/.checksums.json")
    if manifest.get("files") != description["managed"]:
        raise ValueError("installed managed files do not match the exact stock source")
    report = store.document(root / ".ai/runtime/last-update-report.json")
    if (report.get("status") != "ok" or not report.get("smoke_tests")
            or any(t.get("status") != "pass" for t in report["smoke_tests"])):
        raise ValueError("stock update did not confirm smoke checks")
    return context


def _updated_task(task, transaction):
    new = copy.deepcopy(task)
    if new.get("verification"):
        new.setdefault("verification_history", []).append(new.pop("verification"))
    new["prepared_update"] = transaction
    new["next_step"] = "Продолжи ту же подготовленную задачу; прежние проверки и reviews требуют нового подтверждения."
    return new


def apply(root, snapshot_path, snapshot_sha, source, revision, *, timeout=180):
    """One stock installer execution inside the exclusive disposition barrier."""
    root = sessions.project_root(root)
    timeout = sessions._process_timeout(timeout)
    source = _source(source, revision)
    if source.is_relative_to(root) or root.is_relative_to(source):
        raise ValueError("stock source and target must be disjoint checkouts")
    saved = _snapshot(root, snapshot_path, snapshot_sha)
    transaction = store.sha(store.encoded([snapshot_sha, revision]))
    directory = pending._transaction(root, transaction)
    with store.barrier(root, exclusive=True), pending._old_locks(root), _python() as executable:
        path, task = _unchanged(root, saved)
        if directory.exists():
            raise ValueError("prepared update already started; inspect the durable outcome, never repeat")
        with tempfile.TemporaryDirectory(prefix="ai-ops-prepared-probe-") as temporary:
            description = _probe(root, source, Path(temporary).resolve(), timeout, task, executable)
        _source(source, revision)
        _unchanged(root, saved)
        install = store.inventory(root, description["paths"])
        intent = {"kind": "prepared-session-update", "id": transaction, "root": str(root),
                  "source_revision": revision, "snapshot_sha256": snapshot_sha,
                  "snapshot": saved, "description": description, "install_before": install}
        store.create(directory / "intent.json", intent)
        journal = {"kind": "prepared-session-update", "id": transaction, "phase": "installing"}
        store.create(directory / "journal.json", journal)
        try:
            result = sessions.run_process([str(executable), "-P", str(source / "installer/ai_ops.py"),
                "update", "--in-place"], root, directory, timeout=timeout, env=_environment(source, executable))
            if result.returncode:
                raise ValueError("stock installer failed; inspect before any rollback or retry")
            _source(source, revision)
            context = _preserved(root, saved, description)
            after = store.inventory(root, description["paths"])
            task_after = {"data": base64.b64encode(store.encoded(_updated_task(task, transaction))).decode(),
                          "mode": saved["task"]["mode"]}
            plan = {**intent, "context": context, "install_after": after,
                    "task": {"path": str(path.relative_to(root)), "before": saved["task"], "after": task_after}}
            plan_sha = store.create(directory / "plan.json", plan)
            journal.update(phase="applying", plan_sha256=plan_sha)
            store.update(directory / "journal.json", journal)
            _preserved(root, saved, description)
            store.replace(path, task_after, saved["task"], staging=directory / "staging")
            journal["phase"] = "committed"
            store.update(directory / "journal.json", journal)
            return {"id": transaction, "phase": "committed", "plan_sha256": plan_sha,
                    "source_revision": revision, "accepted": False, "models": 0}
        except (OSError, ValueError, KeyError, subprocess.TimeoutExpired, KeyboardInterrupt):
            # Durable installing/applying blocks all normal continuations. Unknown writes
            # are not automatically replayed or declared rolled back.
            raise


def _entry(path):
    try:
        return store.read(path)
    except FileNotFoundError:
        return None


def _stage_name(path):
    return "restore-" + store.sha(os.fsencode(path))


def _discard_restore_stage(path, staging):
    """Recover only the transaction's private staging name under the exclusive barrier."""
    slot = staging / _stage_name(path)
    try:
        with store.parent(slot) as (stage, name):
            info = os.stat(name, dir_fd=stage, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink not in (1, 2):
                raise ValueError("unexpected rollback staging entry")
            if info.st_nlink == 2:
                with store.parent(path) as (dest, target):
                    twin = os.stat(target, dir_fd=dest, follow_symlinks=False)
                    if not os.path.samestat(info, twin):
                        raise ValueError("unrelated hard link in rollback staging")
                    os.fsync(dest)
            os.unlink(name, dir_fd=stage)
            os.fsync(stage)
    except FileNotFoundError:
        if slot.exists() or slot.is_symlink():
            raise ValueError("rollback staging link identity changed") from None


def _recreate(path, before, staging):
    # Durable bytes first. link() publishes create-only even if an owner raced the CAS.
    with store.parent(path, create=True) as (dest, target), store.parent(
            staging / _stage_name(path), create=True) as (stage, name):
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=stage)
        with os.fdopen(fd, "wb") as handle:
            handle.write(store.raw(before))
            handle.flush()
            os.fchmod(handle.fileno(), before["mode"])
            os.fsync(handle.fileno())
        os.link(name, target, src_dir_fd=stage, dst_dir_fd=dest, follow_symlinks=False)
        os.fsync(dest)
        os.unlink(name, dir_fd=stage)
        os.fsync(stage)


def _restore_file(path, before, after, staging):
    if _entry(path) != after:
        raise ValueError("rollback CAS conflict; concurrent bytes preserved")
    if before is not None and after is not None:
        store.replace(path, before, after, staging=staging)
    elif before is None:
        with store.parent(path) as (parent, name):
            if _entry(path) != after:
                raise ValueError("rollback deletion conflict")
            os.unlink(name, dir_fd=parent)
            os.fsync(parent)
    else:
        _recreate(path, before, staging)


def _rollback_state(root, plan):
    snapshot = plan["snapshot"]
    current = pending.protected_files(root)
    task = plan["task"]
    if current.get(task["path"]) not in (task["before"], task["after"]):
        raise ValueError("task/input/verification changed; rollback refused")
    current[task["path"]] = task["before"]
    if current != snapshot["files"] or git_identity(root) != snapshot["git"]:
        raise ValueError("claim, artifacts, Git or unrelated session changed; rollback refused")
    installed = store.inventory(root, plan["description"]["paths"])
    before, after = plan["install_before"], plan["install_after"]
    for name in set(before) | set(after) | set(installed):
        if installed.get(name) not in (before.get(name), after.get(name)):
            raise ValueError("installation has concurrent edits; rollback refused")
    # Outside bytes remain protected even while checksums/config are half restored.
    prefixes = tuple(plan["description"]["paths"])
    outside = lambda product: {k: v for k, v in product.items()
                              if not any(k == p or k.startswith(p + "/") for p in prefixes)}
    if outside(pending._product(root)) != outside(snapshot["context"]["product"]):
        raise ValueError("outside product bytes changed; rollback refused")
    return installed


def rollback(root, transaction, plan_sha):
    """Only exact known stock replacements can be undone; unknown installer exit stays blocked."""
    root = sessions.project_root(root)
    directory = pending._transaction(root, transaction)
    with store.barrier(root, exclusive=True, recovery=True), pending._old_locks(root):
        plan = pending._checked(directory / "plan.json", plan_sha)
        journal = store.document(directory / "journal.json", atomic=True)
        if (plan.get("id") != transaction or plan.get("root") != str(root)
                or journal.get("kind") != "prepared-session-update" or journal.get("plan_sha256") != plan_sha):
            raise ValueError("prepared rollback identity mismatch")
        if journal.get("phase") == "rolling_back":
            for name in plan["install_before"].keys() - plan["install_after"].keys():
                _discard_restore_stage(root / name, directory / "staging")
        installed = _rollback_state(root, plan)
        journal["phase"] = "rolling_back"
        store.update(directory / "journal.json", journal)
        task = plan["task"]
        if _entry(root / task["path"]) == task["after"]:
            store.replace(root / task["path"], task["before"], task["after"], staging=directory / "staging")
        for name in sorted(set(plan["install_before"]) | set(plan["install_after"])):
            before, current = plan["install_before"].get(name), installed.get(name)
            if current != before:
                _restore_file(root / name, before, current, directory / "staging")
        if store.inventory(root, plan["description"]["paths"]) != plan["install_before"]:
            raise ValueError("prepared rollback incomplete")
        _unchanged(root, plan["snapshot"])
        journal["phase"] = "rolled_back"
        store.update(directory / "journal.json", journal)
        return {"id": transaction, "phase": "rolled_back", "accepted": False, "models": 0}
