"""Preview заканчивается до любого dispatch с побочными действиями (#1477)."""
from __future__ import annotations

import json
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

from ai_ops_kit.cli import ai_ops_cli, ai_ops_cli_lifecycle
from ai_ops_kit.engine import ai_ops_run, execution_pipeline
from ai_ops_kit.providers import orchestrator_providers, provider_calls

pytestmark = [pytest.mark.unit, pytest.mark.critical_path]
WID = "wi-preview-safety"
TASK = "Добавь выгрузку заказов в CSV"


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local/state"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "src").mkdir()
    (root / "src/export.py").write_text("x = 1\n")
    return root


def _snapshot(root):
    """Содержимое, имена, типы и режимы файлов, включая .git и изолированный HOME."""
    return {
        str(p.relative_to(root)): (stat.S_IMODE(p.lstat().st_mode),
                                  p.readlink() if p.is_symlink() else
                                  p.read_bytes() if p.is_file() else None)
        for p in root.rglob("*")
    }


def _forbidden(*args, **kwargs):
    pytest.fail("preview reached a mutating dispatch boundary")


@pytest.mark.parametrize("intent", list(ai_ops_cli.INTENTS))
def test_every_preview_intent_stops_before_mutating_dispatch(repo, monkeypatch, capsys, intent):
    # Даже будущий зарегистрированный intent должен пройти общий ранний возврат.
    monkeypatch.setattr(ai_ops_cli, "_process_gate", _forbidden)
    monkeypatch.setattr(ai_ops_cli, "_run_intent", _forbidden)
    monkeypatch.setattr(ai_ops_cli, "_main_run_execute", _forbidden)
    monkeypatch.setattr(ai_ops_cli, "_session_identity", _forbidden)
    monkeypatch.setattr(ai_ops_cli_lifecycle, "_intent_specify", _forbidden)
    monkeypatch.setattr(ai_ops_run, "main", _forbidden)
    monkeypatch.setattr(execution_pipeline, "run_pipeline", _forbidden)
    monkeypatch.setattr(execution_pipeline, "_deliver_pr", _forbidden)
    monkeypatch.setattr(orchestrator_providers, "resolve_provider", _forbidden)
    monkeypatch.setattr(orchestrator_providers, "make_provider", _forbidden)
    monkeypatch.setattr(provider_calls, "make_provider", _forbidden)
    before = _snapshot(repo.parent)
    rc = ai_ops_cli.main([
        "preview", intent, TASK, str(repo), "--feature", WID, "--json",
        "--execute", "--open-pr", "--force", "--apply", "--reach", "register",
        "--answers", "зачем=нужно клиентам", "--answer", "purpose", "новый ответ",
        "--signals", '{"size":"small","risk":"low"}',
    ])
    assert rc == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["kind"] == "ExecutionPreview"
    assert preview["intent"] == intent
    assert preview["will_execute_now"] is False
    assert _snapshot(repo.parent) == before


@pytest.mark.parametrize("audience", ["product", "technical"])
def test_human_preview_never_announces_immediate_execution(repo, monkeypatch, capsys, audience):
    monkeypatch.setattr(ai_ops_cli, "_audience", lambda root: audience)
    monkeypatch.setattr(ai_ops_cli, "_main_run_execute", _forbidden)
    monkeypatch.setattr(ai_ops_run, "main", _forbidden)
    before = _snapshot(repo.parent)
    assert ai_ops_cli.main(["preview", "run", TASK, str(repo), "--execute"]) == 0
    output = capsys.readouterr().out
    assert output.strip()
    assert "запускаю сейчас" not in output.lower()
    assert ("■ intent:" in output) == (audience == "technical")
    assert _snapshot(repo.parent) == before


def test_preview_invalid_feature_refuses_without_dispatch(repo, monkeypatch, capsys):
    monkeypatch.setattr(ai_ops_cli, "build_preview", _forbidden)
    monkeypatch.setattr(ai_ops_cli, "_main_run_execute", _forbidden)
    before = _snapshot(repo.parent)
    assert ai_ops_cli.main(["preview", "specify", TASK, str(repo),
                           "--feature", "../escape", "--force"]) == 2
    assert "ОТКАЗ" in capsys.readouterr().err
    assert _snapshot(repo.parent) == before


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("flags", [[], ["--force"], ["--answers", "зачем=новая цель"],
                                   ["--force", "--answers", "зачем=новая цель"]])
