#!/usr/bin/env python3
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
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

# _bootstrap кладёт корень пакета на путь — чтобы `ai_ops_kit.checks` импортировался и при запуске
# валидатора ПЛОСКИМ именем (`python validate_run_handoff.py …`), и как модуль после установки.
try:
    from ai_ops_kit.validation import _bootstrap  # noqa: F401
except ImportError:
    import _bootstrap  # noqa: F401

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
            Path(__file__).resolve().parents[1])

# Проверяющая логика вынесена ВНИЗ в `checks` (v3.38-приём): её зовут и рантайм
# (engine/run_handoff.build_handoff), и эта CLI-обёртка — без восходящего ребра engine -> validation.
from ai_ops_kit.checks.run_handoff import check  # noqa: E402,F401


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
