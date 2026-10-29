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


def test_git_timeout_is_a_named_failure(index, monkeypatch, capsys):
    message = index / "message"
    message.write_text("test: Git timeout CI #1410\n")

    def timeout(argv, **kwargs):
        assert kwargs["timeout"] == 30
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr(commit_hook.subprocess, "run", timeout)
    assert commit_hook.main([str(message)]) == 1
    output = capsys.readouterr()
    assert "НЕ ВЫПОЛНЕН" in output.err
    assert "TimeoutExpired" in output.err and "commit:" not in output.out


def test_claim_forecast_keeps_cli_repository_and_publication_context(index, monkeypatch):
    monkeypatch.delenv("COMMIT_CONTRACT_SKIP_CLAIMS", raising=False)
    registry = index / "claims.yaml"
    registry.write_text("schema_version: 1\nkind: active-work\nactive: []\n")
    (index / ".ai-ops.yaml").write_text("team_coordination:\n  publish: true\n")
    monkeypatch.setattr(commit_hook.active_work, "shared_registry_path", lambda root: registry)
    seen = []
    monkeypatch.setattr(commit_hook.active_work, "check_cmd", lambda *a, **kw: seen.append((a, kw)))
    commit_hook.warn_claims(index, ["src/a.py", "src/b.py", "README.md"])
    assert seen == [((registry, ["README.md", "src/"]), {"child_root": index, "published": True})]


def test_unavailable_claims_warns_and_still_runs_contract(index, monkeypatch, capsys):
    monkeypatch.delenv("COMMIT_CONTRACT_SKIP_CLAIMS", raising=False)
    stage(index, "code.py")
    registry = index / "claims.yaml"
    registry.write_text("fixture")
    monkeypatch.setattr(commit_hook.active_work, "shared_registry_path", lambda root: registry)

    def corrupt(*args, **kwargs):
        raise commit_hook.active_work.ActiveWorkCorrupt("fixture")

    monkeypatch.setattr(commit_hook.active_work, "check_cmd", corrupt)
    message = index / "message"
    message.write_text("test: advisory coordination CI #1410\n")
    assert commit_hook.main([str(message)]) == 0
    output = capsys.readouterr()
    assert "координация недоступна" in output.err
    assert "commit: ДОПУСТИМ" in output.out


def test_merged_foreign_claim_stays_silent_and_registry_is_unchanged(index, monkeypatch, capsys):
    stage(index, "src/code.py")
    for args in (("config", "user.email", "fixture@example.invalid"),
                 ("config", "user.name", "Fixture"), ("branch", "-M", "main"),
                 ("commit", "-qm", "test: own fixture"), ("branch", "ai-ops/already-merged")):
        subprocess.run(["git", *args], check=True, capture_output=True)
    aw = commit_hook.active_work
    registry = aw.shared_registry_path(index)
    aw.save(registry, {"schema_version": 1, "kind": "active-work", "active": [{
        "id": "already-merged", "branch": "ai-ops/already-merged", "status": "in-progress",
        "affected_areas": ["src/"], "owner_session": "foreign-session", "machine": aw._machine(),
    }]})
    before = registry.read_bytes()
    monkeypatch.delenv("COMMIT_CONTRACT_SKIP_CLAIMS", raising=False)
    assert aw.main(["check", str(registry), "--areas", "src/"]) == 0
    assert "пересечений по зонам src/ нет" in capsys.readouterr().out
    commit_hook.warn_claims(index, ["src/code.py"])
    output = capsys.readouterr().out
    assert "возможны пересечения" not in output and "already-merged" not in output
    assert registry.read_bytes() == before