def test_preview_specify_neither_creates_nor_overwrites_spec(repo, capsys, existing, flags):
    if existing:
        assert ai_ops_cli.main(["specify", TASK, str(repo), "--feature", WID, "--json"]) == 0
        assert (repo / "features" / WID / "spec.yaml").is_file()
    capsys.readouterr()
    before = _snapshot(repo.parent)
    assert ai_ops_cli.main(["preview", "specify", TASK, str(repo), "--feature", WID,
                           "--json", *flags]) == 0
    assert _snapshot(repo.parent) == before
    assert json.loads(capsys.readouterr().out)["kind"] == "ExecutionPreview"


def test_preview_run_carries_existing_spec_without_writing(repo, monkeypatch, capsys):
    monkeypatch.setattr(ai_ops_cli, "_main_run_execute", _forbidden)
    monkeypatch.setattr(ai_ops_run, "main", _forbidden)
    spec = repo / "features" / WID / "spec.yaml"
    spec.parent.mkdir(parents=True)
    spec.write_text(yaml.safe_dump({
        "schema_version": 1, "kind": "spec", "workitem_id": WID, "level": 1,
        "signals": {"task_type": "ENGINEERING", "size": "small", "risk": "low"},
        "sections": {"goal": {"status": "complete", "content": TASK}},
    }, allow_unicode=True))
    before = _snapshot(repo.parent)
    assert ai_ops_cli.main(["preview", "run", str(repo), "--feature", WID, "--execute", "--json"]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert TASK in preview["understood"]["task"]
    assert preview["understood"]["task_type"] == "ENGINEERING"
    assert preview["will_execute_now"] is False
    assert _snapshot(repo.parent) == before


def test_ordinary_resume_still_forwards_execution_flags(repo, monkeypatch):
    calls = []
    monkeypatch.setattr(ai_ops_run, "main", lambda argv: calls.append(argv) or 17)
    monkeypatch.setattr(ai_ops_cli, "_session_identity", lambda root: "test-session")
    assert ai_ops_cli.main(["resume", str(repo), WID, "--execute", "--force", "--open-pr"]) == 17
    assert len(calls) == 1
    assert calls[0][:3] == ["resume", str(repo), WID]
    assert all(flag in calls[0] for flag in ("--execute", "--force", "--open-pr"))


@pytest.mark.parametrize("flags", [[], ["--execute"], ["--force"], ["--open-pr"],
                                   ["--execute", "--force", "--open-pr", "--deliver-only"]])
def test_preview_resume_does_not_call_resume_handler(repo, monkeypatch, capsys, flags):
    calls = []
    monkeypatch.setattr(ai_ops_run, "main", lambda argv: calls.append(argv) or 0)
    monkeypatch.setattr(ai_ops_cli, "_session_identity", lambda root: "test-session")
    before = _snapshot(repo.parent)
    assert ai_ops_cli.main(["preview", "resume", str(repo), WID, "--json", *flags]) == 0
    assert calls == []
    assert _snapshot(repo.parent) == before
    assert json.loads(capsys.readouterr().out)["will_execute_now"] is False


@pytest.mark.parametrize("intent,flags", [("run", ["--execute"]), ("do", [])])
def test_ordinary_execution_dispatch_still_reached(repo, monkeypatch, capsys, intent, flags):
    calls = []
    monkeypatch.setattr(ai_ops_cli, "_main_run_execute", lambda *args: calls.append(args) or 17)
    assert ai_ops_cli.main([intent, TASK, str(repo), "--json", "--signals",
                           '{"size":"small","risk":"low"}', *flags]) == 17
    assert len(calls) == 1
    assert calls[0][0] == intent
    assert json.loads(capsys.readouterr().out)["will_execute_now"] is True
