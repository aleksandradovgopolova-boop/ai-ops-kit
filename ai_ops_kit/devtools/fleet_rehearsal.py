"""Предрелизная проверка штатного update на закреплённых публичных снимках (#1406)."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile

import yaml

from ai_ops_kit.engops.adoption_evidence import _installation_evidence


class RehearsalError(ValueError):
    """Нет необходимого свидетельства обновления/отката."""


def _require(ok, reason):
    if not ok:
        raise RehearsalError(reason)


def _env(*, protocol=""):
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "SYSTEMROOT"}}
    return dict(env, PYTHONDONTWRITEBYTECODE="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
                GIT_TERMINAL_PROMPT="0", GIT_ALLOW_PROTOCOL=protocol, GIT_NO_LAZY_FETCH="1",
                GIT_NO_REPLACE_OBJECTS="1", GIT_GRAFT_FILE=os.devnull, GIT_OPTIONAL_LOCKS="0",
                GIT_CONFIG_COUNT="2", GIT_CONFIG_KEY_0="maintenance.auto", GIT_CONFIG_VALUE_0="false",
                GIT_CONFIG_KEY_1="gc.auto", GIT_CONFIG_VALUE_1="0")


def _git(root, *args, protocol=""):
    proc = subprocess.run(["git", "-C", str(root), *args], env=_env(protocol=protocol),
                          capture_output=True, text=True, timeout=600 if protocol == "https" else 120)
    _require(proc.returncode == 0, f"git_{args[0]}_failed")
    return proc.stdout


def load_cases(path):
    doc = yaml.safe_load(Path(path).read_bytes())
    _require(isinstance(doc, dict) and set(doc) == {"schema_version", "cases"}
             and type(doc["schema_version"]) is int and doc["schema_version"] == 1, "invalid_case_registry")
    cases = doc["cases"]
    _require(isinstance(cases, list) and 2 <= len(cases) <= 8, "need_distinct_reference_projects")
    seen = set()
    for case in cases:
        _require(isinstance(case, dict) and set(case) == {"repository", "commit", "installed_version"},
                 "invalid_reference_project")
        repo = case["repository"]
        _require(isinstance(repo, str) and re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+", repo)
                 and repo.split("/")[-1] not in (".", "..") and repo.lower() not in seen, "invalid_reference_repository")
        _require(isinstance(case["commit"], str) and re.fullmatch(r"[a-f0-9]{40}", case["commit"]), "unpinned_reference")
        _require(isinstance(case["installed_version"], str) and re.fullmatch(r"\d+\.\d+\.\d+", case["installed_version"]),
                 "invalid_installed_version")
        seen.add(repo.lower())
    return cases


def _checkout(root, case, mirrors=None):
    root.mkdir()
    _git(root, "init", "-q")
    if mirrors is None:
        source, protocol = f"https://github.com/{case['repository']}.git", "https"
    else:
        mirror = mirrors / case["repository"].split("/")[-1]
        _require(mirror.is_dir(), "local_mirror_missing")
        source, protocol = str(mirror.resolve()), "file"
    fetch = ("fetch", "--no-tags", "--depth=1", "--update-shallow", source, case["commit"])
    try:
        _git(root, *fetch, protocol=protocol)
    except (RehearsalError, subprocess.TimeoutExpired):
        if protocol != "https":
            raise
        _git(root, *fetch, protocol=protocol)  # повторяем тот же публичный снимок при сбое сети
    _git(root, "checkout", "--detach", "FETCH_HEAD")
    _require(_git(root, "rev-parse", "HEAD").strip() == case["commit"], "reference_commit_mismatch")


def _snapshot(root, runtime_paths=()):
    """Checkout и runtime-пути из footprint, без рабочих отчётов самой репетиции."""
    result = {}
    for directory, dirs, files in os.walk(root, followlinks=False):
        base = Path(directory)
        for name in (*dirs, *files):
            path = base / name
            rel = path.relative_to(root).as_posix()
            in_runtime = rel == ".ai/runtime" or rel.startswith(".ai/runtime/")
            in_footprint = any(path == p or p in path.parents for p in runtime_paths)
            if in_runtime and not in_footprint and any(path in p.parents for p in runtime_paths):
                continue  # родитель только для обхода, его создание не часть отката
            if rel == ".git" or name == "__pycache__" or (in_runtime and not in_footprint):
                if name in dirs:
                    dirs.remove(name)
                continue
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                value = os.readlink(path)
            elif stat.S_ISREG(mode):
                with path.open("rb") as stream:
                    value = hashlib.file_digest(stream, "sha256").hexdigest()
            elif stat.S_ISDIR(mode):
                value = None
            else:
                raise RehearsalError("unsupported_checkout_entry")
            result[rel] = (mode, value)
    config = {}
    for entry in _git(root, "config", "--local", "--null", "--list").split("\0"):
        if entry:
            key, sep, value = entry.partition("\n")
            config.setdefault(key, []).append(value if sep else None)
    result["<git-config>"] = config
    result["<git-index>"] = _git(root, "ls-files", "--stage", "-z")
    result["<git-head>"] = _git(root, "rev-parse", "HEAD")
    return result


_WITNESS = """from pathlib import Path
import hashlib, json, sys
import yaml
expected = json.loads(Path(sys.argv[3]).read_text())
if Path('.ai/managed/VERSION').read_text().strip() != sys.argv[1]:
    raise SystemExit(7)
