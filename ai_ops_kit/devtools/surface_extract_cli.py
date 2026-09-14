#!/usr/bin/env python3
"""CLI-обёртка извлечения поверхностей продукта (точка входа, слой `entrypoints`).

Библиотечное извлечение живёт в `ai_ops_kit/checks/surface_extraction.py` (слой primitives, чистый
read-only разбор AST). Эта обёртка проводит его в контур: печатает извлечённые поверхности человеку/в
JSON. Судья охвата (W3) будет звать `extract_surfaces` напрямую как библиотеку; обёртка нужна для
ручного прогона по дочке и как честный runnable-путь к модулю.

Использование:
  python -m ai_ops_kit.devtools.surface_extract_cli <child_root> [--json]
Возврат 0 — ок (даже если поверхностей ноль: это валидный результат, а не ошибка).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ai_ops_kit.checks import surface_extraction


def main(argv) -> int:
    ap = argparse.ArgumentParser(prog="surface_extract_cli.py")
    ap.add_argument("child_root", nargs="?", default=".")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    surfaces = surface_extraction.extract_surfaces(Path(a.child_root))
    if a.json:
        print(json.dumps({"schema_version": 1, "kind": "surface-extraction-report",
                          "root": a.child_root, "surfaces": surfaces},
                         ensure_ascii=False, indent=2))
    else:
        print(f"SURFACES: извлечено {len(surfaces)} поверхностей из {a.child_root}")
        for s in surfaces:
            print(f"  [{s['confidence']}] {s['kind']:6} {s['ref']}  ({s['extractor']})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
