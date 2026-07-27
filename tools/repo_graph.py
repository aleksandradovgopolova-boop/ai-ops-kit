#!/usr/bin/env python3
"""repo_graph.py (v3.6.0) — Repository Graph Lite: первый НЕ-vector retrieval-шаг Context Engine.

Реализует первую ступень цепочки ContextArchitectureDecision (v3.3.2): repository = источник истины,
детерминированный граф ПЕРЕД любым семантическим поиском. Через stdlib `ast` (без сети/vector-DB):
  - symbols: топ-уровневые функции/классы по файлам (symbol_index);
  - imports: зависимости модулей -> внутренние рёбра (файл A импортирует файл B репо);
  - tests: тест-файлы и что они импортируют;
  - impact(changed): обратный обход рёбер — какие файлы (транзитивно) зависят от изменённого
    (для automatic write-scope / relevant-test-selection в v3.6).

Только Python-файлы (лайт). CLI: repo_graph.py [root] [--impact tools/x.py] [--json] | --selftest
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
DEFAULT_SUBDIRS = ("tools", "validation")


def _py_files(root: Path, subdirs, path_filter=None):
    out = []
    for sd in subdirs:
        d = root / sd
        if d.is_dir():
            for p in sorted(d.rglob("*.py")):
                # v3.7.0: access pre-filter — denied-путь НЕ читается для графа
                if path_filter is not None and not path_filter(str(p.relative_to(root))):
                    continue
                out.append(p)
    return out


def _analyze(path: Path):
    """(symbols, imported_module_stems) файла через ast; все Import/ImportFrom (вкл. в функциях)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, OSError):
        return [], set()
    symbols = [n.name for n in tree.body
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                mods.add(a.name.split(".")[0])
        elif isinstance(n, ast.ImportFrom):
            if n.module and n.level == 0:
                mods.add(n.module.split(".")[0])
    return symbols, mods


def build_graph(root=PKG, subdirs=DEFAULT_SUBDIRS, path_filter=None) -> dict:
    root = Path(root)
    files = _py_files(root, subdirs, path_filter=path_filter)
    stem_to_rel = {}
    rels = []
    for f in files:
        rel = str(f.relative_to(root))
        rels.append((f, rel))
        stem_to_rel[f.stem] = rel   # плоское имя модуля -> путь (репо импортит по bare stem via sys.path)

    file_info, symbol_index, import_edges, tests = {}, {}, {}, {}
    for f, rel in rels:
        syms, mods = _analyze(f)
        file_info[rel] = {"symbols": syms, "imports": sorted(mods)}
        for s in syms:
            symbol_index.setdefault(s, []).append(rel)
        internal = sorted({stem_to_rel[m] for m in mods if m in stem_to_rel and stem_to_rel[m] != rel})
        import_edges[rel] = internal
        stem = Path(rel).stem
        if stem.startswith("test_") or stem.endswith("_test"):
            tests[rel] = internal
    return {"kind": "repository-graph", "root": str(root), "subdirs": list(subdirs),
            "file_count": len(rels), "files": file_info, "symbol_index": symbol_index,
            "import_edges": import_edges, "tests": tests}


def impact(graph: dict, changed_rel: str) -> list:
    """Файлы, которые (транзитивно) импортируют changed_rel — обратный обход рёбер импорта."""
    edges = graph.get("import_edges", {})
    reverse = {}
    for src, dsts in edges.items():
        for d in dsts:
            reverse.setdefault(d, set()).add(src)
    seen, stack = set(), [changed_rel]
    while stack:
        cur = stack.pop()
        for dep in reverse.get(cur, ()):
            if dep not in seen:
                seen.add(dep)
                stack.append(dep)
    return sorted(seen)


def selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    # синтетический репо: b<-a, test_b импортирует b
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "tools").mkdir()
        (root / "tools" / "b.py").write_text("def foo():\n    return 1\nclass Bar:\n    pass\n", encoding="utf-8")
        (root / "tools" / "a.py").write_text("import b\n\ndef use():\n    return b.foo()\n", encoding="utf-8")
        (root / "tools" / "test_b.py").write_text("import b\n\ndef test_foo():\n    assert b.foo()==1\n", encoding="utf-8")
        g = build_graph(root, ("tools",))
        expect("symbols извлечены (foo, Bar в b.py)",
               set(g["files"]["tools/b.py"]["symbols"]) == {"foo", "Bar"})
        expect("symbol_index: foo -> b.py", g["symbol_index"]["foo"] == ["tools/b.py"])
        expect("import-ребро a.py -> b.py", g["import_edges"]["tools/a.py"] == ["tools/b.py"])
        expect("тест-файл распознан (test_b.py -> b.py)", g["tests"].get("tools/test_b.py") == ["tools/b.py"])
        imp = impact(g, "tools/b.py")
        expect("impact(b.py) включает a.py и test_b.py (обратные зависимости)",
               "tools/a.py" in imp and "tools/test_b.py" in imp)
        expect("impact(a.py) пуст (никто не импортит a)", impact(g, "tools/a.py") == [])

    # дог-фуд: реальный граф кита (tools+validation), стабильные факты
    real = build_graph()
    expect(f"реальный граф кита строится без ошибок ({real['file_count']} файлов)",
           real["file_count"] > 50 and isinstance(real["symbol_index"], dict))
    imp_gp = impact(real, "tools/gate_policy.py")
    expect("impact(gate_policy) включает execution_pipeline и bench_lite (реальные импортёры)",
           "tools/execution_pipeline.py" in imp_gp and "tools/bench_lite.py" in imp_gp)
    expect("symbol_index покрывает известный символ (build_graph)",
           "build_graph" in real["symbol_index"])

    print("repo_graph selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    # позиционные аргументы, ИСКЛЮЧАЯ флаги и значение --impact (иначе путь impact примут за root)
    skip = set()
    if "--impact" in argv:
        skip.add(argv.index("--impact") + 1)
    args = [a for i, a in enumerate(argv) if not a.startswith("--") and i not in skip]
    root = Path(args[0]) if args else PKG
    g = build_graph(root)
    if "--impact" in argv:
        changed = argv[argv.index("--impact") + 1]
        imp = impact(g, changed)
        if "--json" in argv:
            print(json.dumps({"changed": changed, "impact": imp}, ensure_ascii=False, indent=2))
        else:
            print(f"IMPACT {changed} -> {len(imp)} файлов: {imp}")
        return 0
    if "--json" in argv:
        print(json.dumps({k: v for k, v in g.items() if k != "files"}, ensure_ascii=False, indent=2))
    else:
        print(f"REPO-GRAPH: {g['file_count']} файлов; символов={len(g['symbol_index'])}; "
              f"тестов={len(g['tests'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
