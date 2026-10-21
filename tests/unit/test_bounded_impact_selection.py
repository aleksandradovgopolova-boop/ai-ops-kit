"""Консервативный подбор сохраняет динамических потребителей без полного набора."""
import os
import shlex
import subprocess
import sys

import pytest

from ai_ops_kit.gates import evidence_collector, verification_tiers as tiers

PROFILE = {"stacks": [{"language": "python", "commands": {
    "test": shlex.join([sys.executable, "-m", "pytest", "tests/", "-q"]),
    "lint": "ruff check ."}}]}


def write(root, path, content):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)


@pytest.fixture
def project(tmp_path):
    write(tmp_path, "src/value.py", "value = 22\n")
    write(tmp_path, "tests/test_direct.py", "from src.value import value\n"
          "def test_direct(): assert value > 0\n")
    write(tmp_path, "tests/test_unrelated.py", "def test_unrelated(): assert True\n")
    write(tmp_path, "src/loader.py", "from importlib import import_module as load\n"
          "def read(): return load('src.value').value\n")
    write(tmp_path, "tests/test_dynamic.py", "from pathlib import Path\nfrom src.loader import read\n"
          "def test_dynamic():\n    Path('dynamic-ran').write_text('executed')\n"
          "    assert read() == 1\n")
    return tmp_path


def test_child_selection_executes_dynamic_regression_and_omits_unrelated(project):
    info, commands = evidence_collector._verification_commands(
        PROFILE, project, ["src/value.py"], "draft")
    assert not info["full_command"]
    assert info["affected_tests"] == ["tests/test_direct.py", "tests/test_dynamic.py"]
    assert "src/loader.py" in info["dependency_paths"]
    assert commands["lint"] == [("python", "ruff check .")]
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    for key in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTHONPATH"):
        env.pop(key, None)
    result = subprocess.run(shlex.split(commands["test"][0][1]), cwd=project,
                            env=env, capture_output=True, text=True, timeout=20)
    assert (project / "dynamic-ran").read_text() == "executed"
    assert result.returncode == 1 and "22 == 1" in result.stdout
    assert "1 failed, 1 passed" in result.stdout


@pytest.mark.parametrize("bad_path,content", [
    ("src/broken.py", "def broken(:"),
    ("src/orphan.py", "from importlib import import_module as load\n"),
])
def test_unbounded_dependency_retains_full_fallback(project, bad_path, content):
    write(project, bad_path, content)
    info = tiers.select_tests(["src/value.py"], project, profile=PROFILE)
    assert info["full_command"] and "incomplete" in info["note"]


@pytest.mark.parametrize("intent", ["merge_candidate", "release_candidate"])
def test_final_child_verification_retains_original_suite(project, intent):
    info, commands = evidence_collector._verification_commands(
        PROFILE, project, ["src/value.py"], intent)
    assert info["full_command"]
    assert commands["test"] == [("python", PROFILE["stacks"][0]["commands"]["test"])]


def test_js_alias_retains_full_without_setup_hook_model(tmp_path):
    write(tmp_path, "src/value.ts", "export const value = 1;")
    write(tmp_path, "tests/direct.test.ts", "import {value} from '../src/value';")
    write(tmp_path, "tests/alias.test.ts", "const value = require('@src/value');")
    write(tmp_path, "tests/unrelated.test.ts", "const unrelated = 1;")
    profile = {"stacks": [{"language": "typescript", "commands": {"test": "vitest run"}}]}
    info = tiers.select_tests(["src/value.ts"], tmp_path, profile=profile)
    assert info["full_command"]


def test_dynamic_fixture_keeps_implicit_test_consumers(project):
    write(project, "tests/conftest.py", "import pytest\nfrom src.loader import read\n"
          "@pytest.fixture\ndef client(): return read()\n")
    write(project, "tests/test_client.py", "def test_client(client): assert client == 1\n")
    info = tiers.select_tests(["src/value.py"], project, profile=PROFILE)
    assert info["full_command"] and "implicit consumers" in info["note"]


def test_pytest_plugins_declaration_keeps_implicit_consumers(project):
    write(project, "tests/conftest.py", "pytest_plugins = ['src.loader']\n")
    info = tiers.select_tests(["src/value.py"], project, profile=PROFILE)
    assert info["full_command"] and "incomplete" in info["note"]


@pytest.mark.parametrize("source", ["command", "config", "environment"])
def test_explicit_plugin_keeps_implicit_consumers(project, monkeypatch, source):
    command = PROFILE["stacks"][0]["commands"]["test"]
    if source == "command":
        command += " -p=src.loader"
    elif source == "config":
        write(project, "pytest.ini", "[pytest]\naddopts = -p src.loader\n")
    else:
        monkeypatch.setenv("PYTEST_PLUGINS", "src.loader")
    profile = {"stacks": [{"language": "python", "commands": {"test": command}}]}
    info = tiers.select_tests(["src/value.py"], project, profile=profile)
    assert info["full_command"] and "implicit consumers" in info["note"]
