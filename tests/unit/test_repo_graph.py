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
        imp_gp = impact(real, "ai_ops_kit/gates/gate_policy.py")
        assert "ai_ops_kit/engine/execution_pipeline.py" in imp_gp
        assert "ai_ops_kit/devtools/bench_lite.py" in imp_gp

    def test_symbol_index_covers_known_symbol(self):
        real = build_graph()
        assert "build_graph" in real["symbol_index"]


@pytest.mark.unit
class TestFileSpecKnownEdges:
    """spec_from_file_location по известному __file__-пути — статическое ребро, не динамика.
    Непрослеживаемый путь остаётся динамическим (граф неполон — безопасный full)."""

    @pytest.fixture(autouse=True)
    def setup_repo(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "pkg").mkdir()
            (root / "pkg" / "target.py").write_text("VALUE = 1\n", encoding="utf-8")
            # Загрузка по пути от __file__ к соседнему файлу — цель известна статически.
            (root / "pkg" / "loader.py").write_text(
                "from pathlib import Path\n"
                "import importlib.util as ilu\n"
                "_t = Path(__file__).resolve().parent / 'target.py'\n"
                "_spec = ilu.spec_from_file_location('target_mod', _t)\n"
                "_mod = ilu.module_from_spec(_spec)\n"
                "_spec.loader.exec_module(_mod)\n"
                "VALUE = _mod.VALUE\n", encoding="utf-8")
            (root / "pkg" / "test_loader.py").write_text(
                "import loader\n\ndef test_v():\n    assert loader.VALUE == 1\n", encoding="utf-8")
            # Путь не выводится из __file__ — потребитель/цель неизвестны, файл динамичен.
            (root / "pkg" / "dyn.py").write_text(
                "import os\n"
                "from pathlib import Path\n"
                "import importlib.util as ilu\n"
                "_p = Path(os.environ['SOMEWHERE'])\n"
                "_s = ilu.spec_from_file_location('x', _p)\n", encoding="utf-8")
            self.graph = build_graph(root, ("pkg",))

    def test_resolvable_loader_is_not_dynamic(self):
        assert "pkg/loader.py" not in self.graph["uncertainties"]
        assert self.graph["uncertainty_kinds"].get("pkg/loader.py") is None

    def test_resolved_target_becomes_a_real_edge(self):
        assert "pkg/target.py" in self.graph["import_edges"]["pkg/loader.py"]

    def test_target_change_selects_the_loaders_test(self):
        # Без ребра правка target.py не выбрала бы тест загрузчика — это и была бы дыра покрытия.
        assert "pkg/test_loader.py" in affected_tests(self.graph, ["pkg/target.py"])

    def test_unresolvable_path_stays_dynamic(self):
        assert self.graph["uncertainty_kinds"].get("pkg/dyn.py") == "dynamic"
