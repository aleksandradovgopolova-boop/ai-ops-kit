#!/usr/bin/env python3
"""CLI-обёртка ревью ветки (точка входа, слой `entrypoints`).

Библиотечный review() живёт в ai_ops_kit/engine/review_branch.py: он запускает движковые
ревью-гейты над worktree ветки и выносит вердикт готовности к merge. Эта обёртка печатает
результат человеку. Реальный ревьюер подставляется через `ai-ops review` (там есть провайдер);
здесь reviewer_proposer=None -> verdict=needs-reviewer.

Использование:
  python -m ai_ops_kit.devtools.branch_review_cli <child_root> <wid> [--base <ветка>] [--json]
Возврат 0 — ветка готова к merge, 1 — вердикт не подтверждает готовность.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ai_ops_kit.engine import review_branch


def main(argv):
    ap = argparse.ArgumentParser(prog="branch_review_cli.py")
    ap.add_argument("child_root")
    ap.add_argument("wid")
    ap.add_argument("--base", default=None,
                    help="база сравнения; не задана -> auto: текущая ветка/upstream/remote-default")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    # без живого провайдера ревьюер не подставляется (CLI-обёртка ai-ops даёт провайдер);
    # печатаем, что ревьюируемо и какова ветка (verdict=needs-reviewer).
    rep = review_branch.review(Path(a.child_root), a.wid, reviewer_proposer=None, base=a.base)
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print(f"BRANCH-REVIEW {a.wid}: verdict={rep['verdict']} · ревьюируемо={rep.get('reviewable')} "
              f"· ready_for_merge={(rep.get('readiness') or {}).get('ready_for_merge')}")
        if rep.get("note"):
            print(f"  · {rep['note']}")
    # v2.121 (P1.3): needs-reviewer -> НЕ ok. Вердикт не вынесен = готовность не подтверждена.
    return 0 if (rep.get("readiness") or {}).get("ready_for_merge") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
