"""Реальные Git/CLI-процессы: inventory, отказ и отсутствие исполнения shell."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts/check-shell-quality.sh"
pytestmark = pytest.mark.unit


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def project(tmp_path):
    repo = tmp_path / "repo with spaces"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "core.autocrlf", "false")
    (repo / "old.sh").write_text("#!/bin/sh\nprintf '%s\\n' old\n")
    git(repo, "add", "old.sh")
    git(repo, "commit", "-qm", "test: fixture")
    return repo


@pytest.fixture
def cli(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "calls.jsonl"
    # Отдельные процессы с argv/rc, а не mock subprocess в памяти проверяющего.
    program = f'''#!{shutil.which("python3")}
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
if sys.argv[1:] == ["--version"]:
    print(os.environ.get("VERSION_" + name, "version: 0.11.0" if name == "shellcheck" else "v3.14.1"))
    raise SystemExit(int(os.environ.get("VERSION_RC", "0")))
with open(os.environ["CALL_LOG"], "a") as output:
    output.write(json.dumps([name, sys.argv[1:]]) + "\\n")
source = pathlib.Path(sys.argv[-1]).read_text()
if "BAD_" + name.upper() in source:
    print(name + ": fixture violation", file=sys.stderr)
    raise SystemExit(1)
raise SystemExit(int(os.environ.get("RC_" + name, "0")))
'''
    for name in ("shellcheck", "shfmt"):
        path = bindir / name
        path.write_text(program)
        path.chmod(0o755)
    for name in ("git", "mktemp", "rm", "grep"):
        (bindir / name).symlink_to(shutil.which(name))
    env = {**os.environ, "PATH": str(bindir),
           "CALL_LOG": str(log), "GIT_CONFIG_GLOBAL": os.devnull}
    return bindir, log, env


def run(repo, cli, *args):
    return subprocess.run(["/bin/bash", str(RUNNER), *args], cwd=repo, env=cli[2],
                          text=True, capture_output=True, timeout=20)


def calls(cli):
    return [json.loads(line) for line in cli[1].read_text().splitlines()] if cli[1].exists() else []


def tracked(repo, name, content):
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    git(repo, "add", "--", name)
    return path


def test_all_tracked_scripts_including_hidden_and_spaces_are_checked(project, cli):
    tracked(project, ".hidden/a script.sh", "#!/usr/bin/env bash\nprintf ok\n")
    (project / "untracked.sh").write_text("#!/bin/sh\nexit 99\n")
    result = run(project, cli)
    assert result.returncode == 0, result.stderr
    invoked = calls(cli)
    assert len(invoked) == 4
    assert {args[-1] for _, args in invoked} == {"./old.sh", "./.hidden/a script.sh"}
    assert all("--norc" in args for name, args in invoked if name == "shellcheck")
    assert all("-d" in args and "-w" not in args for name, args in invoked if name == "shfmt")
    assert "checked=2" in result.stdout


def test_inventory_needs_no_tools_and_declares_dialects(project, cli):
    tracked(project, "bash.sh", "#!/bin/bash\ntrue\n")
    cli[2]["VERSION_RC"] = "9"
    result = run(project, cli, "--inventory")
    assert result.returncode == 0
    assert "posix\told.sh" in result.stdout
    assert "bash\tbash.sh" in result.stdout
    assert not calls(cli)


@pytest.mark.parametrize("tool", ["shellcheck", "shfmt"])
def test_actual_violation_is_nonzero_and_both_tools_still_run(project, cli, tool):
    path = tracked(project, "broken.sh", f"#!/bin/sh\n# BAD_{tool.upper()}\ntrue\n")
    assert f"BAD_{tool.upper()}" in path.read_text()  # side-effect перед реакцией
    before = path.read_bytes()
    result = run(project, cli)
    assert result.returncode == 1
    assert len(calls(cli)) == 4
    assert "fixture violation" in result.stderr
    assert path.read_bytes() == before


def test_sources_are_neither_executed_nor_rewritten(project, cli):
    marker = project / "executed"
    path = tracked(project, "danger.sh", f"#!/bin/sh\ntouch '{marker}'\n")
    assert path.exists() and "touch" in path.read_text()
    before = {p: p.read_bytes() for p in project.glob("*.sh")}
    result = run(project, cli)
    assert result.returncode == 0
    assert any(args[-1] == "./danger.sh" for _, args in calls(cli))
    assert not marker.exists()
    assert all(p.read_bytes() == content for p, content in before.items())


def test_changed_view_does_not_hide_new_violation_behind_legacy(project, cli):
    (project / "old.sh").write_text("#!/bin/sh\n# BAD_SHELLCHECK\ntrue\n")
    git(project, "add", "old.sh")
    git(project, "commit", "-qm", "test: legacy debt")
    base = git(project, "rev-parse", "HEAD")
    tracked(project, "new.sh", "#!/bin/sh\n# BAD_SHFMT\ntrue\n")
    result = run(project, cli, "--changed", base)
    assert result.returncode == 1
    assert {args[-1] for _, args in calls(cli)} == {"./new.sh"}
    assert "checked=1" in result.stdout


def test_changed_view_includes_unstaged_changes_and_renames(project, cli):
    base = git(project, "rev-parse", "HEAD")
    git(project, "mv", "old.sh", "renamed.sh")
    (project / "renamed.sh").write_text("#!/bin/sh\n# BAD_SHELLCHECK\ntrue\n")
    result = run(project, cli, "--changed", base)
    assert result.returncode == 1
    assert {args[-1] for _, args in calls(cli)} == {"./renamed.sh"}


def test_deleted_scripts_do_not_break_changed_view(project, cli):
    git(project, "rm", "old.sh")
    result = run(project, cli, "--changed", "HEAD")
    assert result.returncode == 0
    assert "checked=0" in result.stdout and not calls(cli)


@pytest.mark.parametrize("args", [("--changed", "missing"), ("--changed",), ("--wat",)])
def test_bad_base_or_arguments_cannot_pass(project, cli, args):
    result = run(project, cli, *args)
    assert result.returncode == 2
    assert not calls(cli)


@pytest.mark.parametrize("tool", ["shellcheck", "shfmt"])
def test_missing_tool_cannot_pass(project, cli, tool):
    (cli[0] / tool).unlink()
    result = run(project, cli)
    assert result.returncode == 2 and not calls(cli)


@pytest.mark.parametrize("tool", ["shellcheck", "shfmt"])
def test_different_tool_version_cannot_pass(project, cli, tool):
    cli[2]["VERSION_" + tool] = "wrong-version"
    result = run(project, cli)
    assert result.returncode == 2 and not calls(cli)


def test_failed_version_probe_cannot_pass(project, cli):
    cli[2]["VERSION_RC"] = "7"
    result = run(project, cli)
    assert result.returncode == 2 and not calls(cli)


def test_tool_failure_is_incomplete_even_when_other_tool_reports_debt(project, cli):
    tracked(project, "debt.sh", "#!/bin/sh\n# BAD_SHFMT\ntrue\n")
    cli[2]["RC_shellcheck"] = "3"
    result = run(project, cli)
    assert result.returncode == 2
    assert len(calls(cli)) == 4


def test_git_inventory_failure_is_not_empty_success(project, cli):
    git_stub = cli[0] / "git"
    git_stub.unlink()
    git_stub.write_text("#!/bin/sh\nexit 9\n")
    git_stub.chmod(0o755)
    result = run(project, cli)
    assert result.returncode == 2 and not calls(cli)


@pytest.mark.parametrize("source", ["echo no-shebang\n", "#!/bin/zsh\necho unsupported\n"])
def test_unknown_dialect_cannot_pass(project, cli, source):
    tracked(project, "unknown.sh", source)
    result = run(project, cli)
    assert result.returncode == 2
    assert all(args[-1] != "./unknown.sh" for _, args in calls(cli))


def test_posix_uses_posix_parser_and_bash_uses_bash_parser(project, cli):
    tracked(project, "bash.sh", "#!/usr/bin/env bash\ntrue\n")
    assert run(project, cli).returncode == 0
    for name, args in calls(cli):
        dialect = "posix" if args[-1] == "./old.sh" else "bash"
        if name == "shellcheck":
            assert "--shell=" + ("sh" if dialect == "posix" else "bash") in args
        else:
            assert args[args.index("-ln") + 1] == dialect


def test_workflow_keeps_full_debt_separate_and_advisory():
    workflow = yaml.safe_load((ROOT / ".github/workflows/shell-quality.yml").read_text())
    job = workflow["jobs"]["shell-quality"]
    assert job["continue-on-error"] is True
    steps = job["steps"]
    full = next(step for step in steps if step.get("id") == "all")
    changed = next(step for step in steps if step.get("id") == "changed")
    assert full["continue-on-error"] is True
    assert changed["if"] == "always()"
    assert "--changed" in changed["run"]
    assert any(step.get("if") == "always()" and "GITHUB_STEP_SUMMARY" in step.get("run", "") for step in steps)
    assert {row["os"] for row in job["strategy"]["matrix"]["include"]} == {"ubuntu-24.04", "macos-15-intel"}


def test_extensionless_root_entrypoint_is_in_all_and_changed_inventory(project, cli):
    path = tracked(project, "ai-ops", "#!/bin/sh\n# BAD_SHELLCHECK\ntrue\n")
    assert path.is_file()
    for args in ((), ("--changed", "HEAD")):
        cli[1].unlink(missing_ok=True)
        result = run(project, cli, *args)
        assert result.returncode == 1
        assert any(argv[-1] == "./ai-ops" for _, argv in calls(cli))


def test_shell_workflow_also_triggers_for_extensionless_entrypoint():
    workflow = yaml.load((ROOT / ".github/workflows/shell-quality.yml").read_text(), Loader=yaml.BaseLoader)
    for event in ("pull_request", "push"):
        assert "ai-ops" in workflow["on"][event]["paths"]
