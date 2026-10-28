"""Ограниченный opt-in AST-пилот; реальные grammar нужны только optional-тестам."""
import pytest

from ai_ops_kit.context import repo_graph

pytestmark = pytest.mark.unit


def ast_available():
    pytest.importorskip('tree_sitter')
    pytest.importorskip('tree_sitter_javascript')
    pytest.importorskip('tree_sitter_typescript')


def test_default_never_loads_optional_parser(tmp_path, monkeypatch):
    (tmp_path / 'main.ts').write_text('import x from "./x";')
    def forbidden(_extension):
        raise AssertionError('default must not import optional packages')
    monkeypatch.setattr(repo_graph, '_load_js_parser', forbidden)
    graph = repo_graph.build_graph(tmp_path, subdirs=None)
    assert graph['files']['main.ts']['imports'] == ['x']
    assert 'js_analysis' not in graph


@pytest.mark.parametrize('error', [ImportError, TypeError, RuntimeError])
def test_optional_unavailable_falls_back_with_uncertainty(tmp_path, monkeypatch, error):
    (tmp_path / 'main.ts').write_text('import x from "./x";')
    (tmp_path / 'x.ts').write_text('export const x = 1;')
    def unavailable(_extension):
        raise error('optional parser unavailable')
    monkeypatch.setattr(repo_graph, '_load_js_parser', unavailable)
    graph = repo_graph.build_graph(tmp_path, subdirs=None, js_analyzer='tree-sitter')
    assert graph['import_edges']['main.ts'] == ['x.ts']
    assert graph['js_analysis']['main.ts']['backend'] == 'regex'
    assert graph['js_analysis']['main.ts']['fallback'] == f'parser-unavailable:{error.__name__}'
    assert graph['uncertainty_kinds']['main.ts'] == 'unbounded'


def test_parser_failure_preserves_fallback(tmp_path, monkeypatch):
    (tmp_path / 'main.js').write_text('import "./x";')
    class BrokenParser:
        def parse(self, _source):
            raise RuntimeError('parser failed')
    monkeypatch.setattr(repo_graph, '_load_js_parser', lambda _ext: BrokenParser())
    graph = repo_graph.build_graph(tmp_path, subdirs=None, js_analyzer='tree-sitter')
    assert graph['files']['main.js']['imports'] == ['x']
    assert graph['js_analysis']['main.js']['fallback'] == 'parser-failed:RuntimeError'
    assert graph['uncertainty_kinds']['main.js'] == 'unbounded'


@pytest.mark.parametrize('extension', ['js', 'jsx', 'mjs', 'cjs', 'ts', 'tsx'])
def test_real_grammar_imports_and_symbols(tmp_path, extension):
    ast_available()
    content = '''// import "./comment";
const text = "require('./string')";
import /* comment */ { x } from /* comment */ './static';
import './effect';
export { x } from './reexport';
const lazy = import('./lazy');
const common = require(/* comment */ './common');
export function real() { const nested = 1; }
'''
    if extension in ('jsx', 'tsx'):
        content += 'const view = <div>import "./jsx-text"</div>;\n'
    if extension in ('ts', 'tsx'):
        content += 'import alias = require("./alias");\ntype T = import("./types").T;\n'
    path = tmp_path / f'main.{extension}'
    path.write_text(content)
    before = path.read_bytes()
    graph = repo_graph.build_graph(tmp_path, subdirs=None, js_analyzer='tree-sitter')
    analysis = graph['js_analysis'][path.name]
    assert analysis['backend'] == 'tree-sitter'
    expected = {'./static', './effect', './reexport', './lazy', './common'}
    if extension in ('ts', 'tsx'):
        expected.update({'./alias', './types'})
    assert set(analysis['specifiers']) == expected
    assert 'real' in graph['files'][path.name]['symbols']
    assert 'nested' not in graph['files'][path.name]['symbols']
    assert graph['uncertainty_kinds'][path.name] == 'unbounded'
    assert path.read_bytes() == before


