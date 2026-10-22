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


@pytest.mark.unit
@pytest.mark.parametrize('assignment', [
    "_t = Path(__file__).parent / 'target.py'\n_t = Path(__file__).parent / 'other.py'\n",
    "_t = Path(__file__).parent / 'target.py'\ndef unrelated():\n    _t = Path(__file__).parent / 'other.py'\n",
    "_t = Path(__file__).parent / 'target.py'\nmatch Path(__file__).parent / 'other.py':\n    case _t:\n        pass\n",
], ids=['reassignment', 'other-scope', 'pattern-capture'])
def test_file_spec_ambiguous_binding_stays_dynamic(tmp_path, assignment):
    import runpy

    (tmp_path / 'target.py').write_text('VALUE = 1\n')
    (tmp_path / 'other.py').write_text('VALUE = 2\n')
    (tmp_path / 'loader.py').write_text(
        'from pathlib import Path\nimport importlib.util as ilu\n' + assignment +
        "spec = ilu.spec_from_file_location('loaded', _t)\n"
        "module = ilu.module_from_spec(spec)\nspec.loader.exec_module(module)\n")
    loaded = runpy.run_path(str(tmp_path / 'loader.py'))
    assert loaded['module'].VALUE == (1 if 'def unrelated' in assignment else 2)
    graph = build_graph(tmp_path, subdirs=None)
    assert graph['uncertainty_kinds'].get('loader.py') == 'dynamic'


@pytest.mark.unit
def test_file_spec_out_of_range_parent_stays_dynamic(tmp_path):
    (tmp_path / 'loader.py').write_text(
        'from pathlib import Path\nimport importlib.util as ilu\n'
        "spec = ilu.spec_from_file_location('loaded', Path(__file__).parents[999] / 'x.py')\n")
    graph = build_graph(tmp_path, subdirs=None)
    assert graph['uncertainty_kinds'].get('loader.py') == 'dynamic'


@pytest.mark.unit
@pytest.mark.parametrize('location', ['outside', 'excluded', 'filtered'])
def test_file_spec_target_outside_graph_stays_dynamic(tmp_path, location):
    import runpy

    root = tmp_path / 'repo'
    root.mkdir()
    if location == 'outside':
        target = tmp_path / 'target.py'
        expression = "Path(__file__).parent.parent / 'target.py'"
    elif location == 'excluded':
        (root / '.ai').mkdir()
        target = root / '.ai' / 'target.py'
        expression = "Path(__file__).parent / '.ai' / 'target.py'"
    else:
        target = root / 'target.py'
        expression = "Path(__file__).parent / 'target.py'"
    target.write_text('VALUE = 7\n')
    (root / 'loader.py').write_text(
        'from pathlib import Path\nimport importlib.util as ilu\n'
        f"spec = ilu.spec_from_file_location('loaded', {expression})\n"
        'module = ilu.module_from_spec(spec)\nspec.loader.exec_module(module)\n')
    assert runpy.run_path(str(root / 'loader.py'))['module'].VALUE == 7
    graph = build_graph(root, subdirs=None,
                        path_filter=lambda rel: location != 'filtered' or rel != 'target.py')
    assert 'target.py' not in graph['files']
    assert graph['uncertainty_kinds'].get('loader.py') == 'dynamic'


def test_file_spec_without_loader_does_not_collect_bindings(tmp_path, monkeypatch):
    import ast
    from ai_ops_kit.context import repo_graph

    source = tmp_path / 'plain.py'
    tree = ast.parse('from pathlib import Path\nx = Path(__file__).parent\n')
    def unexpected_bindings(_tree):
        raise AssertionError('no file loader: binding scan must not run')
    monkeypatch.setattr(repo_graph, '_collect_assignments', unexpected_bindings)
    assert repo_graph._known_file_spec_targets(source, tree) == (set(), True)
