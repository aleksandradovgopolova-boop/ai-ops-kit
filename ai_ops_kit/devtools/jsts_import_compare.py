#!/usr/bin/env python3
"""Замер: импорты JS/TS регулярным выражением против синтаксического дерева (#1408, dev-only).

Для каждого JS/TS-файла репозитория (каталоги сборки и зависимостей пропускаются тем же списком,
что у проверки слоёв дочки) сравниваются множества (файл, импорт), найденные двумя способами:
прежним построчным regex (`architecture_invariants`) и деревом (`context.js_imports`). Время
меряется отдельно для каждого способа по уже прочитанным текстам — чтение диска в него не входит.

Это СРАВНЕНИЕ, а не полнота против эталона: эталона нет. Расхождения печатаются примерами, чтобы
человек разобрал, кто из двух прав (комментарий, строка, многострочный импорт…).

  python3 -m ai_ops_kit.devtools.jsts_import_compare <repo> [--samples 15] [--json]
Требует опциональные пакеты: pip install tree-sitter tree-sitter-javascript tree-sitter-typescript
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from ai_ops_kit.context import js_imports
from ai_ops_kit.planning import architecture_invariants as arch


def _sources(root: Path) -> list:
    files = []
    for path in sorted(arch._iter_source_files(root)):
        try:
            files.append((path.relative_to(root).as_posix(), path.suffix,
                          path.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue
    return files


def _timed(fn):
    start = time.perf_counter()
    result = fn()
    return result, time.perf_counter() - start


def _run_regex(files):
    return {(rel, imp.specifier): imp.line
            for rel, _, text in files for imp in arch._regex_imports(text)}


def _run_tree(files):
    reader, found, fallbacks = js_imports.AstImportReader(), {}, {}
    for rel, suffix, text in files:
        try:
            imports = reader.read(suffix, text)
        except js_imports.AstUnavailable as exc:
            fallbacks.setdefault(exc.reason, []).append(rel)
            continue
        found.update({(rel, imp.specifier): imp.line for imp in imports})
    return found, fallbacks


def compare(root, samples: int = 15) -> dict:
    files = _sources(Path(root))
    regex, regex_s = _timed(lambda: _run_regex(files))
    (tree, fallbacks), tree_s = _timed(lambda: _run_tree(files))
    skipped = {rel for rels in fallbacks.values() for rel in rels}
    regex_cmp = {k: v for k, v in regex.items() if k[0] not in skipped}   # сравнимо только общее
    only_regex = sorted(set(regex_cmp) - set(tree))
    only_tree = sorted(set(tree) - set(regex_cmp))
    return {
        "kind": "jsts-import-compare", "root": str(root), "files": len(files),
        "tree_parsed_files": len(files) - len(skipped),
        "fallbacks": {k: len(v) for k, v in sorted(fallbacks.items())},
        "pairs": {"regex": len(regex_cmp), "tree": len(tree), "both": len(set(regex_cmp) & set(tree)),
                  "only_regex": len(only_regex), "only_tree": len(only_tree)},
        "seconds": {"regex": round(regex_s, 3), "tree": round(tree_s, 3)},
        "samples": {"only_regex": [f"{f}:{regex[(f, s)]} -> {s}" for f, s in only_regex[:samples]],
                    "only_tree": [f"{f}:{tree[(f, s)]} -> {s}" for f, s in only_tree[:samples]],
                    "fallback_files": {k: v[:samples] for k, v in sorted(fallbacks.items())}},
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="jsts_import_compare", description=__doc__.splitlines()[0])
    ap.add_argument("repo")
    ap.add_argument("--samples", type=int, default=15)
    ap.add_argument("--json", action="store_true")
    ns = ap.parse_args(argv)
    result = compare(ns.repo, ns.samples)
    if result["files"] and result["tree_parsed_files"] == 0 and result["fallbacks"].get(js_imports.NOT_INSTALLED):
        print(f"НЕ ИСПОЛНЕНО: tree-sitter не установлен — {js_imports.INSTALL_HINT}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2 if ns.json else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
