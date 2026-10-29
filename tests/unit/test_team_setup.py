"""Доставка конфигурации, сохранение текста/прав и диагностируемый отказ."""
import importlib.util
import json
from pathlib import Path

import pytest

from ai_ops_kit.lifecycle import project_session as sessions

spec = importlib.util.spec_from_file_location("team_setup_under_test", Path(__file__).resolve().parents[2] / "installer/team_setup.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


@pytest.fixture
def project(tmp_path):
    (tmp_path / ".ai-ops.yaml").write_text("standard:\n  team_session: required\n")
    return tmp_path


def test_delivery_is_idempotent_and_keeps_owner_instructions(project):
    (project / "AGENTS.md").write_text("Свои правила без изменений.\n")
    setup.ensure_team_session(project)
    original = {p: p.read_bytes() for p in project.rglob("*") if p.is_file()}
    setup.ensure_team_session(project)
    assert all(p.read_bytes() == content for p, content in original.items())
    assert (project / "AGENTS.md").read_text().startswith("Свои правила без изменений.\n")
    assert not sessions.configuration_problems(project)


def test_delivery_does_not_enable_experiment_without_explicit_config(tmp_path):
    (tmp_path / ".ai-ops.yaml").write_text("{}")
    assert setup.ensure_team_session(tmp_path)["mode"] == "not-enabled"
    assert not (tmp_path / ".codex").exists()


def test_hooks_preserve_owner_settings_and_do_not_expand_permissions(project):
    path = project / ".claude/settings.json"
    path.parent.mkdir()
    foreign = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo own"}]}
    path.write_text(json.dumps({"permissions": {"deny": ["Bash(rm *)"]}, "hooks": {"Stop": [foreign]}}))
    setup.ensure_team_session(project)
    doc = json.loads(path.read_text())
    assert doc["permissions"] == {"deny": ["Bash(rm *)"]}
    assert doc["hooks"]["Stop"][0] == foreign
    assert not (project / ".codex/config.toml").exists()


@pytest.mark.parametrize("content", ('{broken', '{"hooks":{"Stop":null}}'))
def test_unreadable_settings_are_not_overwritten(project, content):
    path = project / ".codex/hooks.json"
    path.parent.mkdir()
    path.write_text(content)
    result = setup.ensure_team_session(project)
    assert path.read_text() == content
    assert any(a["action"] == "blocked" and a["path"] == ".codex/hooks.json" for a in result["actions"])


def test_broken_instruction_markers_are_not_replaced(project):
    path = project / "CLAUDE.md"
    path.write_text("owner\n" + sessions.BEGIN)
    setup.ensure_team_session(project)
    assert path.read_text() == "owner\n" + sessions.BEGIN


def test_reversed_markers_keep_entire_owner_document(project):
    path = project / "CLAUDE.md"
    original = sessions.END + "\nowner-before\n" + sessions.BEGIN + "\nowner-after"
    path.write_text(original)
    assert any(a["action"] == "blocked" for a in setup.ensure_team_session(project)["actions"])
    assert path.read_text() == original


def test_explicit_opt_out_removes_only_owned_entries(project):
    (project / "AGENTS.md").write_text("owner")
    setup.ensure_team_session(project)
    (project / ".ai-ops.yaml").write_text("standard:\n  team_session: off\n")
    setup.ensure_team_session(project)
    assert sessions.BEGIN not in (project / "AGENTS.md").read_text()
    assert (project / "AGENTS.md").read_text().startswith("owner")
    for relative in sessions.RUNTIMES.values():
        assert sessions.MARKER not in (project / relative).read_text()


def test_default_off_does_not_reformat_owner_settings(project):
    (project / ".ai-ops.yaml").write_text("{}")
    path = project / ".claude/settings.json"
    path.parent.mkdir()
    original = '{"permissions": {"deny": ["Bash(rm *)"]}}'
    path.write_text(original)
    setup.ensure_team_session(project)
    assert path.read_text() == original
