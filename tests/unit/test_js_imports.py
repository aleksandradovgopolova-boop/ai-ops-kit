"""Импорты JS/TS по синтаксическому дереву (#1408): что видит дерево и где честный fallback.

Тесты разбора деревом требуют опциональных пакетов tree-sitter. Без них — skip, НО с признаком
AI_OPS_JSTS_AST=1 (его ставит CI-workflow jsts-ast, где пакеты установлены) отсутствие грамматики
— провал: вызвавший проверку обязан получить исполнение, а не тихий пропуск. Fallback-ветки
(нет пакета, синтаксическая ошибка, .vue) проверяются без пакетов.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ai_ops_kit.context import js_imports as J
from ai_ops_kit.planning import architecture_invariants as A

PKG = next(p for p in Path(__file__).resolve().parents if (p / "VERSION").is_file())
HAVE_AST = all(importlib.util.find_spec(m) for m in
               ("tree_sitter", "tree_sitter_javascript", "tree_sitter_typescript"))
needs_ast = pytest.mark.skipif(not HAVE_AST and os.environ.get("AI_OPS_JSTS_AST") != "1",
                               reason="нет tree-sitter (опционально); CI jsts-ast ставит AI_OPS_JSTS_AST=1")

# Каждая строка — случай, на котором прежний построчный regex ошибается или угадывает верно.
TS_SOURCE = """import {
  query,
  close,
} from '../db/client'
// import legacy from '../db/legacy'
const s = "require('../db/fake')"
export { a } from '../db/re'
import type { Row } from './types'
import x = require('./legacy-ts')
const lazy = await import(
  '../db/lazy'
)
const tpl = import(`./tpl`)
const dyn = import(`./${name}`)
const byVar = require(path)
const cjs = require('./cjs')
"""
EXPECTED = [("../db/client", 1), ("../db/re", 7), ("./types", 8), ("./legacy-ts", 9),
            ("../db/lazy", 10), ("./tpl", 13), ("./cjs", 16)]


def _read(suffix, text):
    return [(i.specifier, i.line) for i in J.AstImportReader().read(suffix, text)]


@needs_ast
def test_tree_reads_multiline_dynamic_reexport_and_ts_forms():
    assert _read(".ts", TS_SOURCE) == EXPECTED


@needs_ast
def test_comment_string_and_computed_specifiers_are_not_edges():
    specs = {s for s, _ in _read(".ts", TS_SOURCE)}
    assert not specs & {"../db/legacy", "../db/fake"}
    assert not any("${" in s for s in specs)


@needs_ast
@pytest.mark.parametrize("suffix, text", [
    (".jsx", "import React from 'react'\nexport const A = () => <div/>\n"),
    (".tsx", "import { db } from '../db'\nexport const B = <T,>(x: T) => <b>{x}</b>\n"),
    (".mjs", "export * from './all.mjs'\n"),
    (".cjs", "module.exports = require('./x.cjs')\n"),
])
def test_each_mapped_extension_is_parsed_by_its_grammar(suffix, text):
    assert _read(suffix, text), f"{suffix}: импорт не найден"


@needs_ast
def test_syntax_error_is_reported_not_partial_success():
    with pytest.raises(J.AstUnavailable) as exc:
        J.AstImportReader().read(".ts", "import { a from './x'\nconst = ;\n")
    assert exc.value.reason == J.SYNTAX_ERROR


@needs_ast
def test_escaped_specifier_falls_back_instead_of_losing_the_import(tmp_path):
    with pytest.raises(J.AstUnavailable) as exc:
        J.AstImportReader().read(".ts", "import a from '../db/caf\\u00e9'\nimport b from './ok'\n")
    assert exc.value.reason == J.ESCAPED_SPECIFIER
    root = _child(tmp_path, {"src/ui/a.ts": "import a from '../db/x\\u0041'\n"})
    edges, parse = A.analyze_import_graph(root, ZONES, parser="tree-sitter")
    assert parse["fallbacks"] == {J.ESCAPED_SPECIFIER: 1} and len(edges) == 1


def test_unsupported_extension_is_reported():
    with pytest.raises(J.AstUnavailable) as exc:
        J.AstImportReader().read(".vue", "<script>import a from './a'</script>")
    assert exc.value.reason == J.UNSUPPORTED


def test_missing_package_is_reported_once_per_grammar(monkeypatch):
    calls = []

    def missing(grammar):
        calls.append(grammar)
        raise ImportError("No module named 'tree_sitter'")
    monkeypatch.setattr(J, "_load_language", missing)
    reader = J.AstImportReader()
    for _ in range(3):
        with pytest.raises(J.AstUnavailable) as exc:
            reader.read(".ts", "import a from './a'\n")
        assert exc.value.reason == J.NOT_INSTALLED
    assert calls == ["typescript"]


def test_default_path_never_imports_tree_sitter(tmp_path):
    """Регулярный путь (default) не тянет опциональный пакет — его может не быть у дочки."""
    child = tmp_path / "child"
    (child / "src/ui").mkdir(parents=True)
    (child / "src/ui/a.ts").write_text("import b from '../db/b'\n")
    code = ("import sys; from ai_ops_kit.planning import architecture_invariants as A; "
            f"A.analyze_import_graph({str(child)!r}, {{'ui': ['src/ui/**'], 'db': ['src/db/**']}}); "
            "print(sorted(m for m in sys.modules if m.startswith('tree_sitter')))")
    out = subprocess.run([sys.executable, "-c", code], cwd=PKG, capture_output=True, text=True,
                         env={**os.environ, "PYTHONPATH": str(PKG)}, timeout=60, check=True)
    assert out.stdout.strip() == "[]"


# ── Подключение к проверке слоёв дочки (architecture_invariants) ──

ZONES = {"ui": ["src/ui/**"], "db": ["src/db/**"]}


def _child(tmp_path, files):
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


@needs_ast
def test_tree_parser_finds_layer_violation_regex_misses_and_drops_false_alarms(tmp_path):
    root = _child(tmp_path, {"src/ui/page.ts": TS_SOURCE, "src/db/client.ts": "export const q = 1\n"})
    regex = {e["import"] for e in A.build_import_graph(root, ZONES)}
    tree = {e["import"] for e in A.build_import_graph(root, ZONES, parser="tree-sitter")}
    assert "../db/client" in tree and "../db/client" not in regex      # пропуск regex закрыт
    assert "../db/lazy" in tree and "../db/lazy" not in regex
    assert {"../db/legacy", "../db/fake"} <= regex                       # ложные тревоги regex
    assert not {"../db/legacy", "../db/fake"} & tree


def test_unavailable_tree_falls_back_to_regex_with_visible_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(J, "_load_language", lambda g: (_ for _ in ()).throw(ImportError("nope")))
    root = _child(tmp_path, {"src/ui/a.ts": "import q from '../db/q'\n",
                             "src/ui/b.vue": "<script>import r from '../db/r'</script>\n"})
    edges, parse = A.analyze_import_graph(root, ZONES, parser="tree-sitter")
    assert {e["import"] for e in edges} == {"../db/q", "../db/r"}       # регрессии против regex нет
    assert parse["files"] == {"tree-sitter": 0, "regex": 2}
    assert parse["fallbacks"] == {J.NOT_INSTALLED: 1, J.UNSUPPORTED: 1}
    summary = A.parse_summary(parse)
    assert "tree-sitter не установлен: 1" in summary and J.INSTALL_HINT in summary


def test_report_carries_parse_and_unknown_parser_is_named(tmp_path):
    import yaml
    decl = {"zones": ZONES, "parser": "babel",
            "rules": [{"id": "ui-not-db", "forbid": {"from": "ui", "to": "db"}, "reason": "слой"}]}
    root = _child(tmp_path, {"src/ui/a.ts": "import q from '../db/q'\n"})
    (root / "architecture-invariants.yaml").write_text(yaml.safe_dump(decl), encoding="utf-8")
    rep = A.report(root)
    assert rep["counts"]["violated"] == 1                                 # проверка не потеряна
    assert rep["parse"]["requested"] == "regex" and "babel" in rep["parse"]["problem"]
    assert "babel" in A.parse_summary(rep["parse"])


def test_default_report_output_is_unchanged(tmp_path):
    assert A.parse_summary({"requested": "regex", "files": {"tree-sitter": 0, "regex": 3},
                            "fallbacks": {}}) is None
    assert A.parse_summary(None) is None


# ── Замер (devtools.jsts_import_compare) ──

@needs_ast
def test_compare_reports_regex_misses_and_false_alarms(tmp_path):
    from ai_ops_kit.devtools import jsts_import_compare as C
    root = _child(tmp_path, {"src/ui/page.ts": TS_SOURCE, "src/ui/bad.ts": "import { a from './x'\n"})
    result = C.compare(root)
    assert result["files"] == 2 and result["fallbacks"] == {J.SYNTAX_ERROR: 1}
    assert any(s.endswith("-> ../db/client") for s in result["samples"]["only_tree"])
    assert any(s.endswith("-> ../db/legacy") for s in result["samples"]["only_regex"])
    assert result["pairs"]["both"] == len(set(EXPECTED) - {("../db/client", 1), ("../db/lazy", 10),
                                                           ("./tpl", 13)})


def test_compare_without_tree_sitter_is_not_executed(tmp_path, monkeypatch, capsys):
    from ai_ops_kit.devtools import jsts_import_compare as C
    monkeypatch.setattr(J, "_load_language", lambda g: (_ for _ in ()).throw(ImportError("nope")))
    root = _child(tmp_path, {"src/a.ts": "import b from './b'\n"})
    assert C.main([str(root)]) == 2
    assert "НЕ ИСПОЛНЕНО" in capsys.readouterr().err
