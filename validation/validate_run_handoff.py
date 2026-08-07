#!/usr/bin/env python3
from __future__ import annotations
"""Validate RunHandoff (v2.99, эпик Context Engineering, этап 3 — Context Lifecycle и Resume).

Стережёт форму передачи состояния между сессиями:
  1. kind=RunHandoff, есть workitem_id, next_action (следующий безопасный шаг);
  2. verification = {passed:[], failed:[]};
  3. completed/decisions/changed_files/open_questions/known_risks — списки;
  4. decisions[i] (если объект) несёт id и summary;
  5. resume_from_revision — строка (git sha) или null (прогон без коммита).

Использование:
  validate_run_handoff.py <handoff.yaml|.json>
  validate_run_handoff.py --selftest
Возврат 0 — ок, 1 — ошибки.
"""

import json
import sys
from pathlib import Path

import yaml

PKG = Path(__file__).resolve().parents[1]
LIST_FIELDS = ("completed", "decisions", "changed_files", "open_questions", "known_risks")


def check(h):
    errors = []
    if not isinstance(h, dict) or h.get("kind") != "RunHandoff":
        errors.append("kind должен быть 'RunHandoff'")
        return errors
    if not h.get("workitem_id"):
        errors.append("нет workitem_id")
    if not h.get("next_action"):
        errors.append("нет next_action (следующий безопасный шаг обязателен)")
    ver = h.get("verification")
    if not isinstance(ver, dict) or "passed" not in ver or "failed" not in ver:
        errors.append("verification должен быть объектом с passed[] и failed[]")
    elif not isinstance(ver.get("passed"), list) or not isinstance(ver.get("failed"), list):
        errors.append("verification.passed/failed должны быть списками")
    for f in LIST_FIELDS:
        if f in h and not isinstance(h[f], list):
            errors.append(f"{f} должен быть списком")
    for i, d in enumerate(h.get("decisions", []) or []):
        if isinstance(d, dict) and (not d.get("id") or not d.get("summary")):
            errors.append(f"decisions[{i}]: нужны id и summary")
    rev = h.get("resume_from_revision")
    if rev is not None and not isinstance(rev, str):
        errors.append("resume_from_revision должен быть строкой (git sha) или null")
    return errors


def main(argv):
    if not argv:
        print("укажи путь к handoff или --selftest")
        return 1
    path = Path(argv[0])
    if not path.exists():
        print(f"RUN-HANDOFF: файл не найден: {path}")
        return 1
    text = path.read_text(encoding="utf-8")
    h = json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
    errs = check(h)
    if errs:
        print("RUN-HANDOFF: ошибки:")
        for e in errs:
            print(f"  - {e}")
        return 1
    print(f"RUN-HANDOFF-OK: {path.name} — форма передачи состояния соблюдена.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
