#!/usr/bin/env python3
"""Проверка LoopPolicy — v3.3.2 Operational Architecture Backbone.

LoopPolicy (schemas/loop-policy.schema.json) — контракт управляемого цикла. Валидатор:

  1. schema_version=1, kind=LoopPolicy; id формата LP-NNN; loop_type ∈ 6-enum;
  2. trigger/progress_measure/on_stop/escalation непусты; success_conditions/stop_conditions непусты;
  3. ИНВАРИАНТ: budgets несут ХОТЯ БЫ ОДНУ границу (max_iterations|max_tokens|max_cost_usd не-null) —
     unbounded loop запрещён (готовит v3.4: никакой loop без бюджета);
  4. границы бюджета положительны;
  5. согласованность: stop_conditions должны упоминать исчерпание бюджета (loop обязан уметь
     остановиться по границе, а не только по успеху).

Использование:  validate_loop_policy.py <loop-policy.(yaml|json)> [--json] | --selftest
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

import yaml

PKG = Path(__file__).resolve().parents[1]
SCHEMA = PKG / "schemas" / "loop-policy.schema.json"
LOOP_TYPES = {"implementation", "review_fix", "ui_storybook", "research", "product_learning",
              "safe_improvement"}
_ID = re.compile(r"^LP-[0-9]{3,}$")


def _is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def check(data: dict):
    e = []
    if not isinstance(data, dict):
        return ["LoopPolicy не объект"]
    if data.get("schema_version") != 1:
        e.append("schema_version должен быть 1")
    if data.get("kind") != "LoopPolicy":
        e.append("kind должен быть 'LoopPolicy'")
    if not (isinstance(data.get("id"), str) and _ID.match(data["id"])):
        e.append("id должен быть формата LP-NNN")
    if data.get("loop_type") not in LOOP_TYPES:
        e.append(f"loop_type ∉ {sorted(LOOP_TYPES)}")
    for f in ("trigger", "progress_measure", "on_stop", "escalation"):
        if not (isinstance(data.get(f), str) and data[f].strip()):
            e.append(f"{f} обязателен и непуст")
    for f in ("success_conditions", "stop_conditions"):
        v = data.get(f)
        if not (isinstance(v, list) and v and all(isinstance(x, str) for x in v)):
            e.append(f"{f} — непустой список строк")

    b = data.get("budgets")
    if not isinstance(b, dict):
        e.append("budgets обязателен")
    else:
        bounds = [b.get("max_iterations"), b.get("max_tokens"), b.get("max_cost_usd")]
        if all(x is None for x in bounds):
            e.append("budgets: нужна хотя бы одна граница (unbounded loop запрещён)")
        for k in ("max_iterations", "max_tokens"):
            v = b.get(k)
            if v is not None and not (isinstance(v, int) and not isinstance(v, bool) and v >= 1):
                e.append(f"budgets.{k} должен быть целым ≥1 или null")
        c = b.get("max_cost_usd")
        if c is not None and not (_is_num(c) and c >= 0):
            e.append("budgets.max_cost_usd должен быть числом ≥0 или null")

    sc = data.get("stop_conditions") or []
    if isinstance(sc, list) and sc and not any(
            ("бюджет" in s.lower() or "budget" in s.lower() or "исчерп" in s.lower()) for s in sc):
        e.append("stop_conditions должны включать исчерпание бюджета (остановка по границе, не только успех)")
    return e


def _load(p: Path):
    t = p.read_text(encoding="utf-8")
    return yaml.safe_load(t) if p.suffix in (".yaml", ".yml") else json.loads(t)


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 1
    errors = check(_load(Path(args[0])))
    if "--json" in argv:
        print(json.dumps({"errors": errors}, ensure_ascii=False, indent=2))
    elif errors:
        print("LOOP-POLICY: ошибки:")
        for x in errors:
            print(f"  - {x}")
    else:
        print("LOOP-POLICY-OK: структура валидна.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
