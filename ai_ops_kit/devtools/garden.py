#!/usr/bin/env python3
"""Садовник кита: единый read-only отчёт «что лишнее / на консолидацию» (#1405).

ЗАЧЕМ. Кит хорошо наращивает (правила, проверки, агенты), но плохо УДАЛЯЕТ — через год это
идеальное соответствие стандартам при медленной полезной работе. Садовник собирает в ОДИН взгляд
владельца уже существующие сигналы «это можно убрать/свести», чтобы уборка была видимой задачей,
а не случайной находкой.

ЧТО ЭТО НЕ. Не новый детектор и НЕ гейт. Это КОМПОЗИЦИЯ уже построенных сигналов, и она СОВЕТУЕТ,
не блокирует: блокирующая проверка «удали лишнее» была бы ростом вширь — ровно тем, против чего
направлено #1405 и независимое ревью. Поэтому `main` всегда возвращает 0 (это отчёт, не ворота).

ЧТО СОБИРАЕТСЯ (пока из переиспользуемых сигналов):
  * `stale_duplicate_baseline_keys` — ключи базы дублей, которых в коде уже нет: дубль убрали, базу
    можно сократить (`code_duplication.stale_baseline_keys`);
  * `dishonest_gate_rows` — статьи, чья метка обещает дочке гейт, который её не видит
    (`arch_gate_reconciliation.dishonest_rows`): метку надо честно поправить/свести;
  * `duplicate_group_count` — сколько структурных дублей функций всего (контекст, не призыв удалять
    заморожённое базой).

ЧЕГО ПОКА НЕТ (честный долг #1405): дормантные (built≠wired) модули живут логикой в
`tests/contracts/test_dormant_inventory.py`; их вынос в переиспользуемый детектор и подключение сюда —
отдельный срез. Дубли skills/workflows, неиспользуемые агенты и устаревшие доки — тоже следующие
сигналы. Садовник расширяется композицией, не переписыванием.

Запуск:  python3 -m ai_ops_kit.devtools.garden [--json]
"""
from __future__ import annotations

import argparse
import json
import sys


def collect() -> dict:
    """Собрать отчёт уборки из существующих сигналов. Read-only: ничего не пишет."""
    from ai_ops_kit.devtools import arch_gate_reconciliation as recon
    from ai_ops_kit.devtools import code_duplication as dup

    return {
        "schema_version": 1,
        "kind": "kit-garden-report",
        "stale_duplicate_baseline_keys": sorted(dup.stale_baseline_keys()),
        "dishonest_gate_rows": [r.get("id") for r in recon.dishonest_rows()],
        "duplicate_group_count": len(dup.duplicate_groups()),
    }


def _candidate_count(report: dict) -> int:
    """Сколько реальных кандидатов на уборку (не контекстных счётчиков)."""
    return len(report["stale_duplicate_baseline_keys"]) + len(report["dishonest_gate_rows"])


def render(report: dict) -> str:
    lines = ["Садовник кита — кандидаты на уборку/консолидацию (отчёт, не гейт):"]
    stale = report["stale_duplicate_baseline_keys"]
    dishonest = report["dishonest_gate_rows"]
    if stale:
        lines.append(f"  база дублей сократилась — убрать {len(stale)} устаревших ключ(а/ей): "
                     + ", ".join(stale))
    if dishonest:
        lines.append(f"  нечестные метки гейтов ({len(dishonest)}) — поправить/свести: "
                     + ", ".join(dishonest))
    lines.append(f"  (контекст: всего структурных дублей функций — {report['duplicate_group_count']})")
    if _candidate_count(report) == 0:
        lines.append("  уборочных кандидатов нет — сад чист.")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="garden.py", description="Отчёт уборки кита (read-only).")
    ap.add_argument("--json", action="store_true", help="машиночитаемый вывод")
    a = ap.parse_args(argv)
    report = collect()
    print(json.dumps(report, ensure_ascii=False, indent=2) if a.json else render(report))
    return 0  # отчёт, не ворота: всегда 0


if __name__ == "__main__":
    sys.exit(main())
