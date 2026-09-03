"""Гранулярные тесты repo_graph (мигрировано из test_repo_graph_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import tempfile

import pytest

from ai_ops_kit.context.repo_graph import (
    Path,
    affected_tests,
    build_graph,
    impact,
)


@pytest.mark.unit
class TestPythonGraph:
    @pytest.fixture(autouse=True)
    def setup_repo(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "tools").mkdir()
            (root / "tools" / "b.py").write_text(
                "def foo():\n    return 1\nclass Bar:\n    pass\n", encoding="utf-8")
            (root / "tools" / "a.py").write_text(
                "import b\n\ndef use():\n    return b.foo()\n", encoding="utf-8")
            (root / "tools" / "test_b.py").write_text(
                "import b\n\ndef test_foo():\n    assert b.foo()==1\n", encoding="utf-8")
            self.graph = build_graph(root, ("tools",))

    def test_symbols_extracted(self):
        assert set(self.graph["files"]["tools/b.py"]["symbols"]) == {"foo", "Bar"}

    def test_symbol_index(self):
        assert self.graph["symbol_index"]["foo"] == ["tools/b.py"]

    def test_import_edge(self):
        assert self.graph["import_edges"]["tools/a.py"] == ["tools/b.py"]

    def test_test_file_recognized(self):
        assert self.graph["tests"].get("tools/test_b.py") == ["tools/b.py"]

    def test_impact_includes_dependents(self):
        imp = impact(self.graph, "tools/b.py")
        assert "tools/a.py" in imp
        assert "tools/test_b.py" in imp

    def test_impact_leaf_is_empty(self):
        assert impact(self.graph, "tools/a.py") == []

    def test_affected_tests(self):
        at = affected_tests(self.graph, ["tools/b.py"])
        assert "tools/test_b.py" in at

    def test_affected_tests_empty_for_leaf(self):
        assert affected_tests(self.graph, ["tools/a.py"]) == []


@pytest.mark.unit
class TestJsGraph:
    @pytest.fixture(autouse=True)
    def setup_js_repo(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "src").mkdir()
            (root / "src" / "utils.ts").write_text(
                "export function helper() { return 1; }\n", encoding="utf-8")
            (root / "src" / "main.ts").write_text(
                "import { helper } from './utils';\nconsole.log(helper());\n", encoding="utf-8")
            (root / "src" / "utils.test.ts").write_text(
                "import { helper } from './utils';\ntest('helper', () => expect(helper()).toBe(1));\n",
                encoding="utf-8")
            self.graph = build_graph(root, ("src",))

    def test_js_symbols_extracted(self):
        assert "helper" in self.graph["files"]["src/utils.ts"]["symbols"]

    def test_js_import_edge(self):
        assert "src/utils.ts" in self.graph["import_edges"].get("src/main.ts", [])

    def test_js_test_file_recognized(self):
        assert "src/utils.test.ts" in self.graph["tests"]

    def test_js_affected_tests(self):
        at = affected_tests(self.graph, ["src/utils.ts"])
        assert "src/utils.test.ts" in at


@pytest.mark.unit
class TestRealKitGraph:
    def test_real_graph_builds(self):
        real = build_graph()
        assert real["file_count"] > 50
        assert isinstance(real["symbol_index"], dict)

    def test_impact_gate_policy(self):
        real = build_graph()
        imp_gp = impact(real, "tools/gate_policy.py")
        assert "ai_ops_kit/engine/execution_pipeline.py" in imp_gp
        assert "ai_ops_kit/devtools/bench_lite.py" in imp_gp

    def test_symbol_index_covers_known_symbol(self):
        real = build_graph()
        assert "build_graph" in real["symbol_index"]
