"""Risk floors, complete changed scope, precise commands and conservative graph failures."""
from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

import pytest

from ai_ops_kit.context import repo_graph
from ai_ops_kit.devtools.impact_check_cli import changed_paths
from ai_ops_kit.gates import verification_tiers as tiers

PROFILE = {"stacks": [{"language": "python", "commands": {"test": "python3 -m pytest tests/ -q -m 'not slow'"}}]}


def write(root, name, text=""):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.mark.parametrize("path", ["VERSION", "templates/prompt.md", "skills/run/SKILL.md", "tests/conftest.py", "pyproject.toml", ".github/workflows/ci.yml", "registry/gates.yaml"])
@pytest.mark.parametrize("intent", ["explore", "draft", "release_candidate"])
def test_risk_floor_cannot_be_weakened(path, intent):
    assert tiers.decide_tier([path], force_tier="skip", lifecycle_intent=intent) == "full"


def test_pytest_replaces_root_preserves_options_and_quotes_paths():
    paths = ["tests/test a.py"]
    command = tiers._get_test_commands_from_profile(PROFILE, paths)[0]
    tokens = shlex.split(command)
    assert "tests/" not in tokens
    assert tokens[-1] == paths[0]
    assert tokens[4:6] == ["-m", "not slow"]


@pytest.mark.parametrize("command", ["pytest --cov=src", "pytest tests && echo ok", "npm test", "make test", "jest", "pytest --unknown arg"])
def test_unsafe_or_unknown_runner_uses_full(command):
    profile = {"stacks": [{"language": "python", "commands": {"test": command}}]}
    assert tiers._get_test_commands_from_profile(profile, ["tests/test_a.py"]) == []


def test_vitest_positional_filter_not_jest_flag():
    profile = {"stacks": [{"language": "typescript", "commands": {"test": "vitest run"}}]}
    assert tiers._get_test_commands_from_profile(profile, ["src/a.test.ts"]) == ["vitest run src/a.test.ts"]


def test_mixed_change_unknown_asset_forces_full(tmp_path):
    write(tmp_path, "tests/test_a.py", "def test_a(): pass")
    write(tmp_path, "data.json", "{}")
    result = tiers.select_tests(["tests/test_a.py", "data.json"], tmp_path, profile=PROFILE)
    assert result["full_command"] and result["tier"] == "full"


def test_deleted_test_forces_full(tmp_path):
    assert tiers.select_tests(["tests/test_deleted.py"], tmp_path, profile=PROFILE)["full_command"]


def test_direct_test_edits_do_not_scan_dependencies(tmp_path, monkeypatch):
    write(tmp_path, "tests/test_a.py", "def test_a(): pass")
    monkeypatch.setattr(repo_graph, "build_graph", lambda *a, **kw: pytest.fail("unnecessary graph"))
    result = tiers.select_tests(["tests/test_a.py"], tmp_path, profile=PROFILE)
    assert not result["full_command"] and result["affected_tests"] == ["tests/test_a.py"]


def test_module_checkpoint_expands_neighbour_sources(tmp_path):
    write(tmp_path, "src/a.py", "def a(): return 1")
    write(tmp_path, "src/b.py", "def b(): return 2")
    write(tmp_path, "tests/test_a.py", "from src import a")
    write(tmp_path, "tests/test_b.py", "from src import b")
    result = tiers.select_tests(["src/a.py"], tmp_path, lifecycle_intent="ready_for_review", profile=PROFILE)
    assert result["affected_tests"] == ["tests/test_a.py", "tests/test_b.py"]


def test_dynamic_dependency_forces_full(tmp_path):
    write(tmp_path, "src/a.py", "def a(): return 1")
    write(tmp_path, "tests/test_a.py", "import a")
    write(tmp_path, "src/loader.py", "import importlib\nimportlib.import_module(name)")
    result = tiers.select_tests(["src/a.py"], tmp_path, profile=PROFILE)
    assert result["full_command"] and "incomplete" in result["note"]


