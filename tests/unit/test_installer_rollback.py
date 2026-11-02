"""R5/#1406: полный footprint реального update на synthetic Git children."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tests.unit._installer_helpers import INSTALLER, _git, _make_child_repo, _run_cli


def test_preflight_keeps_previous_backup_and_owner_target(tmp_path, monkeypatch):
    """Отказ ДО snapshot не должен уничтожить уже существующий страховочный backup."""
    root = _make_child_repo(tmp_path / "child")
    backup = root / ".ai/runtime/backups/previous"
    backup.mkdir(parents=True)
    (backup / "saved").write_bytes(b"previous backup\\r\\n")
    (backup / "saved").chmod(0o640)
    owner = tmp_path / "owner"
    owner.write_bytes(b"owner bytes\\r\\n")
    (root / ".gitignore").symlink_to(owner)
    spec = importlib.util.spec_from_file_location("r5_preflight_installer", INSTALLER)
    installer = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = installer
    spec.loader.exec_module(installer)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    for name, path in {"REPO_ROOT": root, "AI_DIR": root / ".ai",
                       "MANAGED": root / ".ai/managed", "CHILD_CONFIG": root / ".ai-ops.yaml"}.items():
        monkeypatch.setattr(installer, name, path)
    before, backup_before = _tree(root), _tree(backup)
    with pytest.raises(OSError, match="символическая ссылка"):
        installer._core().snapshot_footprint(backup)
    assert _tree(root) == before
    assert _tree(backup) == backup_before
    assert owner.read_bytes() == b"owner bytes\\r\\n"
    assert (root / ".gitignore").is_symlink()


@pytest.fixture(scope="module")
def seed(tmp_path_factory):
    root = _make_child_repo(tmp_path_factory.mktemp("rollback-seed") / "child")
    env = {k: v for k, v in os.environ.items() if k != "CODEX_HOME"}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = _run_cli(root, "init", ".", env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    return root


def _tree(root):
    """Независимая перепись ВСЕХ путей, а не чтение inventory реализации."""
    result = {}
    for p in root.rglob("*"):
        rel = p.relative_to(root).as_posix()
        if (rel == ".git" or rel.startswith(".git/") or rel == ".ai/runtime/backups"
                or (rel.startswith(".ai/runtime/backups/") and not rel.startswith(".ai/runtime/backups/skills"))
                or rel == ".ai/runtime/last-update-report.json"):
            continue
        mode = stat.S_IMODE(p.lstat().st_mode)
        if p.is_symlink():
            result[rel] = ("link", os.readlink(p), mode)
        elif p.is_file():
            result[rel] = ("file", hashlib.sha256(p.read_bytes()).hexdigest(), mode)
        else:
            result[rel] = ("dir", mode)
    return result


def _child(seed, tmp_path, existing, *, same_version=False):
    root = tmp_path / "child"
    shutil.copytree(seed, root)
    paths = ["ai-ops", ".gitignore", ".gitattributes", "CLAUDE.md", "AGENTS.md",
             ".claude/settings.json", ".codex/hooks.json", ".github/workflows/ai-ops-update.yml",
             ".github/dependabot.yml", ".ai/runtime/ci-templates.json", "ROADMAP.md", "ARCHITECTURE.md",
             "planning/plan.yaml", ".ai/project/context/now.md", ".ai/custom/README.md"]
    # Разрешённое явное обновление CI должно откатить и созданную им резервную копию.
    for rel in paths:
        p = root / rel
        if existing:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b'{"hooks": {}, "owner": true}\n' if rel.endswith(".json")
                          else b"template: true\n# owner bytes\r\n" if rel.endswith(".yaml")
                          else b"owner bytes\r\n")
            p.chmod(0o640)
        else:
            p.unlink(missing_ok=True)
    # Существующие документы/продуктовый код, не принадлежащие киту, тоже сравниваются побайтно.
    (root / ".ai/custom/owner.txt").write_bytes(b"owner overlay\r\n")
    config = root / ".ai-ops.yaml"
    cfg = yaml.safe_load(config.read_text())
    if not same_version:
        cfg["parent"]["installed_version"] = "4.11.1"
    cfg.setdefault("standard", {})["team_session"] = "required"
    cfg["runtimes"] = {"configured": ["claude-code", "codex", "qwen-code"]}
    config.write_text(yaml.safe_dump(cfg, allow_unicode=True))
    _git(root, "config", "--local", "owner.setting", "preserved")
    if existing:
        _git(root, "config", "--local", "--add", "merge.ai-ops-plan.driver", "owner driver")
        _git(root, "config", "--local", "--add", "merge.ai-ops-plan.driver", "")
        _git(root, "config", "--local", "merge.ai-ops-plan.name", "owner name")
    else:
        _git(root, "config", "--local", "--unset-all", "merge.ai-ops-plan.driver")
        _git(root, "config", "--local", "--unset-all", "merge.ai-ops-plan.name")
    return root


_RUN = r'''
import importlib.util
import json
import sys
from pathlib import Path
spec = importlib.util.spec_from_file_location('r5_installer', sys.argv[1])
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)
core = mod._core()
if sys.argv[3] == 'delivery':
    # Точка сбоя после реальных записей entry/CI/config, внутри общего цикла delivery.
    def fail(root):
        assert (root / 'ai-ops').stat().st_mode & 0o111
        assert 'AI Ops' in (root / '.gitignore').read_text() or 'AI-OPS' in (root / '.gitignore').read_text()
        Path(sys.argv[4]).write_text('partial delivery observed')
        raise OSError('synthetic delivery failure')
    core.ensure_team_session = fail
elif sys.argv[3] == 'restore':
    core.deliver_assets = lambda *a, **kw: (_ for _ in ()).throw(OSError('delivery'))
    core.restore_footprint = lambda *a: (_ for _ in ()).throw(OSError('restore'))
raise SystemExit(mod._update_ops().cmd_update(in_place=True, refresh_ci=True,
                                             smoke_checks=[[sys.argv[2]]]))
'''


def _execute(root, tmp_path, failure, *, clean_git, existing_prompts=False):
    observed = tmp_path / "observed.json"
    probe = tmp_path / "smoke.py"
    runtime_assert = "" if failure == "same-version" else "assert (root / '.qwen/commands').is_dir()\nassert list((Path(os.environ['CODEX_HOME']) / 'prompts').glob('*.md'))"
    probe.write_text(f'''
import json
import os
from pathlib import Path
root = Path.cwd()
assert (root / 'ai-ops').stat().st_mode & 0o111
assert (root / '.ai/runtime/ci-templates.json').is_file()
{runtime_assert}
assert 'team_hook.py' in (root / '.codex/hooks.json').read_text()
Path({str(observed)!r}).write_text(json.dumps({{'delivered': True}}))
raise SystemExit({0 if failure == 'success' else 1})
''')
    home = tmp_path / "codex"
    home.mkdir(exist_ok=True)
    (home / "settings.json").write_bytes(b'owner runtime settings\r\n')
    if existing_prompts:
        (home / "prompts").mkdir()
        (home / "prompts/owner.md").write_bytes(b"owner prompt\r\n")
        (home / "prompts/owner.md").chmod(0o640)
    env = {**os.environ, "CODEX_HOME": str(home), "PYTHONDONTWRITEBYTECODE": "1"}
    if clean_git:
        env["GIT_CONFIG_GLOBAL"] = "/dev/null"
    proc = subprocess.run([sys.executable, "-c", _RUN, str(INSTALLER), str(probe), failure, str(observed)],
                          cwd=root, env=env, capture_output=True, text=True, timeout=180)
    report = json.loads((root / ".ai/runtime/last-update-report.json").read_text())
    return proc, report, observed, home


def _local_config(root):
    data = {}
    for row in _git(root, "config", "--local", "--null", "--list").stdout.split("\0"):
        if row:
            key, _, value = row.partition("\n")
            data.setdefault(key, []).append(value)
    return data


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("clean_git", [False, True])
@pytest.mark.parametrize("failure", ["smoke", "delivery"])
def test_failed_update_restores_entire_tree_and_local_driver(seed, tmp_path, existing, clean_git, failure):
    root = _child(seed, tmp_path, existing)
    before, config_before = _tree(root), _local_config(root)
    proc, report, observed, home = _execute(root, tmp_path, failure, clean_git=clean_git, existing_prompts=existing)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert observed.is_file(), proc.stdout + proc.stderr  # действие произошло ДО ошибки
    assert report["status"] == "rolled_back", report
    after = _tree(root)
    assert after == before, {p: (before.get(p), after.get(p)) for p in before.keys() | after.keys()
                             if before.get(p) != after.get(p)}
    assert _local_config(root) == config_before
    if existing:
        assert _tree(home / "prompts") == {"owner.md": ("file", hashlib.sha256(b"owner prompt\r\n").hexdigest(), 0o640)}
    else:
        assert not (home / "prompts").exists()
    assert (home / "settings.json").read_bytes() == b'owner runtime settings\r\n'


def test_same_version_asset_delivery_still_checks_smoke_and_rolls_back(seed, tmp_path):
    root = _child(seed, tmp_path, existing=False, same_version=True)
    before = _tree(root)
    proc, report, observed, _ = _execute(root, tmp_path, "same-version", clean_git=True)
    assert observed.is_file(), proc.stdout + proc.stderr
    assert proc.returncode == 1 and report["status"] == "rolled_back", report
    assert _tree(root) == before


def test_positive_update_applies_inventory_before_smoke(seed, tmp_path):
    root = _child(seed, tmp_path, existing=False)
    before = _tree(root)
    proc, report, observed, home = _execute(root, tmp_path, "success", clean_git=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert report["status"] == "ok" and observed.is_file()
    assert _tree(root) != before
    assert list((home / "prompts").glob("*.md"))
    assert (root / ".ai/custom/owner.txt").read_bytes() == b"owner overlay\r\n"
    assert _git(root, "config", "--local", "owner.setting").stdout.strip() == "preserved"


def test_restore_error_does_not_claim_complete_rollback(seed, tmp_path):
    root = _child(seed, tmp_path, existing=False)
    proc, report, _, _ = _execute(root, tmp_path, "restore", clean_git=True)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert report["status"] == "rollback_failed"
    assert report["rollback_error_type"] == "OSError"


@pytest.mark.parametrize("existing_history", [False, True])
def test_failed_update_restores_plan_history_written_by_migration(seed, tmp_path, existing_history):
    root = _child(seed, tmp_path, existing=False)
    plan = root / "planning/plan.yaml"
    plan.parent.mkdir(exist_ok=True)
    plan.write_text("work:\n  - {id: closed-work, status: done, result: completed}\n")
    if existing_history:
        history = root / "history/plan-history.yaml"
        history.parent.mkdir(exist_ok=True)
        history.write_text("schema_version: 1\nwork: []\n# owner history\n")
    before = _tree(root)
    proc, report, observed, _ = _execute(root, tmp_path, "smoke", clean_git=True)
    assert observed.is_file(), proc.stdout + proc.stderr
    assert proc.returncode == 1 and report["status"] == "rolled_back", report
    assert _tree(root) == before


@pytest.mark.parametrize("linked", ["gitignore", "prompts", "nested-command", "ancestor"])
def test_symlink_footprint_is_blocked_before_delivery(seed, tmp_path, linked):
    root = _child(seed, tmp_path, existing=False)
    home, owner = tmp_path / "codex", tmp_path / "owner"
    home.mkdir()
    owner.mkdir()
    (owner / "data").write_bytes(b"owner data\r\n")
    if linked == "gitignore":
        (root / ".gitignore").symlink_to(owner / "data")
    elif linked == "prompts":
        (home / "prompts").symlink_to(owner, target_is_directory=True)
    elif linked == "nested-command":
        (root / ".claude/commands/owner.md").symlink_to(owner / "data")
    else:
        # Даже отсутствовавший inventory-файл может иметь ссылку среди родительских каталогов.
        shutil.rmtree(root / ".github")
        (root / ".github").symlink_to(owner, target_is_directory=True)
    before, owner_before, home_before = _tree(root), _tree(owner), _tree(home)
    config_before = _local_config(root)
    env = {**os.environ, "CODEX_HOME": str(home), "GIT_CONFIG_GLOBAL": "/dev/null",
           "PYTHONDONTWRITEBYTECODE": "1"}
    proc = _run_cli(root, "update", "--in-place", env=env)
    report = json.loads((root / ".ai/runtime/last-update-report.json").read_text())
    assert proc.returncode == 2 and report["status"] == "blocked", proc.stdout + proc.stderr
    assert "символическая ссылка" in report["report"]
    assert _tree(root) == before
    assert _tree(owner) == owner_before
    assert _tree(home) == home_before
    assert _local_config(root) == config_before
    assert not (root / ".ai/runtime/backups").exists()


@pytest.mark.parametrize("linked", ["ai", "runtime", "report"])
def test_blocked_snapshot_does_not_write_report_through_symlink(seed, tmp_path, linked):
    root = _child(seed, tmp_path, existing=False)
    owner = tmp_path / "owner"
    owner.mkdir()
    if linked == "report":
        target = owner / "data"
        target.write_bytes(b"owner report target\r\n")
        link = root / ".ai/runtime/last-update-report.json"
    else:
        link = root / (".ai" if linked == "ai" else ".ai/runtime")
        target = owner / linked
        shutil.move(link, target)
    link.symlink_to(target, target_is_directory=linked != "report")
    before, owner_before, config_before = _tree(root), _tree(owner), _local_config(root)
    env = {k: v for k, v in os.environ.items() if k != "CODEX_HOME"}
    env.update(GIT_CONFIG_GLOBAL="/dev/null", PYTHONDONTWRITEBYTECODE="1")
    proc = _run_cli(root, "update", "--in-place", env=env)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "Отчёт не записан" in proc.stdout and "символическая ссылка" in proc.stdout
    assert link.is_symlink() and link.readlink() == target
    assert _tree(root) == before
    assert _tree(owner) == owner_before
    assert _local_config(root) == config_before
