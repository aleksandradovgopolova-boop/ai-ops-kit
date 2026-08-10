#!/usr/bin/env python3
"""Python-совместимость: PEP 604 union-аннотации без future-import ломают <3.10 (v2.69).

finding квалификационного прогона (self-audit): tools/generate_artifacts.py использовал
`str | None` в аннотации функции. На Python 3.9 (дефолт macOS CommandLineTools) аннотации
вычисляются при импорте -> TypeError, и ВЕСЬ движок не грузился (ai_ops_run -> workitem ->
run_report -> generate_artifacts). Кит заявляет широкую переносимость и ставится в child с
любым python, поэтому `X | Y` в аннотациях допустим ТОЛЬКО при `from __future__ import
annotations` (PEP 563 — делает аннотации ленивыми строками, безопасно на 3.9+).

Проверка (AST, детерминированно): для каждого .py в tools/validation/installer — если есть
union-аннотация (BinOp `|` в аннотации аргумента/возврата/AnnAssign) БЕЗ future-import ->
ERROR. Так класс «падает на 3.9» ловится в CI, а не пользователем на Mac.

Использование:  validate_python_compat.py [--json] | --selftest
Возврат 0 — совместимо, 1 — есть нарушение.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
            Path(__file__).resolve().parents[1])
# v3.33.2: добавлены ai_ops_kit (после переезда 3.31.0 РЕАЛЬНЫЙ код там, а в tools/ — тонкие
# алиасы без аннотаций, то есть guard проверял пустое место) и tests (джоба python39-compat гоняет
# на 3.9 контрактные тесты — значит и они обязаны быть совместимы).
SCAN_DIRS = ["ai_ops_kit", "tools", "validation", "installer", "tests"]

# Модули stdlib, появившиеся ПОЗЖЕ объявленного пола. Импорт такого модуля — не стилистика,
# а гарантированный ModuleNotFoundError у пользователя со старым python. Пол берётся из
# pyproject (requires-python), а не зашивается: проверка обязана следовать декларации.
STDLIB_SINCE = {
    "tomllib": (3, 11),        # поймано живьём: тест дистрибутива уронил джобу 3.9 (v3.33.2)
    "graphlib": (3, 9),
    "zoneinfo": (3, 9),
}


def declared_floor(pkg=PKG):
    """(major, minor) из pyproject requires-python; по умолчанию — 3.9."""
    import re
    text = (pkg / "pyproject.toml").read_text(encoding="utf-8") if (pkg / "pyproject.toml").is_file() else ""
    m = re.search(r'requires-python\s*=\s*"[^0-9]*(\d+)\.(\d+)', text)
    return (int(m.group(1)), int(m.group(2))) if m else (3, 9)


def _too_new_imports(tree, floor):
    """[(строка, модуль, версия)] — импорты stdlib новее пола."""
    out = []
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names = [node.module.split(".")[0]]
        for name in names:
            since = STDLIB_SINCE.get(name)
            if since and since > floor:
                out.append((node.lineno, name, f"{since[0]}.{since[1]}"))
    return out


def _has_future_annotations(tree):
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            if any(a.name == "annotations" for a in node.names):
                return True
    return False


def _union_annotation_lines(tree):
    """Номера строк аннотаций, содержащих union через `|` (ast.BinOp / ast.BitOr)."""
    def has_bitor(ann):
        return any(isinstance(n, ast.BinOp) and isinstance(n.op, ast.BitOr)
                   for n in ast.walk(ann))

    lines = []
    for node in ast.walk(tree):
        anns = []
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = node.args
            for arg in (list(getattr(a, "posonlyargs", [])) + list(a.args) + list(a.kwonlyargs)):
                if arg.annotation:
                    anns.append(arg.annotation)
            if a.vararg and a.vararg.annotation:
                anns.append(a.vararg.annotation)
            if a.kwarg and a.kwarg.annotation:
                anns.append(a.kwarg.annotation)
            if node.returns:
                anns.append(node.returns)
        elif isinstance(node, ast.AnnAssign) and node.annotation:
            anns.append(node.annotation)
        for ann in anns:
            if has_bitor(ann):
                lines.append(ann.lineno)
    return sorted(set(lines))


def check_source(src, floor=None):
    """-> список номеров строк с проблемными union-аннотациями (пусто = ок).

    Импорты stdlib новее пола проверяет check_imports: отдельная функция, потому что
    future-import их не спасает — модуля на старом python просто нет.
    """
    tree = ast.parse(src)
    if _has_future_annotations(tree):
        return []
    return _union_annotation_lines(tree)


def check_imports(src, floor):
    """-> [(строка, модуль, версия)] импортов stdlib, которых на объявленном поле нет."""
    return _too_new_imports(ast.parse(src), floor)


def scan(root):
    errors = []
    floor = declared_floor(root)
    for d in SCAN_DIRS:
        base = root / d
        if not base.exists():
            continue
        for p in sorted(base.rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            src = p.read_text(encoding="utf-8")
            for ln in check_source(src):
                errors.append(f"{p.relative_to(root)}:{ln}: union-аннотация `X | Y` без "
                              f"`from __future__ import annotations` — сломает Python <3.10")
            for ln, mod, since in check_imports(src, floor):
                errors.append(f"{p.relative_to(root)}:{ln}: `{mod}` появился в stdlib с {since}, "
                              f"а объявленный пол — {floor[0]}.{floor[1]} -> ModuleNotFoundError")
    return errors


def run(as_json=False):
    errors = scan(PKG)
    if as_json:
        print(json.dumps({"schema_version": 1, "kind": "python-compat", "errors": errors},
                         ensure_ascii=False, indent=2))
    elif errors:
        print(f"PYTHON-COMPAT: {len(errors)} нарушений (сломают Python <3.10):")
        for e in errors:
            print(f"  - {e}")
    else:
        print("PYTHON-COMPAT-OK: union-аннотации под future-import, импорты stdlib не новее пола "
              f"{declared_floor(PKG)[0]}.{declared_floor(PKG)[1]}.")
    return 1 if errors else 0


def main(argv):
    ap = argparse.ArgumentParser(prog="validate_python_compat.py")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    return run(as_json=a.json)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
