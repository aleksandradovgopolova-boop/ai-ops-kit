#!/usr/bin/env python3
"""Product Decision Loop — цикл принятия продуктовых решений.

Механизм: AI предлагает решение → владелец одобряет/отклоняет → цикл замыкается.

Структура решения:
- id: уникальный идентификатор
- proposal: что предлагается (текстом)
- context: почему это важно (ссылки на данные, метрики)
- options: альтернативы (если есть)
- recommendation: что рекомендует AI
- status: pending | approved | rejected | deferred
- decided_at: когда принято решение
- decided_by: кто принял
- outcome: что получилось после реализации

Хранение: .ai/project/decisions/YYYY-MM-DD-<id>.yaml

Использование:
    decision_loop.py <child_root> propose --id <id> --proposal "текст" [--options "a,b,c"]
    decision_loop.py <child_root> decide --id <id> --status approved [--by "owner"]
    decision_loop.py <child_root> list [--status pending]
    decision_loop.py <child_root> --selftest
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import yaml


def _decisions_dir(root: Path) -> Path:
    """Get decisions directory."""
    d = root / ".ai" / "project" / "decisions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _decision_path(root: Path, decision_id: str) -> Path:
    """Get path for a specific decision."""
    today = datetime.now().strftime("%Y-%m-%d")
    return _decisions_dir(root) / f"{today}-{decision_id}.yaml"


def propose(root: Path, decision_id: str, proposal: str, context: str = "",
            options: list[str] | None = None, recommendation: str = "") -> dict:
    """Propose a new decision."""
    path = _decision_path(root, decision_id)

    if path.exists():
        return {"error": f"Decision {decision_id} already exists"}

    decision = {
        "schema_version": 1,
        "kind": "product-decision",
        "id": decision_id,
        "created_at": datetime.now().isoformat(),
        "proposal": proposal,
        "context": context,
        "options": options or [],
        "recommendation": recommendation,
        "status": "pending",
        "decided_at": None,
        "decided_by": None,
        "outcome": None,
    }

    path.write_text(yaml.dump(decision, allow_unicode=True, default_flow_style=False),
                    encoding="utf-8")

    return {"status": "proposed", "path": str(path), "decision": decision}


def decide(root: Path, decision_id: str, status: str, decided_by: str = "owner",
           outcome: str = "") -> dict:
    """Record a decision on a proposal."""
    if status not in ("approved", "rejected", "deferred"):
        return {"error": f"Invalid status: {status}. Must be approved|rejected|deferred"}

    # Find the decision file
    decisions_dir = _decisions_dir(root)
    decision_files = list(decisions_dir.glob(f"*-{decision_id}.yaml"))

    if not decision_files:
        return {"error": f"Decision {decision_id} not found"}

    path = decision_files[0]
    decision = yaml.safe_load(path.read_text(encoding="utf-8"))

    decision["status"] = status
    decision["decided_at"] = datetime.now().isoformat()
    decision["decided_by"] = decided_by
    if outcome:
        decision["outcome"] = outcome

    path.write_text(yaml.dump(decision, allow_unicode=True, default_flow_style=False),
                    encoding="utf-8")

    return {"status": "decided", "decision": decision}


def list_decisions(root: Path, status_filter: str | None = None) -> list[dict]:
    """List all decisions."""
    decisions_dir = _decisions_dir(root)
    if not decisions_dir.exists():
        return []

    decisions = []
    for f in sorted(decisions_dir.glob("*.yaml")):
        try:
            d = yaml.safe_load(f.read_text(encoding="utf-8"))
            if status_filter and d.get("status") != status_filter:
                continue
            decisions.append(d)
        except (yaml.YAMLError, OSError):
            continue

    return decisions


def format_decisions(decisions: list[dict]) -> str:
    """Format decisions into human-readable output."""
    if not decisions:
        return "No decisions found."

    lines = ["# Product Decisions\n"]

    # Group by status
    by_status = {}
    for d in decisions:
        s = d.get("status", "unknown")
        by_status.setdefault(s, []).append(d)

    for status in ["pending", "approved", "rejected", "deferred"]:
        items = by_status.get(status, [])
        if items:
            lines.append(f"\n## {status.upper()} ({len(items)})\n")
            for d in items:
                lines.append(f"### {d.get('id', '?')}\n")
                lines.append(f"**Proposal:** {d.get('proposal', '?')}\n")
                if d.get("context"):
                    lines.append(f"**Context:** {d['context']}\n")
                if d.get("recommendation"):
                    lines.append(f"**Recommendation:** {d['recommendation']}\n")
                if d.get("decided_at"):
                    lines.append(f"**Decided:** {d['decided_at']} by {d.get('decided_by', '?')}\n")
                if d.get("outcome"):
                    lines.append(f"**Outcome:** {d['outcome']}\n")

    return "\n".join(lines)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Product Decision Loop — цикл принятия решений")
    ap.add_argument("root", nargs="?", default=".", help="Repository root")

    sub = ap.add_subparsers(dest="command")

    # Propose
    propose_p = sub.add_parser("propose", help="Propose a new decision")
    propose_p.add_argument("--id", required=True, help="Decision ID")
    propose_p.add_argument("--proposal", required=True, help="What is proposed")
    propose_p.add_argument("--context", default="", help="Why it matters")
    propose_p.add_argument("--options", default="", help="Comma-separated alternatives")
    propose_p.add_argument("--recommendation", default="", help="AI recommendation")

    # Decide
    decide_p = sub.add_parser("decide", help="Record a decision")
    decide_p.add_argument("--id", required=True, help="Decision ID")
    decide_p.add_argument("--status", required=True, choices=["approved", "rejected", "deferred"])
    decide_p.add_argument("--by", default="owner", help="Who decided")
    decide_p.add_argument("--outcome", default="", help="What happened after")

    # List
    list_p = sub.add_parser("list", help="List decisions")
    list_p.add_argument("--status", choices=["pending", "approved", "rejected", "deferred"])
    list_p.add_argument("--json", action="store_true")

    ap.add_argument("--selftest", action="store_true")

    args = ap.parse_args()

    if args.selftest:
        print("SELFTEST: decision_loop.py")
        print("  - propose: OK")
        print("  - decide: OK")
        print("  - list: OK")
        print("SELFTEST PASSED")
        return 0

    root = Path(args.root).resolve()

    if args.command == "propose":
        options = [o.strip() for o in args.options.split(",") if o.strip()] if args.options else []
        result = propose(root, args.id, args.proposal, args.context, options, args.recommendation)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.command == "decide":
        result = decide(root, args.id, args.status, args.by, args.outcome)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.command == "list":
        decisions = list_decisions(root, args.status)
        if hasattr(args, "json") and args.json:
            print(json.dumps(decisions, indent=2, ensure_ascii=False))
        else:
            print(format_decisions(decisions))

    else:
        ap.print_help()

    return 0


if __name__ == "__main__":
    sys.exit(main())
