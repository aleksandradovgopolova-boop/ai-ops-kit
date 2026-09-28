"""Брокер исполняет команду без оболочки, когда оболочка ей не нужна (#1157).

Поведение сохраняется в обе стороны: простая команда даёт тот же код и тот же вывод, что и раньше,
а команда с синтаксисом оболочки (конвейер, `&&`, перенаправление) по-прежнему работает — это
объявленная возможность op `shell`, и на её последствиях стоит сторож путей.
"""
from __future__ import annotations

import shlex
import subprocess
import sys

import pytest

from ai_ops_kit.engine import tool_broker

pytestmark = pytest.mark.unit

PY = shlex.quote(sys.executable)


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], capture_output=True, check=True)
    return tmp_path


def _run(repo, command):
    return tool_broker.execute({"op": "shell", "command": command}, repo,
                               tool_broker.Policy(level="execution"))


def test_simple_command_runs_without_shell(repo):
    ev = _run(repo, f"{PY} -c 'print(42)'")
    assert ev["via_shell"] is False
    assert (ev["ok"], ev["exit_code"]) == (True, 0)
    assert ev["output_tail"].strip() == "42"


def test_quoted_arguments_reach_the_process_intact(repo):
    ev = _run(repo, f"{PY} -c 'import sys; print(sys.argv[1:])' 'a b' \"c; touch pwned\"")
    assert ev["via_shell"] is False
    assert ev["output_tail"].strip() == "['a b', 'c; touch pwned']"
    assert not (repo / "pwned").exists(), "кусок аргумента исполнился как команда"


def test_nonzero_exit_code_is_preserved(repo):
    ev = _run(repo, f"{PY} -c 'raise SystemExit(3)'")
    assert (ev["via_shell"], ev["ok"], ev["exit_code"]) == (False, False, 3)


def test_env_prefix_reaches_the_process(repo):
    ev = _run(repo, f"AI_OPS_PROBE=да {PY} -c 'import os; print(os.environ[\"AI_OPS_PROBE\"])'")
    assert ev["via_shell"] is False
    assert ev["output_tail"].strip() == "да"


def test_missing_binary_is_exit_127_as_before(repo):
    ev = _run(repo, "ai-ops-no-such-binary-1157 --version")
    assert ev["via_shell"] is False
    assert (ev["ok"], ev["exit_code"]) == (False, 127)


def test_secrets_stay_out_of_the_argv_path_env(repo, monkeypatch):
    """scrub_env действует и на путь без оболочки: секрет процессу не достаётся."""
    monkeypatch.setenv("AI_OPS_FAKE_TOKEN", "s3cr3t-value")
    ev = _run(repo, f"{PY} -c 'import os; print(os.environ.get(\"AI_OPS_FAKE_TOKEN\"))'")
    assert ev["via_shell"] is False
    assert ev["output_tail"].strip() == "None"


def test_pipeline_still_goes_through_the_shell(repo):
    ev = _run(repo, f"{PY} -c 'print(1); print(2)' | tail -n 1")
    assert ev["via_shell"] is True
    assert (ev["ok"], ev["output_tail"].strip()) == (True, "2")


def test_redirect_still_goes_through_the_shell(repo):
    ev = _run(repo, "echo записано > out.txt")
    assert ev["via_shell"] is True and ev["ok"] is True
    assert (repo / "out.txt").read_text(encoding="utf-8").strip() == "записано"


def test_git_op_runs_without_shell(repo):
    ev = tool_broker.execute({"op": "git", "command": "git status --porcelain"}, repo,
                             tool_broker.Policy(level="execution"))
    assert (ev["via_shell"], ev["exit_code"]) == (False, 0)
