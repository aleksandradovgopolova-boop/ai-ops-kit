#!/usr/bin/env python3
"""Ратчет структурных дублей функций САМОГО кита (статья CODE-003, #827).

Ядро — подпись, группы, ключи, база — живёт в поставляемом `ai_ops_kit.checks.code_duplication`
(#1512): им же проверяется проект и онбординг. Здесь — только привязка к дереву кита: что
сканировать (`ai_ops_kit/`), где база (`packages/code-duplication-baseline.yaml`) и её заголовок.
Существующие дубли заморожены, НОВАЯ группа краснит `tests/contracts/test_code_duplication.py`.

ЗАПУСК: python3 -m ai_ops_kit.devtools.code_duplication [--write-baseline]
"""
from __future__ import annotations

import sys
from pathlib import Path

from ai_ops_kit.checks import code_duplication as core

KIT = Path(__file__).resolve().parents[2]
SCAN_ROOT = KIT / "ai_ops_kit"
BASELINE = KIT / "packages" / "code-duplication-baseline.yaml"
MIN_STMTS = core.MIN_STMTS
HEADER = (
    "code-duplication-baseline.yaml — заморозка существующих структурных дублей функций (#827).",
    "",
    "Ратчет CODE-003 (DRY): перечисленные группы дублей ЗАМОРОЖЕНЫ (известный долг), НОВАЯ группа",
    "краснит tests/contracts/test_code_duplication.py. Убрали дубль — удалите его группу отсюда",
    "(ратчет ходит вниз). Генерируется: python3 -m ai_ops_kit.devtools.code_duplication --write-baseline.",
)


def duplicate_groups(root: Path = SCAN_ROOT) -> list[dict]:
    """Группы дублей дерева; пути — от корня кита (`ai_ops_kit/...`), как в базе."""
    root = Path(root)
    rel_to = KIT if root.resolve().is_relative_to(KIT) else root
    return [{"key": g["key"], "members": g["members"]}
            for g in core.duplicate_groups(sorted(root.rglob("*.py")), rel_to)]


def load_baseline() -> set[str]:
    return core.load_baseline(BASELINE) or set()


def new_groups(root: Path = SCAN_ROOT) -> list[dict]:
    """Группы, которых НЕТ в базе — новый дубль (краснеет)."""
    return core.compare(duplicate_groups(root), load_baseline())["new"]


def stale_baseline_keys(root: Path = SCAN_ROOT) -> set[str]:
    """Ключи базы, которых больше нет в коде (ратчет вниз: дубль убрали — обнови базу)."""
    return set(core.compare(duplicate_groups(root), load_baseline())["stale"])


def render_baseline() -> str:
    return core.render_baseline(duplicate_groups(), "ai_ops_kit", HEADER)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--write-baseline" in argv:
        BASELINE.write_text(render_baseline(), encoding="utf-8")
        print(f"OK: baseline записан ({len(duplicate_groups())} групп)")
        return 0
    new, total, stale = new_groups(), duplicate_groups(), stale_baseline_keys()
    print(f"структурных групп дублей: {len(total)}; новых сверх baseline: {len(new)}; "
          f"устаревших записей baseline: {len(stale)}")
    for g in new:
        print("  НОВЫЙ дубль:", ", ".join(g["members"]))
    return 1 if new else 0


if __name__ == "__main__":
    raise SystemExit(main())
