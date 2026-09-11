#!/usr/bin/env python3
"""CLI-обёртка Context Compiler'а (точка входа, слой `entrypoints`).

Библиотечный ai_ops_kit/context/context_compiler.py не строит RunPlan сам — он его ПОТРЕБЛЯЕТ,
чтобы context не зависел от engine (K2-развязка слоёв). Эта обёртка живёт в entrypoints, где
engine импортировать можно: она берёт построитель плана `run_plan.build_plan` и инъецирует его в
compile_bundle. Так проводка «сигналы -> план -> контекст» собрана в точке входа, а не спрятана
динамическим импортом внутри слоя capabilities.

Использование:
  python -m ai_ops_kit.devtools.context_compile_cli <child_root> --signals '{...}' [--feature name] [--json]
Возврат 0 — ок, 1 — ошибка (или overflow при --strict).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ai_ops_kit.context import context_compiler
from ai_ops_kit.engine.run_plan import build_plan


def main(argv):
    ap = argparse.ArgumentParser(prog="context_compile_cli.py")
    ap.add_argument("child_root", nargs="?", default=".")
    ap.add_argument("--signals", default="{}")
    ap.add_argument("--feature")
    ap.add_argument("--budget", type=int)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true", help="ненулевой код при overflow")
    a = ap.parse_args(argv)
    signals = json.loads(a.signals)
    if a.feature:
        signals["feature"] = a.feature
    b = context_compiler.compile_bundle(signals, Path(a.child_root), context_budget=a.budget,
                                        build_plan=build_plan)
    if a.json:
        print(json.dumps(b, ensure_ascii=False, indent=2))
    else:
        inc = b["included"]
        print(f"CONTEXT-BUNDLE {b['workitem_id']} ({b['base_workflow']}) · ~{b['estimated_tokens']}/"
              f"{b['context_budget']} ток.{' ⚠OVERFLOW' if b['overflow'] else ''}")
        print(f"  агенты ({len(inc['agents'])}): {', '.join(inc['agents']) or '—'}")
        print(f"  правила: {', '.join(inc['rules']) or '—'} · skills: {', '.join(inc['skills']) or '—'}")
        print(f"  стек: {', '.join(inc['repository_context']) or 'не определён'}")
        print(f"  исключено источников: {len(b['excluded'])}")
        for q in b["open_questions"]:
            print(f"  ? {q}")
    return 1 if (a.strict and b["overflow"]) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