def test_real_ast_adds_edges_and_affected_tests(tmp_path):
    ast_available()
    (tmp_path / 'target.ts').write_text('export const value = 1;')
    (tmp_path / 'main.ts').write_text('export const loader = import(/* lazy */ "./target");')
    (tmp_path / 'main.test.ts').write_text('import /* test */ "./main";')
    baseline = repo_graph.build_graph(tmp_path, subdirs=None)
    graph = repo_graph.build_graph(tmp_path, subdirs=None, js_analyzer='tree-sitter')
    assert baseline['import_edges']['main.ts'] == []
    assert graph['import_edges']['main.ts'] == ['target.ts']
    assert repo_graph.affected_tests(graph, ['target.ts']) == ['main.test.ts']


def test_real_syntax_recovery_is_not_success(tmp_path):
    ast_available()
    (tmp_path / 'bad.ts').write_text('import "./preserved"; const = ;')
    graph = repo_graph.build_graph(tmp_path, subdirs=None, js_analyzer='tree-sitter')
    assert graph['files']['bad.ts']['imports'] == ['preserved']
    assert graph['js_analysis']['bad.ts']['fallback'] == 'syntax-error'
    assert graph['uncertainty_kinds']['bad.ts'] == 'unreadable'


def test_computed_and_escaped_imports_stay_uncertain(tmp_path):
    ast_available()
    (tmp_path / 'main.ts').write_text('import(name); require(prefix + name); import "./a\\u0062";')
    graph = repo_graph.build_graph(tmp_path, subdirs=None, js_analyzer='tree-sitter')
    assert graph['js_analysis']['main.ts']['unresolved'] is True
    assert graph['uncertainty_kinds']['main.ts'] == 'unbounded'


def test_unreadable_source_is_reported_without_success(tmp_path):
    (tmp_path / 'bad.ts').write_bytes(b'\xff')
    graph = repo_graph.build_graph(tmp_path, subdirs=None, js_analyzer='tree-sitter')
    assert graph['js_analysis']['bad.ts'] == {'backend': 'none', 'fallback': 'source-unreadable'}
    assert graph['uncertainty_kinds']['bad.ts'] == 'unreadable'


def test_invalid_backend_is_rejected(tmp_path):
    with pytest.raises(ValueError, match='js_analyzer'):
        repo_graph.build_graph(tmp_path, js_analyzer='typo')


def test_opt_in_preserves_python_graph_and_does_not_load_without_js(tmp_path, monkeypatch):
    (tmp_path / 'main.py').write_text('import target\ndef run(): pass\n')
    (tmp_path / 'target.py').write_text('VALUE = 1\n')
    (tmp_path / 'ignored.ts').write_text('import "./target";')
    def forbidden(_extension):
        raise AssertionError('include_js=False must not load optional packages')
    monkeypatch.setattr(repo_graph, '_load_js_parser', forbidden)
    baseline = repo_graph.build_graph(tmp_path, subdirs=None, include_js=False)
    graph = repo_graph.build_graph(tmp_path, subdirs=None, include_js=False, js_analyzer='tree-sitter')
    assert graph.pop('js_analysis') == {}
    assert graph == baseline


def test_unavailable_grammar_is_loaded_once_per_build(tmp_path, monkeypatch):
    calls = []
    def unavailable(extension):
        calls.append(extension)
        raise ImportError('optional grammar unavailable')
    monkeypatch.setattr(repo_graph, '_load_js_parser', unavailable)
    for name in ('a.ts', 'b.ts', 'c.tsx', 'd.js', 'e.jsx', 'f.cjs', 'g.mjs'):
        (tmp_path / name).write_text('export const value = 1;')
    first = repo_graph.build_graph(tmp_path, subdirs=None, js_analyzer='tree-sitter')
    assert sorted(calls) == ['.js', '.ts', '.tsx']
    assert len(first['js_analysis']) == 7
    repo_graph.build_graph(tmp_path, subdirs=None, js_analyzer='tree-sitter')
    assert len(calls) == 6
