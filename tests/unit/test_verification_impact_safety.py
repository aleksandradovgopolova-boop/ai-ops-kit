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


def _final_pipeline_repo(root, run_log, unrelated_passes, unrelated_reads_source=False):
    """Реальные unittest-классы, Git и явно объявленная команда — без fake exit codes."""
    import yaml
    from _pipeline_helpers import _init_python_repo
    _init_python_repo(root)
    write(root, ".ai-ops.yaml", yaml.safe_dump({"verification": {"commands": {
        "python": {"test": shlex.join([sys.executable, "-m", "pytest", "-q", "tests"])}}}}))
    write(root, ".gitignore", "__pycache__/\n.pytest_cache/\n")
    write(root, "src/a.py", "def value(): return 1\n")
    write(root, "tests/test_a.py", "import unittest\nfrom src.a import value\n"
          "class Direct(unittest.TestCase):\n def test_direct(self):\n"
          f"  with open({str(run_log)!r}, 'a') as log: log.write('direct\\n')\n"
          "  self.assertEqual(value(), 1)\n")
    condition = "'EXTRA' not in open('src/a.py').read()" if unrelated_reads_source else repr(unrelated_passes)
    write(root, "tests/test_unrelated.py", "import unittest\nclass Unrelated(unittest.TestCase):\n"
          " def test_unrelated(self):\n"
          f"  with open({str(run_log)!r}, 'a') as log: log.write('unrelated\\n')\n"
          f"  self.assertTrue({condition})\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "test baseline"], cwd=root, check=True, capture_output=True)


@pytest.mark.unit
@pytest.mark.parametrize("unrelated_passes", [False, True])
def test_final_pipeline_runs_full_suite_without_requiring_open_pr(tmp_path, unrelated_passes):
    from ai_ops_kit.engine import execution_pipeline
    from _pipeline_helpers import _QUICK_SIG
    root, log = tmp_path / "repo", tmp_path / "tests-ran.log"
    root.mkdir()
    _final_pipeline_repo(root, log, unrelated_passes)
    steps = iter([{"op": "write", "path": "src/a.py", "content": "def value(): return 1\nEXTRA = 2\n"},
                  {"done": True}])
    report = execution_pipeline.run_pipeline("добавить константу", _QUICK_SIG, root,
        lambda ctx: next(steps), feature="final-floor", commit=True, install_deps=False, open_pr=False)
    # Сначала сам факт: появился коммит, а вне-графовый тест ДЕЙСТВИТЕЛЬНО исполнился.
    assert report["commit"]["sha"]
    assert report["commit"]["changed_files"] == ["src/a.py"]
    assert report["commit"]["evidence_on_exact_sha"] is True
    assert log.read_text().splitlines() == ["direct", "unrelated"]
    assert report["checks"]["test"]["status"] == ("pass" if unrelated_passes else "fail")
    assert report["ready_for_pr"] is unrelated_passes
    if not unrelated_passes:
        assert "implementation_verification" in report["gates"]["unmet"]


@pytest.mark.unit
def test_draft_collector_keeps_targeted_execution_for_same_real_repo(tmp_path):
    from ai_ops_kit.engine import tool_broker
    from ai_ops_kit.gates import evidence_collector
    from ai_ops_kit.shared import project_detector
    root, log = tmp_path / "repo", tmp_path / "tests-ran.log"
    root.mkdir()
    _final_pipeline_repo(root, log, False)
    result = evidence_collector.collect(project_detector.detect(root), root,
        tool_broker.Policy(level="execution", child_root=str(root)), changed_files=["src/a.py"],
        broker=tool_broker, lifecycle_intent="draft")
    assert result["verification"]["tier"] == "affected"
    assert result["verification"]["affected_tests"] == ["tests/test_a.py"]
    assert result["checks"]["test"]["status"] == "pass"
    assert log.read_text().splitlines() == ["direct"]


@pytest.mark.unit
def test_immutable_package_draft_then_final_aggregate_runs_actual_full_suite(tmp_path):
    from ai_ops_kit.engine import execution_pipeline, sequence_aggregate, tool_broker
    from ai_ops_kit.gates import evidence_collector
    from ai_ops_kit.shared import project_detector
    from _pipeline_helpers import _QUICK_SIG
    root, log = tmp_path / "repo", tmp_path / "tests-ran.log"
    root.mkdir()
    _final_pipeline_repo(root, log, True, unrelated_reads_source=True)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    baseline = evidence_collector.collect(project_detector.detect(root), root,
        tool_broker.Policy(level="execution", child_root=str(root)), broker=tool_broker)
    assert baseline["revision"] == base and baseline["checks"]["test"]["status"] == "pass"
    assert log.read_text().splitlines() == ["direct", "unrelated"]
    log.write_text("")
    steps = iter([{"op": "write", "path": "src/a.py", "content": "def value(): return 1\nEXTRA = 2\n"},
                  {"done": True}])
    report = execution_pipeline.run_pipeline("пакет", _QUICK_SIG, root, lambda ctx: next(steps),
        feature="package-floor", commit=True, install_deps=False, verification_intent="draft")
    sha = report["commit"]["sha"]
    assert sha and sha != base and report["commit"]["evidence_on_exact_sha"] is True
    assert report["verification"]["tier"] == "affected"
    assert report["ready_for_pr"] is True  # готовность ПАКЕТА, не интеграции
    assert log.read_text().splitlines() == ["direct"]
    log.write_text("")
    aggregate = sequence_aggregate._aggregate_verify(root, "package-floor", False, sha,
        baseline["checks"], base, _QUICK_SIG, None, False, True)
    assert log.read_text().splitlines() == ["direct", "unrelated"]
    assert aggregate["evidence_revision"] == sha and aggregate["revision_ok"] is True
    assert aggregate["checks"]["test"] == "fail"
    assert aggregate["no_regressions"] is False


@pytest.mark.unit
@pytest.mark.parametrize("entry", ["pipeline", "controller", "collector"])
def test_unknown_verification_intent_refuses_before_execution(tmp_path, entry):
    from ai_ops_kit.engine import ai_ops_run, execution_pipeline
    from ai_ops_kit.gates import evidence_collector
    def forbidden(*args, **kwargs):
        pytest.fail("unknown intent executed a model or command")
    if entry == "collector":
        class Broker:
            execute = forbidden
        with pytest.raises(ValueError, match="unknown verification intent"):
            evidence_collector.collect({}, tmp_path, None, broker=Broker(), lifecycle_intent="drafft")
    else:
        fn = ai_ops_run.run if entry == "controller" else execution_pipeline.run_pipeline
        result = fn("task", {}, tmp_path, proposer=forbidden, verification_intent="drafft")
        assert result["status"] == "error" and result["ready_for_pr"] is False
        assert "unknown verification intent" in result["error"]
    assert not (tmp_path / "features").exists()


@pytest.mark.parametrize('binding,read', [
    ('load = __import__', "load('src.a', fromlist=['value']).value"),
    ('evaluate = eval', '''evaluate("__import__('src.a', fromlist=['value']).value")'''),
    ('execute = exec', "namespace['value']"),
])
def test_builtin_loader_alias_really_hides_changed_consumer_without_full_fallback(tmp_path, binding, read):
    write(tmp_path, 'src/a.py', 'value = 1')
    setup = 'namespace = {}\n    execute("from src.a import value", namespace)\n    ' if binding == 'execute = exec' else ''
    write(tmp_path, 'src/bridge.py', f'{binding}\ndef read():\n    {setup}return {read}\n')
    write(tmp_path, 'tests/test_direct.py', 'from src.a import value\ndef test_direct(): assert value > 0')
    write(tmp_path, 'tests/test_alias.py', 'from src.bridge import read\ndef test_alias(): assert read() == 1')
    # Actual interpreter executes the consumer: a cheap isolated process, no provider/nested pytest.
    command = [sys.executable, '-c', "import runpy; runpy.run_path('tests/test_alias.py')['test_alias']()"]
    def run():
        return subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=30,
                              env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
    assert run().returncode == 0
    write(tmp_path, 'src/a.py', 'value = 22')
    failed = run()
    assert failed.returncode == 1 and 'AssertionError' in failed.stderr
    graph = repo_graph.build_graph(tmp_path, subdirs=None)
    # Prove a nonempty static selection would omit the consumer that actually failed.
    static = repo_graph.affected_tests(graph, ['src/a.py'])
    assert 'tests/test_direct.py' in static and 'tests/test_alias.py' not in static
    result = tiers.select_tests(['src/a.py'], tmp_path, profile=PROFILE)
    assert result['full_command'] and result['targeted_command'] is None
    assert 'src/bridge.py' in graph['uncertainties'] and 'incomplete' in result['note']


@pytest.mark.parametrize('binding', [
    'consume(__import__)', 'consume(eval)', 'consume(exec)', 'loaders = [__import__]',
    'def load(name, loader=__import__): return loader(name)',
])
def test_builtin_loader_reference_cannot_be_certified_static(tmp_path, binding):
    path = write(tmp_path, 'loader.py', binding)
    assert repo_graph._uncertain_dependency(path)


def test_ordinary_static_import_and_unrelated_load_function_remain_targeted(tmp_path):
    write(tmp_path, 'src/a.py', 'value = 1')
    write(tmp_path, 'src/static.py', 'from src.a import value\ndef load(): return value')
    write(tmp_path, 'tests/test_static.py', 'from src.static import load\ndef test_value(): assert load() == 1')
    result = tiers.select_tests(['src/a.py'], tmp_path, profile=PROFILE)
    assert not result['full_command'] and result['affected_tests'] == ['tests/test_static.py']