def test_pruned_trees_are_never_traversed(tmp_path, monkeypatch):
    for directory in ("node_modules", ".ai", ".claude", "build", ".venv"):
        write(tmp_path, f"{directory}/nested/ghost.py", "import a")
    write(tmp_path, "src/a.py", "def a(): return 1")
    original = os.scandir
    def guarded(path):
        if Path(path).is_relative_to(tmp_path):
            assert not any(part in repo_graph.PY_SKIP_DIRS for part in Path(path).relative_to(tmp_path).parts)
        return original(path)
    monkeypatch.setattr(os, "scandir", guarded)
    graph = repo_graph.build_graph(tmp_path, subdirs=None)
    assert set(graph["files"]) == {"src/a.py"}


def test_same_stem_keeps_both_dependencies(tmp_path):
    write(tmp_path, "one/a.py", "def a(): pass")
    write(tmp_path, "two/a.py", "def a(): pass")
    write(tmp_path, "tests/test_a.py", "import a")
    graph = repo_graph.build_graph(tmp_path, subdirs=None)
    assert graph["import_edges"]["tests/test_a.py"] == ["one/a.py", "two/a.py"]


def test_scope_includes_staged_unstaged_untracked_and_deleted(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path)
    git("init", "-q")
    write(tmp_path, "removed.py")
    write(tmp_path, "edited.py")
    git("add", ".")
    git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "base")
    (tmp_path / "removed.py").unlink()
    write(tmp_path, "edited.py", "x=1")
    write(tmp_path, "staged.py")
    git("add", "staged.py")
    write(tmp_path, "untracked.py")
    assert changed_paths(tmp_path, "HEAD") == ["edited.py", "removed.py", "staged.py", "untracked.py"]


def test_declared_npm_vitest_script_is_narrowed(tmp_path):
    write(tmp_path, "package.json", '{"scripts":{"test":"vitest run"}}')
    profile = {"stacks": [{"language": "node", "commands": {"test": "npm run test"}}]}
    assert tiers._get_test_commands_from_profile(profile, ["src/a.test.ts"], tmp_path) == ["npm run test -- src/a.test.ts"]
    write(tmp_path, "package.json", '{"scripts":{"test":"vitest run --coverage"}}')
    assert tiers._get_test_commands_from_profile(profile, ["src/a.test.ts"], tmp_path) == []


def test_relative_package_import_is_included(tmp_path):
    write(tmp_path, "src/a.py", "def a(): pass")
    write(tmp_path, "src/test_a.py", "from . import a")
    graph = repo_graph.build_graph(tmp_path, subdirs=None)
    assert repo_graph.affected_tests(graph, ["src/a.py"]) == ["src/test_a.py"]


def test_release_runs_full_and_propagates_failure(tmp_path, monkeypatch):
    from ai_ops_kit.devtools import impact_check_cli as cli
    monkeypatch.setattr(cli, "changed_paths", lambda *a: ["README.md"])
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return 7
    monkeypatch.setattr(cli.subprocess, "call", run)
    assert cli.main(["--root", str(tmp_path), "--intent", "release_candidate"]) == 7
    assert calls[0][0] == ["bash", "scripts/check-full.sh"]
    assert calls[0][1]["env"]["PYTHON"] == cli.sys.executable


def test_unknown_git_base_refuses_execution(tmp_path, monkeypatch):
    from ai_ops_kit.devtools import impact_check_cli as cli
    monkeypatch.setattr(cli, "changed_paths", lambda *a: (_ for _ in ()).throw(subprocess.CalledProcessError(128, "git")))
    monkeypatch.setattr(cli.subprocess, "call", lambda *a, **kw: pytest.fail("executed on incomplete scope"))
    assert cli.main(["--root", str(tmp_path), "--base", "missing"]) == 2
