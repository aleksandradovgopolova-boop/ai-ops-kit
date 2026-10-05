"""Имена подкоманд графа не исчезают при наличии одноимённого каталога."""
from types import SimpleNamespace

import pytest

from ai_ops_kit.cli.ai_ops_cli_intents import _graph_positionals


@pytest.mark.parametrize("command", ["build", "trace", "gaps", "questions"])
def test_graph_subcommand_survives_same_named_directory(tmp_path, monkeypatch, command):
    (tmp_path / command).mkdir()
    assert (tmp_path / command).is_dir()
    monkeypatch.chdir(tmp_path)
    args = SimpleNamespace(rest=[str(tmp_path), command, "feature-name"], feature=None)
    assert _graph_positionals(args, tmp_path) == (command, "feature-name")


@pytest.mark.parametrize("position", ["first", "last"])
@pytest.mark.parametrize("name", ["build", "trace", "gaps", "questions"])
def test_named_repository_is_removed_once(tmp_path, monkeypatch, name, position):
    root = tmp_path / name
    root.mkdir()
    monkeypatch.chdir(tmp_path)
    rest = [name, "trace", "feature-name"] if position == "first" else ["trace", "feature-name", name]
    args = SimpleNamespace(rest=rest, feature=None)
    assert _graph_positionals(args, root) == ("trace", "feature-name")


def test_default_root_is_not_the_build_output(tmp_path, monkeypatch):
    from ai_ops_kit.cli.ai_ops_cli import _parse_task_and_root
    (tmp_path / "build").mkdir()
    monkeypatch.chdir(tmp_path)
    assert _parse_task_and_root("graph", ["build"]) == ("build", ".")
