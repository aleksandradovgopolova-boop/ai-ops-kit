"""Экспериментальный перенос pending-state без запуска или принятия задач."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import yaml

from ai_ops_kit.lifecycle import session_migration as migration


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("capture", "preview", "apply", "rollback"))
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--snapshot-sha256")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--plan-sha256")
    parser.add_argument("--transaction")
    parser.add_argument("--quiescent-window", action="store_true",
                        help="владелец согласовал остановку старых writers/importers; не определяется автоматически")
    args = parser.parse_args(argv)
    required = {"capture": ("snapshot",), "preview": ("snapshot", "snapshot_sha256", "plan"),
                "apply": ("snapshot", "snapshot_sha256", "plan", "plan_sha256"),
                "rollback": ("transaction", "plan_sha256")}[args.action]
    if not args.quiescent_window or any(getattr(args, key) is None for key in required):
        parser.error("нужны согласованное --quiescent-window и аргументы выбранного действия")
    try:
        if args.action == "capture":
            result = migration.capture(args.project, args.snapshot)
        elif args.action == "preview":
            result = migration.preview(args.project, args.snapshot, args.snapshot_sha256, args.plan)
        elif args.action == "apply":
            result = migration.apply(args.project, args.snapshot, args.snapshot_sha256, args.plan, args.plan_sha256)
        else:
            result = migration.rollback(args.project, args.transaction, args.plan_sha256, args.plan)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError, yaml.YAMLError) as exc:
        print(f"AI Ops migration: {exc}. Задачи не приняты и не перезапущены.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
