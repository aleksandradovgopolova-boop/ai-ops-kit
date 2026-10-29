"""Реальные Git/FS границы перенесённого commit-msg hook."""
from pathlib import Path
import subprocess

import pytest

from ai_ops_kit.devtools import commit_hook

pytestmark = pytest.mark.unit


@pytest.fixture
def index(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("COMMIT_CONTRACT_FILES", raising=False)
    monkeypatch.setenv("COMMIT_CONTRACT_SKIP_CLAIMS", "1")
    subprocess.run(["git", "init", "-q"], check=True)
    return tmp_path


def stage(root, name):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("fixture\n")
    subprocess.run(["git", "add", "--", name], check=True)
    return path


def test_real_index_preserves_spaces_newlines_and_option_names(index, capsys):
    names = ["a space.py", "a\nnewline.py", "--message"]
    for name in names:
        assert stage(index, name).read_text() == "fixture\n"
    assert set(commit_hook.staged_files(index)) == set(names)
    message = index / "COMMIT_EDITMSG"
    message.write_text("# ignored\ntest: staged paths CI #1410\n\n")
    assert commit_hook.main([str(message)]) == 0
    assert "3 файлов" in capsys.readouterr().out


def test_git_failure_is_not_an_empty_success(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("COMMIT_CONTRACT_FILES", raising=False)
    message = tmp_path / "message"
    message.write_text("test: not a repo CI #1410\n")
    assert commit_hook.main([str(message)]) == 1
    output = capsys.readouterr()
    assert "НЕ ВЫПОЛНЕН" in output.err
    assert "commit:" not in output.out


def test_forbidden_real_staged_file_reaches_unchanged_contract(index, capsys):
    assert stage(index, ".env").exists()
    message = index / "message"
    message.write_text("test: existing policy CI #1410\n")
    assert commit_hook.main([str(message)]) == 1
    assert "ЗАБЛОКИРОВАН" in capsys.readouterr().out


def test_comment_only_message_does_not_disable_contract(index, capsys):
    stage(index, "code.py")
    (index / ".ai-ops.yaml").write_text(
        "engineering_operating_model:\n  commit:\n    enforce: block\n")
    message = index / "message"
    message.write_text("# only a Git comment\n\n")
    assert commit_hook.main([str(message)]) == 1
    assert "short_message" in capsys.readouterr().out


def test_missing_message_has_original_usage_status(index, capsys):
    assert commit_hook.main([]) == 2
    assert "не передан файл" in capsys.readouterr().err
