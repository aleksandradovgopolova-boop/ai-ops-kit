"""Удалённая работа не исполняется, а отбор зависимостей и границы доступа сохраняются."""
import ast
from collections import Counter
from pathlib import Path

import pytest
import yaml

from ai_ops_kit.context import context_engine, repo_graph

KIT = Path(__file__).resolve().parents[2]


def test_graph_reads_and_parses_each_source_once_and_sees_next_edit(tmp_path, monkeypatch):
    (tmp_path / "value.py").write_text("value = 1\n")
    (tmp_path / "test_value.py").write_text("import value\nfrom importlib import import_module\n")
    (tmp_path / "view.ts").write_text("import {value} from './value';\n")
    reads, parses = Counter(), Counter()
    original_read, original_parse = Path.read_text, ast.parse

    def read(path, *args, **kwargs):
        if path.parent == tmp_path:
            reads[path.name] += 1
        return original_read(path, *args, **kwargs)

    def parse(source, filename='<unknown>', *args, **kwargs):
        if Path(filename).parent == tmp_path:
            parses[Path(filename).name] += 1
        return original_parse(source, filename, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    monkeypatch.setattr(ast, "parse", parse)
    graph = repo_graph.build_graph(tmp_path, subdirs=None)
    assert reads == {"value.py": 1, "test_value.py": 1, "view.ts": 1}
    assert parses == {"value.py": 1, "test_value.py": 1}
    assert repo_graph.affected_tests(graph, ["value.py"]) == ["test_value.py"]
    assert graph["uncertainty_kinds"] == {"test_value.py": "dynamic"}
    (tmp_path / "value.py").write_text("def broken(:\n")
    fresh = repo_graph.build_graph(tmp_path, subdirs=None)
    assert fresh["uncertainty_kinds"]["value.py"] == "unreadable"


def test_document_search_does_not_build_code_graph_or_read_denied_source(tmp_path, monkeypatch):
    (tmp_path / "guide.md").write_text("# discounts guide\n")
    private = tmp_path / "private"
    private.mkdir()
    denied = private / "secrets.py"
    denied.write_text("# discounts\nvalue = 1\n")
    afp = {"rules": [{"role": "executor", "allowed_classes": ["internal"]}]}
    dcp = {"default_class": "internal", "rules": [{"path_prefix": "private/", "class": "confidential"}]}
    original_read = Path.read_text

    def read(path, *args, **kwargs):
        assert path != denied, "denied source must not be read"
        return original_read(path, *args, **kwargs)

    def no_graph(*args, **kwargs):
        pytest.fail("document-only candidates do not need a code graph")

    monkeypatch.setattr(Path, "read_text", read)
    monkeypatch.setattr(repo_graph, "build_graph", no_graph)
    view = context_engine.build_context(tmp_path, "discounts", "executor", sha="fixture",
                                        afp=afp, dcp=dcp, semantic_recall_floor=0)
    assert view["valid"]
    assert {item["file"] for item in view["included"]} == {"guide.md"}
    assert view["sources_used"]["graph_added"] == 0
    assert "нет Python-кандидатов" in view["sources_used"]["graph_reason"]


@pytest.mark.parametrize("workflow", ["package-quality", "pr-smoke", "docs"])
def test_only_superseded_pr_run_is_cancelled(workflow):
    config = yaml.safe_load((KIT / ".github/workflows" / f"{workflow}.yml").read_text())
    concurrency = config["concurrency"]
    # Workflow/event разделяют контексты; PR number группирует только один PR;
    # run_id изолирует каждый push/manual. Проверяется реальная декларация Actions.
    assert concurrency["group"] == (
        "${{ github.workflow }}-${{ github.event_name }}-"
        "${{ github.event.pull_request.number || github.run_id }}")
    assert concurrency["cancel-in-progress"] == "${{ github.event_name == 'pull_request' }}"
