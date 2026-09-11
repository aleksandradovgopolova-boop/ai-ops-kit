#!/usr/bin/env python3
"""Детектор структурного дублирования функций (статья CODE-003 конституции, #827).

ЗАЧЕМ. CODE-003 (без дублирования, DRY) была честным долгом: `gate: none`. Здесь долг закрывается
РЕАЛЬНЫМ гейтом-ратчетом (как func-size/module-size): существующие дубли заморожены в baseline,
НОВЫЙ структурный дубль краснеет. Не имитация: сигнатура версионно-стабильна, шум (CLI-`main`,
дандеры, мелочь) отфильтрован — во всём ядре остаётся горстка настоящих групп, а не boilerplate.

СИГНАТУРА. Последовательность ИМЁН ТИПОВ AST-узлов функции (обход `ast.walk`). Идентификаторы,
литералы и имена аргументов игнорируются: две структурно одинаковые функции с разными именами/
константами считаются дублями. Имена типов узлов стабильны между версиями Python — baseline не
плывёт от смены интерпретатора (в отличие от `ast.dump`).

ФИЛЬТР ШУМА. Исключаются `main`/дандеры (намеренный boilerplate точек входа) и функции короче
`MIN_STMTS` операторов: маленькие совпадения не являются долгом дублирования.

Витрина read-only: читает код, ничего не пишет (кроме `--write-baseline`).
ЗАПУСК: python3 -m ai_ops_kit.devtools.code_duplication [--write-baseline]
"""
from __future__ import annotations

import ast
import hashlib
import sys
from pathlib import Path

import yaml

KIT = Path(__file__).resolve().parents[2]
SCAN_ROOT = KIT / "ai_ops_kit"
BASELINE = KIT / "packages" / "code-duplication-baseline.yaml"

MIN_STMTS = 10
_SKIP_NAMES = {"main", "__init__", "__repr__", "__eq__", "__hash__", "__str__"}


def _signature(fn: ast.AST) -> tuple:
    """Версионно-стабильная структурная подпись: имена типов узлов при обходе."""
    return tuple(type(n).__name__ for n in ast.walk(fn))


def _stmt_count(fn: ast.AST) -> int:
    return sum(1 for n in ast.walk(fn) if isinstance(n, ast.stmt))


def _iter_functions(root: Path):
    for p in sorted(root.rglob("*.py")):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        except SyntaxError:
            continue
        try:
            rel = p.relative_to(KIT).as_posix()     # реальный скан: пути вида ai_ops_kit/...
        except ValueError:
            rel = p.relative_to(root).as_posix()     # скан вне репозитория (tmp в тестах)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in _SKIP_NAMES:
                    continue
                if _stmt_count(node) < MIN_STMTS:
                    continue
                yield rel, node


def duplicate_groups(root: Path = SCAN_ROOT) -> list[dict]:
    """Группы структурно-одинаковых функций (размер группы > 1). -> [{key, members}] отсортировано."""
    by_sig: dict[tuple, list[str]] = {}
    for rel, node in _iter_functions(root):
        by_sig.setdefault(_signature(node), []).append(f"{rel}::{node.name}")
    groups = []
    for members in by_sig.values():
        if len(members) > 1:
            uniq = sorted(set(members))
            if len(uniq) > 1:                       # два вхождения одного имени (перегрузка в TYPE_CHECKING) — не дубль
                groups.append({"key": _group_key(uniq), "members": uniq})
    return sorted(groups, key=lambda g: g["key"])


def _group_key(members: list[str]) -> str:
    """Стабильный ключ группы: sha256 от отсортированных членов (relpath::name). От номеров строк не зависит."""
    return hashlib.sha256("\n".join(sorted(members)).encode("utf-8")).hexdigest()[:16]


def load_baseline() -> set[str]:
    if not BASELINE.is_file():
        return set()
    doc = yaml.safe_load(BASELINE.read_text(encoding="utf-8")) or {}
    return {g["key"] for g in (doc.get("groups") or [])}


def new_groups(root: Path = SCAN_ROOT) -> list[dict]:
    """Группы, которых НЕТ в baseline — новый дубль (краснеет)."""
    base = load_baseline()
    return [g for g in duplicate_groups(root) if g["key"] not in base]


def stale_baseline_keys(root: Path = SCAN_ROOT) -> set[str]:
    """Ключи baseline, которых больше нет в коде (ратчет вниз: дубль убрали — обнови baseline)."""
    return load_baseline() - {g["key"] for g in duplicate_groups(root)}


def render_baseline() -> str:
    groups = duplicate_groups()
    lines = [
        "# code-duplication-baseline.yaml — заморозка существующих структурных дублей функций (#827).",
        "#",
        "# Ратчет CODE-003 (DRY): перечисленные группы дублей ЗАМОРОЖЕНЫ (известный долг), НОВАЯ группа",
        "# краснит tests/contracts/test_code_duplication.py. Убрали дубль — удалите его группу отсюда",
        "# (ратчет ходит вниз). Генерируется: python3 -m ai_ops_kit.devtools.code_duplication --write-baseline.",
        "schema_version: 1",
        "kind: code-duplication-ratchet",
        f"scan_root: ai_ops_kit",
        f"min_stmts: {MIN_STMTS}",
        "groups:",
    ]
    for g in groups:
        lines.append(f"  - key: {g['key']}")
        lines.append(f"    members:")
        for m in g["members"]:
            lines.append(f"      - {m}")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--write-baseline" in argv:
        BASELINE.write_text(render_baseline(), encoding="utf-8")
        print(f"OK: baseline записан ({len(duplicate_groups())} групп)")
        return 0
    new = new_groups()
    total = duplicate_groups()
    stale = stale_baseline_keys()
    print(f"структурных групп дублей: {len(total)}; новых сверх baseline: {len(new)}; "
          f"устаревших записей baseline: {len(stale)}")
    for g in new:
        print("  НОВЫЙ дубль:", ", ".join(g["members"]))
    return 1 if new else 0


if __name__ == "__main__":
    raise SystemExit(main())
