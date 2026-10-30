"""Процессный CLI добровольного учёта; библиотека engops возвращает данные."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_ops_kit.engops import adoption


def main(argv=None):
    ap = argparse.ArgumentParser(description="Добровольный локальный учёт проектов; без сети")
    sub = ap.add_subparsers(dest="action", required=True)
    for action in ("identity", "consent", "revoke", "status", "preview", "export", "import", "report"):
        p = sub.add_parser(action)
        p.add_argument("root", type=Path)
        if action in ("consent", "revoke"):
            p.add_argument("--owner", action="store_true", help="подтверждаю решение владельца проекта")
        if action in ("preview", "export", "report"):
            p.add_argument("--start", required=True)
            p.add_argument("--end", required=True)
        if action == "export":
            p.add_argument("--output", type=Path, required=True)
        if action == "import":
            p.add_argument("source", type=Path)
            p.add_argument("--relationship", choices=adoption.RELATIONSHIPS, default="unknown")
        if action == "report":
            for flag in ("owned", "external", "project"):
                p.add_argument(f"--{flag}", action="append", type=Path, default=[])
    a = ap.parse_args(argv)
    try:
        if a.action == "identity":
            result = {"project_id": adoption.identity(a.root, create=True), "next": f"сохраните {adoption.IDENTITY} в git; учёт ещё выключен"}
        elif a.action in ("consent", "revoke"):
            result = adoption.consent(a.root, owner=a.owner, revoke=a.action == "revoke")
        elif a.action == "status":
            result = adoption.status(a.root)
        elif a.action == "preview":
            result = adoption.snapshot(a.root, a.start, a.end)
        elif a.action == "export":
            result = adoption.export(a.root, a.start, a.end, a.output)
        elif a.action == "import":
            result = adoption.import_receipt(a.root, a.source, a.relationship)
        else:
            projects = [(p, r) for flag, r in (("owned", "owned"), ("external", "external"), ("project", "unknown"))
                        for p in getattr(a, flag)]
            result = adoption.report(a.root, a.start, a.end, projects)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result.get("errors") else 0
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        print(json.dumps({"error": "учёт не выполнен: проверьте согласие, ID и целостность данных"}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
