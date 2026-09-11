#!/usr/bin/env python3
"""CLI-обёртка сбора evidence: строит broker (engine) + зовёт collect (gates) — в точке входа (K1).

F-03/K1: проводка `engine.tool_broker` жила в `main()` самого `gates/evidence_collector.py` через
`__import__` — ребро gates->engine, спрятанное от анализатора слоёв. Библиотечный `collect()` давно
принимает broker ПАРАМЕТРОМ (DI); CLI же, который этот broker СТРОИТ, — концерн entrypoints, а не
гейта. Поэтому он переехал сюда: `devtools` (слой entrypoints) вправе импортировать `engine`
статически, и гейт снова чист — gates больше не зависит от engine ни статически, ни динамически.

Использование:
  python3 -m ai_ops_kit.devtools.evidence_collect_cli collect [root] [--policy-level execution]
      [--changed file1 file2] [--json]
"""
from __future__ import annotations

import argparse
import json
import sys

from ai_ops_kit.engine import tool_broker
from ai_ops_kit.gates import evidence_collector
from ai_ops_kit.shared import project_detector


def main(argv):
    ap = argparse.ArgumentParser(prog="evidence_collect_cli.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("root", nargs="?", default=".")
    c.add_argument("--policy-level", default="execution")
    c.add_argument("--changed", nargs="*", default=None, help="changed files for progressive verification")
    c.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "collect":
        profile = project_detector.detect(a.root)
        policy = tool_broker.Policy(level=a.policy_level)
        r = evidence_collector.collect(profile, a.root, policy, changed_files=a.changed, broker=tool_broker)
        if a.json:
            print(json.dumps(r, ensure_ascii=False, indent=2))
        else:
            import yaml
            print(yaml.safe_dump(r, allow_unicode=True, sort_keys=False))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
