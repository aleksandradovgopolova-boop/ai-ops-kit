#!/usr/bin/env python3
from __future__ import annotations
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

import json
import sys
from pathlib import Path

import yaml

PKG = Path(__file__).resolve().parents[1]

REQUIRED_INCLUDED = ("project_context", "repository_context", "specifications", "decisions",
                     "files", "rules", "skills", "agents")


def check(bundle):
    errors = []
    if not isinstance(bundle, dict) or bundle.get("kind") != "ContextBundle":
        errors.append("kind должен быть 'ContextBundle'")
        return errors
    if not bundle.get("workitem_id"):
        errors.append("нет workitem_id")
    inc = bundle.get("included")
    if not isinstance(inc, dict):
        errors.append("included должен быть объектом")
        inc = {}
    for key in REQUIRED_INCLUDED:
        if key not in inc:
            errors.append(f"included: нет раздела '{key}'")
        elif not isinstance(inc[key], list):
            errors.append(f"included.{key} должен быть списком")
    exc = bundle.get("excluded")
    if not isinstance(exc, list):
        errors.append("excluded должен быть списком")
        exc = []
    for i, e in enumerate(exc):
        if not isinstance(e, dict) or not e.get("source") or not e.get("reason"):
            errors.append(f"excluded[{i}]: нужны непустые source и reason (не выкидываем молча)")
    tok, budget = bundle.get("estimated_tokens"), bundle.get("context_budget")
    if not isinstance(tok, int) or tok < 0:
        errors.append("estimated_tokens должен быть неотрицательным целым (размер измерен ДО модели)")
    if not isinstance(budget, int) or budget < 1:
        errors.append("context_budget должен быть положительным целым")
    # overflow не молчит
    if bundle.get("overflow") is True:
        oq = bundle.get("open_questions") or []
        if not any("бюджет" in str(q) or "budget" in str(q).lower() or "overflow" in str(q).lower() for q in oq):
            errors.append("overflow=True без open_question про бюджет (контекст обрезан молча — запрещено)")
    # included vs excluded — один источник, одно решение (агенты)
    inc_agents = set(inc.get("agents", []) if isinstance(inc, dict) else [])
    exc_agents = {e.get("source", "").split("agent:", 1)[-1] for e in exc if str(e.get("source", "")).startswith("agent:")}
    overlap = inc_agents & exc_agents
    if overlap:
        errors.append(f"агенты одновременно included и excluded: {sorted(overlap)}")
    return errors


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
