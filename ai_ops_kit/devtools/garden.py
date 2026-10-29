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
  * `dormant_modules` — неподключённые модули, пути исходников и причины намеренного карантина
    (существующий `capability_inventory.dormant_modules`);
  * `duplicate_group_count` — сколько структурных дублей функций всего (контекст, не призыв удалять
    заморожённое базой).

Структурный инвентарь garden_inventory дополняет композицию: точные копии skills/workflows,
роли без объявленных потребителей, явно retired/supersedes, разные объявления одного id,
проверки с одинаковым контрактом и пробелы owner/retirement. Отчёт называет пути и строки,
но не доказывает произвольную семантику прозы или отсутствие ручного вызова роли.
Неподключённый модуль — кандидат на разбор: карантин нельзя снимать автоматически.

Запуск:  python3 -m ai_ops_kit.devtools.garden [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ai_ops_kit.devtools.garden_inventory import SIGNALS, collect as inventory_signals


def collect() -> dict:
    """Собрать отчёт уборки из существующих сигналов. Read-only: ничего не пишет."""
    from ai_ops_kit.devtools import arch_gate_reconciliation as recon
    from ai_ops_kit.devtools import code_duplication as dup
    from ai_ops_kit.devtools import capability_inventory as inventory

    duplicate_groups = dup.duplicate_groups()
    report = {
        "schema_version": 1,
        "kind": "kit-garden-report",
        "stale_duplicate_baseline_keys": sorted(dup.stale_baseline_keys()),
        "dishonest_gate_rows": [r.get("id") for r in recon.dishonest_rows()],
        "duplicate_group_count": len(duplicate_groups),
        "duplicate_functions": [
            {"key": group["key"], "members": group["members"],
             "sources": [{"path": member.partition("::")[0], "line": 1}
                         for member in group["members"]]}
            for group in duplicate_groups
        ],
        "legacy_sources": {"stale_duplicate_baseline_keys": "packages/code-duplication-baseline.yaml",
                           "dishonest_gate_rows": "standards/architecture/rules.yaml"},
        "dormant_modules": [
            {"module": module, "path": module.replace(".", "/") + ".py",
             "reason": inventory.INTENTIONAL_DORMANT_REASON.get(module)}
            for module in inventory.dormant_modules()
        ],
    }
    report.update(inventory_signals(Path(__file__).resolve().parents[2]))
    return report


def _candidate_count(report: dict) -> int:
    """Сколько реальных кандидатов на уборку (не контекстных счётчиков)."""
    return (len(report["stale_duplicate_baseline_keys"]) + len(report["dishonest_gate_rows"])
            + len(report.get("dormant_modules", []))
            + sum(len(report.get(key, [])) for key in SIGNALS))


def render(report: dict) -> str:
    lines = ["Садовник кита — кандидаты на уборку/консолидацию (отчёт, не гейт):"]
    stale = report["stale_duplicate_baseline_keys"]
    dishonest = report["dishonest_gate_rows"]
    if stale:
        lines.append(f"  база дублей сократилась — убрать {len(stale)} устаревших ключ(а/ей): "
                     + ", ".join(stale))
        lines.append("    " + report.get("legacy_sources", {}).get(
            "stale_duplicate_baseline_keys", "packages/code-duplication-baseline.yaml") + ":1")
    if dishonest:
        lines.append(f"  нечестные метки гейтов ({len(dishonest)}) — поправить/свести: "
                     + ", ".join(dishonest))
        lines.append("    " + report.get("legacy_sources", {}).get(
            "dishonest_gate_rows", "standards/architecture/rules.yaml") + ":1")
    for module in report.get("dormant_modules", []):
        lines.append(f"  неподключённый модуль — проверить назначение: {module['path']}")
        if module["reason"]:
            lines.append(f"    причина сохранения: {module['reason']}")
    labels = {"duplicate_documents": "копии skills/workflows", "unreferenced_agents": "роли без статической ссылки",
              "stale_rules": "явно снятые/заменённые правила", "conflicting_declarations": "разные объявления одного id",
              "duplicate_checks": "проверки с одинаковым контрактом", "retirement_gaps": "нет владельца/условия вывода"}
    for key in SIGNALS:
        for finding in report.get(key, []):
            ident = finding.get("id") or ", ".join(finding.get("ids", []))
            lines.append(f"  {labels[key]}: {ident}")
            for source in finding["sources"]:
                lines.append(f"    {source['path']}:{source['line']}")
            if finding.get("reason"):
                lines.append(f"    {finding['reason']}")
            if finding.get("missing"):
                lines.append("    отсутствует: " + ", ".join(finding["missing"]))
    lines.append(f"  (контекст: всего структурных дублей функций — {report['duplicate_group_count']})")
    for group in report.get("duplicate_functions", []):
        lines.append(f"  группа функций {group['key']} (контекст, не разрешение снять заморозку):")
        lines.extend(f"    {source['path']}:{source['line']}" for source in group["sources"])
    if _candidate_count(report) == 0:
        lines.append("  уборочных кандидатов по проверенным сигналам нет — сад чист в этих границах.")
    lines.extend(f"  предел: {limit}" for limit in report.get("limits", []))
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