for path, digest in expected['files'].items():
    path = Path(path)
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise SystemExit(7)
if any(Path(path).exists() for path in expected['removed']):
    raise SystemExit(7)
config = Path('.ai-ops.yaml')
if not config.is_file() or yaml.safe_load(config.read_bytes())['parent']['installed_version'] != sys.argv[1]:
    raise SystemExit(7)
Path(sys.argv[2]).write_text(sys.argv[1])
raise SystemExit(9)
"""


def _installer(kit, root):
    os.chdir(root)  # только одноразовый worker; installer привязывает корень при импорте
    spec = importlib.util.spec_from_file_location("_fleet_installer", kit / "installer/ai_ops.py")
    _require(spec is not None and spec.loader is not None, "installer_not_loadable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _owner_settings(config):
    data = yaml.safe_load(config.read_bytes())
    parent = data.get("parent") if isinstance(data, dict) else None
    _require(isinstance(parent, dict) and "installed_version" in parent, "invalid_child_config")
    del parent["installed_version"]
    return data


def _check_preservation(before, after, owned, old_cfg, new_cfg, merge_driver):
    prefixes = (".ai/project", ".ai/custom")
    def owner_path(path):
        return any(path == prefix or path.startswith(prefix + "/") for prefix in prefixes)
    _require(old_cfg == new_cfg and all(after.get(path) == value for path, value in before.items()
                                       if owner_path(path)), "owner_content_changed")
    for path in after.keys() - before.keys():
        if owner_path(path):
            local = Path(path)
            _require(any(local == p or p in local.parents or local in p.parents for p in owned),
                     "unexpected_owner_content_added")
    _require(all(after.get(path) == entry for path, entry in before.items()
                 if path.startswith(".claude/skills/") and stat.S_ISLNK(entry[0])), "owner_skill_alias_changed")
    _require(all(after[key] == before[key] for key in ("<git-head>", "<git-index>")), "unexpected_git_mutation")
    allowed = {f"merge.{merge_driver}.name", f"merge.{merge_driver}.driver"}
    previous, current = ({k: v for k, v in state["<git-config>"].items() if k not in allowed}
                         for state in (before, after))
    _require(previous == current, "unrelated_git_config_changed")


def _trial(kit, root, old, mode, witness):
    installer = _installer(kit, root)
    core = installer._core()
    target = core.pkg_version()
    runtime = root / ".ai/runtime"
    managed_state = core._load("managed_state")
    footprint = managed_state._footprint_paths()
    runtime_paths = tuple(p for p in footprint if p.is_relative_to(runtime))
    report_path = runtime / "last-update-report.json"
    _require(managed_state._footprint_symlink([report_path]) is None, "unsafe_update_report_path")
    report_path.unlink(missing_ok=True)  # отчёт этого прогона не может оказаться старым
    before = _snapshot(root, runtime_paths)
    cfg = root / ".ai-ops.yaml"
    _require(cfg.is_file() and not cfg.is_symlink(), "invalid_child_config")
    owner_cfg = _owner_settings(cfg)
    _require(core.installed_version() == old and old != target, "unexpected_source_version_or_no_transition")
    observed = _installation_evidence(root)
    _require(observed.get("state") == "locally_consistent" and observed.get("version") == old,
             "source_inventory_unknown_or_drifted")
    diff = core.build_diff()
    _require(bool(diff) and _snapshot(root, runtime_paths) == before, "dry_run_empty_or_wrote_to_checkout")
    checks = None
    if mode == "rollback":
        probe = witness.with_name("witness-check.py")
        with probe.open("x", encoding="utf-8") as stream:
            stream.write(_WITNESS)
        payload = witness.with_name("expected-payload.json")
        expected = {"files": {f".ai/managed/{rel}": hashlib.sha256(core.managed_content(rel, source.read_bytes())).hexdigest()
                              for source, rel in core.managed_set()},
                    "removed": [c["path"] for c in diff if c["action"] == "remove"]}
        with payload.open("x", encoding="utf-8") as stream:
            json.dump(expected, stream)
        checks = [[str(probe), target, str(witness), str(payload)]]
    with redirect_stdout(io.StringIO()):
        rc = installer._update_ops().cmd_update(in_place=True, smoke_checks=checks)
    report = json.loads(report_path.read_bytes())
    _require((report.get("from_version"), report.get("to_version")) == (old, target), "update_report_version_mismatch")
    after = _snapshot(root, runtime_paths)
    if mode == "rollback":
        _require(rc == 1 and report.get("status") == "rolled_back" and witness.is_file()
                 and witness.read_text() == target and before == after, "rollback_not_proven")
        return {"status": "pass", "diff_entries": len(diff), "restored_entries": len(before),
                "witness_saw_target": True}
    smoke = report.get("smoke_tests") or []
    _require(rc == 0 and report.get("status") == "ok" and smoke and all(s.get("status") == "pass" for s in smoke)
             and core.installed_version() == target and (root / ".ai/managed/VERSION").read_text().strip() == target
             and core.detect_drift() == [] and core.build_diff() == [] and before != after, "applied_update_not_verified")
    owned = tuple(p.relative_to(root) for p in footprint if p.is_relative_to(root))
    _check_preservation(before, after, owned, owner_cfg, _owner_settings(cfg), installer._plan_merge_setup().DRIVER_NAME)
    return {"status": "pass", "diff_entries": len(diff), "smoke_checks": len(smoke), "from": old, "to": target}


def _worker(kit, root, case, mode, witness):
    cmd = [sys.executable, "-m", "ai_ops_kit.devtools.fleet_rehearsal", "--worker", str(root),
           case["installed_version"], mode, str(witness)]
    result = subprocess.run(cmd, cwd=kit, env=_env(), capture_output=True, text=True, timeout=240)
    try:
        data = json.loads((root.parent / f"result-{mode}.json").read_bytes())
    except (OSError, json.JSONDecodeError):
        raise RehearsalError(f"{mode}_worker_no_report") from None
    _require(result.returncode == 0 and data.get("status") == "pass", f"{mode}: {data.get('reason', 'failed')}")
    return data


def rehearse(kit, expected_sha, mirrors=None):
    _require(re.fullmatch(r"[a-f0-9]{40}", expected_sha) and _git(kit, "rev-parse", "HEAD").strip() == expected_sha,
             "kit_head_mismatch")
    _require(not _git(kit, "status", "--porcelain", "--untracked-files=normal").strip(), "kit_checkout_not_clean")
    cases = load_cases(kit / "qualification/fleet-rehearsal.yaml")
    with tempfile.TemporaryDirectory(prefix="kit-fleet-rehearsal-") as tmp, ThreadPoolExecutor(max_workers=2) as pool:
        def run_case(item):
            index, case = item
            case_dir = Path(tmp) / str(index)
            case_dir.mkdir()
            root = case_dir / "apply"
            row = dict(case)
            try:
                _checkout(root, case, mirrors)
                rollback = case_dir / "rollback"
                shutil.copytree(root, rollback, symlinks=True)
                row["apply"] = _worker(kit, root, case, "apply", case_dir / "unused")
                row["rollback"] = _worker(kit, rollback, case, "rollback", case_dir / "witness")
                row["status"] = "pass"
            except RehearsalError as exc:
                row.update(status="fail", reason=str(exc))
            except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError) as exc:
                row.update(status="fail", reason=type(exc).__name__)
            return row

        rows = list(pool.map(run_case, enumerate(cases)))
    _require(_git(kit, "rev-parse", "HEAD").strip() == expected_sha
             and not _git(kit, "status", "--porcelain", "--untracked-files=normal").strip(), "kit_changed_during_rehearsal")
    return {"schema_version": 1, "kind": "fleet-rehearsal", "kit_sha": expected_sha,
            "status": "pass" if all(r["status"] == "pass" for r in rows) else "fail", "projects": rows}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha")
    parser.add_argument("--mirrors", type=Path, help="папка с локальными Git-зеркалами по именам репозиториев")
    parser.add_argument("--worker", nargs=4, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    kit = Path.cwd()
    receipt = None
    try:
        if args.worker:
            root, old, mode, witness = args.worker
            root, witness = Path(root).resolve(), Path(witness).resolve()
            trial_dir = root.parent.parent
            _require(mode in ("apply", "rollback") and root.name == mode and root.parent.name.isdecimal()
                     and trial_dir.parent == Path(tempfile.gettempdir()).resolve()
                     and trial_dir.name.startswith("kit-fleet-rehearsal-")
                     and witness.parent == root.parent and witness.name in ("unused", "witness"),
                     "worker_requires_disposable_checkout")
            receipt = root.parent / f"result-{mode}.json"
            report = _trial(kit, root, old, mode, witness)
        else:
            _require(args.expected_sha, "expected_sha_required")
            report = rehearse(kit, args.expected_sha, args.mirrors)
    except RehearsalError as exc:
        report = {"status": "fail", "reason": str(exc)}
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        report = {"status": "fail", "reason": type(exc).__name__}
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if receipt is None:
        print(encoded)
    else:
        with receipt.open("x", encoding="utf-8") as stream:
            stream.write(encoded + "\n")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
