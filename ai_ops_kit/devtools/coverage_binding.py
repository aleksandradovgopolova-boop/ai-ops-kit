"""Привязка замера покрытия к исходникам для CRAP (#1387): доверенный runner в CI.

`snapshot` — отпечаток исходников, тестов и настроек ДО тестов. `bind` — после тестов и
генерации coverage.json: сверяет отпечаток заново и пишет `coverage-binding.json` в формате,
который принимает `crap_score --coverage-binding`. Изменились входы за время прогона — привязка
не пишется (код 2): покрытие старого кода нельзя выдать за покрытие нового.

Итог `passed` пишется только при коде возврата тестов 0; иначе `failed`, и `crap_score` такую
привязку не примет. Сам модуль тестов не запускает и покрытие не измеряет.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from pathlib import Path

from ai_ops_kit.devtools.crap_score import measurement_inputs


def snapshot(root: Path, out: Path) -> None:
    out.write_text(json.dumps(measurement_inputs(root), sort_keys=True) + "\n", encoding="utf-8")


def bind(root: Path, inputs: Path, report: Path, tests_exit: int, scope: str, command: list[str]) -> dict:
    before = json.loads(inputs.read_text(encoding="utf-8"))
    after = measurement_inputs(root)
    if before != after:
        changed = sorted(set(before) ^ set(after) | {k for k in before if after.get(k) != before[k]})
        raise ValueError(f"входы изменились за время замера: {', '.join(changed[:5])}")
    if not scope.strip() or not command:
        raise ValueError("нужны scope и command")
    return {"schema_version": 1, "outcome": "passed" if tests_exit == 0 else "failed",
            "tests_exit_code": tests_exit, "scope": scope, "command": command,
            "python": platform.python_version(),
            "report_sha256": hashlib.sha256(report.read_bytes()).hexdigest(), "inputs_sha256": after}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="action", required=True)
    snap = sub.add_parser("snapshot")
    snap.add_argument("--out", type=Path, required=True)
    joined = sub.add_parser("bind")
    joined.add_argument("--inputs", type=Path, required=True)
    joined.add_argument("--report", type=Path, required=True)
    joined.add_argument("--tests-exit", type=int, required=True)
    joined.add_argument("--scope", required=True)
    joined.add_argument("--out", type=Path, required=True)
    joined.add_argument("command", nargs=argparse.REMAINDER, help="argv тестового прогона после --")
    for command in (snap, joined):
        command.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    try:
        if args.action == "snapshot":
            snapshot(args.root, args.out)
            return 0
        argv_run = args.command[1:] if args.command[:1] == ["--"] else args.command
        result = bind(args.root, args.inputs, args.report, args.tests_exit, args.scope, argv_run)
        args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"coverage binding: {result['outcome']}")
        return 0
    except (OSError, ValueError) as exc:
        print(f"ERROR coverage-binding: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
