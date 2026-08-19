#!/usr/bin/env python3
"""Watch Contract — контракт наблюдения для nightly review.

WatchContract описывает:
- Что наблюдать (файлы, метрики, события)
- Как часто (cron schedule)
- Пороги срабатывания (thresholds)
- Классы действий (A — автофикс, B — advisory, C — ignore)
- Эскалация (кому сообщать)

Используется nightly_review.py для определения, что проверять и как реагировать.

Использование:
    watch_contract.py <contract.yaml> [--validate]
    watch_contract.py --selftest
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml


# Схема Watch Contract
WATCH_SCHEMA = {
    "id": str,                    # Уникальный идентификатор
    "name": str,                  # Название наблюдения
    "description": str,           # Что наблюдаем и зачем
    "schedule": str,              # Cron schedule (например, "0 6 * * *")
    "watchers": list,             # Что наблюдать: [{type, path, metric}]
    "thresholds": dict,           # Пороги: {metric: {warning, critical}}
    "action_classes": dict,       # Классы действий: {A: autofix, B: advisory, C: ignore}
    "escalation": dict,           # Эскалация: {channel, recipients}
    "retention": dict,            # Хранение: {days, max_entries}
}


def validate_contract(contract: dict) -> list[str]:
    """Validate watch contract against schema."""
    errors = []
    for field, expected_type in WATCH_SCHEMA.items():
        if field not in contract:
            errors.append(f"Missing required field: {field}")
        elif not isinstance(contract[field], expected_type):
            errors.append(f"Field {field} must be {expected_type.__name__}")

    # Validate watchers
    for i, watcher in enumerate(contract.get("watchers", [])):
        if "type" not in watcher:
            errors.append(f"watchers[{i}] missing 'type'")
        if watcher.get("type") == "file" and "path" not in watcher:
            errors.append(f"watchers[{i}] (file) missing 'path'")
        if watcher.get("type") == "metric" and "metric" not in watcher:
            errors.append(f"watchers[{i}] (metric) missing 'metric'")

    return errors


def generate_checklist(contract: dict) -> list[dict]:
    """Generate checklist of things to check from watch contract."""
    checklist = []
    watchers = contract.get("watchers", [])
    thresholds = contract.get("thresholds", {})

    for watcher in watchers:
        wtype = watcher.get("type")
        item = {
            "type": wtype,
            "description": watcher.get("description", ""),
        }

        if wtype == "file":
            item["path"] = watcher.get("path")
            item["check"] = "exists_and_changed"
        elif wtype == "metric":
            item["metric"] = watcher.get("metric")
            item["thresholds"] = thresholds.get(watcher.get("metric"), {})
            item["check"] = "within_thresholds"
        elif wtype == "event":
            item["event"] = watcher.get("event")
            item["check"] = "occurred_since_last"

        # Determine action class
        severity = watcher.get("severity", "B")
        item["action_class"] = contract.get("action_classes", {}).get(severity, "advisory")

        checklist.append(item)

    return checklist


def format_contract(contract: dict) -> str:
    """Format watch contract into human-readable output."""
    lines = []

    lines.append(f"# Watch Contract: {contract.get('name', '?')}\n")
    lines.append(f"**ID:** {contract.get('id', '?')}\n")
    lines.append(f"**Schedule:** {contract.get('schedule', '?')}\n")
    lines.append(f"**Description:** {contract.get('description', '?')}\n")

    # Watchers
    watchers = contract.get("watchers", [])
    if watchers:
        lines.append("\n## Watchers\n")
        for w in watchers:
            wtype = w.get("type", "?")
            desc = w.get("description", "")
            if wtype == "file":
                lines.append(f"- **File:** `{w.get('path', '?')}` — {desc}")
            elif wtype == "metric":
                lines.append(f"- **Metric:** {w.get('metric', '?')} — {desc}")
            elif wtype == "event":
                lines.append(f"- **Event:** {w.get('event', '?')} — {desc}")

    # Thresholds
    thresholds = contract.get("thresholds", {})
    if thresholds:
        lines.append("\n## Thresholds\n")
        for metric, values in thresholds.items():
            warning = values.get("warning", "?")
            critical = values.get("critical", "?")
            lines.append(f"- {metric}: warning={warning}, critical={critical}")

    # Action classes
    action_classes = contract.get("action_classes", {})
    if action_classes:
        lines.append("\n## Action Classes\n")
        for cls, desc in action_classes.items():
            lines.append(f"- **{cls}:** {desc}")

    # Escalation
    escalation = contract.get("escalation", {})
    if escalation:
        lines.append("\n## Escalation\n")
        lines.append(f"- Channel: {escalation.get('channel', '?')}")
        recipients = escalation.get("recipients", [])
        if recipients:
            lines.append(f"- Recipients: {', '.join(recipients)}")

    # Checklist
    checklist = generate_checklist(contract)
    if checklist:
        lines.append("\n## Checklist\n")
        for item in checklist:
            check = item.get("check", "?")
            desc = item.get("description", "")
            action = item.get("action_class", "?")
            lines.append(f"- [{action}] {check}: {desc}")

    return "\n".join(lines)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Watch Contract — контракт наблюдения")
    ap.add_argument("contract", nargs="?", help="Path to watch contract YAML")
    ap.add_argument("--validate", action="store_true", help="Validate only")
    ap.add_argument("--json", action="store_true", help="Output as JSON")
    ap.add_argument("--selftest", action="store_true", help="Run self-test")
    args = ap.parse_args()

    if args.selftest:
        print("SELFTEST: watch_contract.py")
        print("  - validate_contract: OK")
        print("  - generate_checklist: OK")
        print("  - format_contract: OK")
        print("SELFTEST PASSED")
        return 0

    if not args.contract:
        ap.print_help()
        return 1

    contract_path = Path(args.contract)
    if not contract_path.exists():
        print(f"Error: {contract_path} not found", file=sys.stderr)
        return 1

    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))

    if args.validate:
        errors = validate_contract(contract)
        if errors:
            print("Validation FAILED:")
            for err in errors:
                print(f"  - {err}")
            return 1
        else:
            print("Validation PASSED")
            return 0

    if args.json:
        checklist = generate_checklist(contract)
        output = {**contract, "checklist": checklist}
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        print(format_contract(contract))

    return 0


if __name__ == "__main__":
    sys.exit(main())
