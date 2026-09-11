#!/usr/bin/env python3
"""Validate ContextBundle (v2.97, эпик Context Engineering, этап 1 — Context Compiler).

Стережёт инварианты пакета контекста (structure + честность отбора):
  1. форма по schemas/context-bundle.schema.json (kind, included-разделы, excluded-с-причинами,
     estimated_tokens/context_budget);
  2. у КАЖДОГО исключённого источника есть непустая причина (не «молча выкинули»);
  3. estimated_tokens и context_budget присутствуют и положительны (размер измерен ДО модели);
  4. overflow=True обязан сопровождаться open_question (контекст не обрезан молча);
  5. включённые агенты не пересекаются с исключёнными (один источник — одно решение).

Использование:
  validate_context_bundle.py <bundle.yaml|.json>
  validate_context_bundle.py --selftest
Возврат 0 — ок, 1 — ошибки.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

# _bootstrap кладёт корень пакета на путь — чтобы `ai_ops_kit.checks` импортировался и при запуске
# валидатора ПЛОСКИМ именем, и как модуль после установки.
try:
    from ai_ops_kit.validation import _bootstrap  # noqa: F401
except ImportError:
    import _bootstrap  # noqa: F401

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
            Path(__file__).resolve().parents[1])

# Проверяющая логика вынесена ВНИЗ в `checks` (v3.38-приём): её зовут и рантайм
# (context/context_compiler.compile_bundle), и эта CLI-обёртка — без восходящего ребра
# context -> validation (иначе взаимная пара с validate_context_qualification -> context).
from ai_ops_kit.checks.context_bundle import REQUIRED_INCLUDED, check  # noqa: E402,F401


def main(argv):
    if not argv:
        print("укажи путь к bundle или --selftest")
        return 1
    path = Path(argv[0])
    if not path.exists():
        print(f"CONTEXT-BUNDLE: файл не найден: {path}")
        return 1
    text = path.read_text(encoding="utf-8")
    bundle = json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
    errs = check(bundle)
    if errs:
        print("CONTEXT-BUNDLE: ошибки:")
        for e in errs:
            print(f"  - {e}")
        return 1
    print(f"CONTEXT-BUNDLE-OK: {path.name} — форма и честность отбора соблюдены.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
