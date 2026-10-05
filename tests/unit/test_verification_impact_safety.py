"""Risk floors, complete changed scope, precise commands and conservative graph failures."""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
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


def test_test_helper_edit_includes_consumers(tmp_path):
    write(tmp_path, "tests/test_helpers.py", "def helper(): return 1\ndef test_helper(): pass")
    write(tmp_path, "tests/test_consumer.py", "from tests.test_helpers import helper\ndef test_consumer(): assert helper() == 1")
    result = tiers.select_tests(["tests/test_helpers.py"], tmp_path, profile=PROFILE)
    assert not result["full_command"]
    assert result["affected_tests"] == ["tests/test_consumer.py", "tests/test_helpers.py"]


def test_js_directory_import_includes_both_consumers(tmp_path):
    write(tmp_path, "src/util/index.ts", "export const value = 1;")
    write(tmp_path, "tests/direct.test.ts", "import { value } from '../src/util/index';")
    write(tmp_path, "tests/directory.test.ts", "import { value } from '../src/util';")
    profile = {"stacks": [{"language": "typescript", "commands": {"test": "vitest run"}}]}
    result = tiers.select_tests(["src/util/index.ts"], tmp_path, profile=profile)
    assert not result["full_command"]
    assert result["affected_tests"] == ["tests/direct.test.ts", "tests/directory.test.ts"]


def test_commonjs_alias_forces_full(tmp_path):
    write(tmp_path, "src/value.ts", "export const value = 1;")
    write(tmp_path, "tests/direct.test.ts", "import { value } from '../src/value';")
    write(tmp_path, "tests/alias.test.ts", "const value = require('@src/value');")
    profile = {"stacks": [{"language": "typescript", "commands": {"test": "vitest run"}}]}
    result = tiers.select_tests(["src/value.ts"], tmp_path, profile=profile)
    assert result["full_command"] and "incomplete" in result["note"]


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


def test_multiline_js_import_keeps_its_consumer(tmp_path):
    write(tmp_path, "src/a.ts", "export const a = 1;")
    write(tmp_path, "tests/direct.test.ts", "import { a } from '../src/a';")
    write(tmp_path, "tests/multiline.test.ts", "import {\n a\n} from '../src/a';")
    profile = {"stacks": [{"language": "typescript", "commands": {"test": "vitest run"}}]}
    result = tiers.select_tests(["src/a.ts"], tmp_path, profile=profile)
    assert not result["full_command"]
    assert result["affected_tests"] == ["tests/direct.test.ts", "tests/multiline.test.ts"]


def test_side_effect_before_multiline_import_keeps_both_dependencies(tmp_path):
    write(tmp_path, "src/a.ts", "export const a = 1;")
    write(tmp_path, "src/b.ts", "export const b = 2;")
    write(tmp_path, "tests/direct.test.ts", "import { a } from '../src/a';")
    write(tmp_path, "tests/mixed.test.ts", "import '../src/a';\nimport {\n b\n} from '../src/b';")
    graph = repo_graph.build_graph(tmp_path, subdirs=None)
    assert graph["import_edges"]["tests/mixed.test.ts"] == ["src/a.ts", "src/b.ts"]
    profile = {"stacks": [{"language": "typescript", "commands": {"test": "vitest run"}}]}
    result = tiers.select_tests(["src/a.ts"], tmp_path, profile=profile)
    assert result["affected_tests"] == ["tests/direct.test.ts", "tests/mixed.test.ts"]


@pytest.mark.parametrize("binding", ["from importlib import import_module",
                                      "from importlib import import_module as load",
                                      "from runpy import run_module as load",
                                      "import importlib\nload = importlib.import_module"])
def test_imported_dynamic_loader_forces_full(tmp_path, binding):
    write(tmp_path, "src/a.py", "value = 1")
    write(tmp_path, "tests/test_direct.py", "from src.a import value\ndef test_value(): assert value == 1")
    write(tmp_path, "src/loader.py", binding)
    result = tiers.select_tests(["src/a.py"], tmp_path, profile=PROFILE)
    assert result["full_command"] and "incomplete" in result["note"]


def test_dynamic_alias_really_loads_changed_source(tmp_path):
    write(tmp_path, "src/a.py", "value = 1")
    write(tmp_path, "tests/test_direct.py", "from src.a import value\ndef test_direct(): assert value == 1")
    write(tmp_path, "tests/test_alias.py", "from importlib import import_module as load\n"
          "def test_alias(): assert load('src.a').value == 1")
    def run():
        return subprocess.run([sys.executable, "-m", "pytest", "tests/test_alias.py", "-q"],
                              cwd=tmp_path, capture_output=True, text=True,
                              env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert run().returncode == 0
    write(tmp_path, "src/a.py", "value = 22")
    failed = run()
    assert failed.returncode == 1 and "22 == 1" in failed.stdout
    assert tiers.select_tests(["src/a.py"], tmp_path, profile=PROFILE)["full_command"]


def test_nested_initializer_effect_reaches_descendant_consumer(tmp_path):
    write(tmp_path, "pkg/__init__.py")
    write(tmp_path, "pkg/sub/__init__.py", "import builtins\nbuiltins.package_value = 1")
    write(tmp_path, "pkg/sub/worker.py", "import builtins\nvalue = builtins.package_value")
    write(tmp_path, "tests/test_direct.py", "import pkg.sub\ndef test_direct(): pass")
    write(tmp_path, "tests/test_worker.py", "from pkg.sub.worker import value\ndef test_value(): assert value == 1")
    def run():
        return subprocess.run([sys.executable, "-m", "pytest", "tests/test_worker.py", "-q"],
                              cwd=tmp_path, capture_output=True, text=True,
                              env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert run().returncode == 0
    write(tmp_path, "pkg/sub/__init__.py", "import builtins\nbuiltins.package_value = 22")
    failed = run()
    assert failed.returncode == 1 and "22 == 1" in failed.stdout
    result = tiers.select_tests(["pkg/sub/__init__.py"], tmp_path, profile=PROFILE)
    assert not result["full_command"]
    assert result["affected_tests"] == ["tests/test_direct.py", "tests/test_worker.py"]
