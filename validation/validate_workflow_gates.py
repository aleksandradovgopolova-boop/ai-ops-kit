#!/usr/bin/env python3
"""Согласованность workflow ↔ gate (v2.16).

Раньше валидаторы проверяли только существование gate/agent id и обязательные поля,
но не то, что гейт, включённый в workflow.quality_gates, ВООБЩЕ применим к этому
workflow. Так VISUAL/ANALYTICS ссылались на implementation_verification, чьё
applicability их не включало — контракт сам себе противоречил, а CI молчал.

Проверки:
  1. ERROR: гейт в workflow.quality_gates обязан числить этот workflow в
     `applicability` (или applicability=[all]);
  2. ERROR: гейт из quality_gates существует в quality/gates.yaml
     (дублирует часть validate_ai_first_workflows, но здесь — вместе с applicability);
  3. WARN: blocking-гейт, применимый к workflow по applicability, но НЕ включённый
     в его quality_gates — возможный пропуск обязательной проверки (информационно).

Использование:  validate_workflow_gates.py [--json] | --selftest
Возврат 0 — согласовано (возможны WARN), 1 — есть ERROR.
"""

import json
import sys
from pathlib import Path

import yaml

PKG = Path(__file__).resolve().parents[1]


def load():
    gates = yaml.safe_load((PKG / "quality" / "gates.yaml").read_text(encoding="utf-8")).get("gates", {})
    wfs = yaml.safe_load((PKG / "registry" / "workflows.yaml").read_text(encoding="utf-8")).get("workflows", {})
    return gates, wfs


def check(gates: dict, wfs: dict):
    errors, warns = [], []
    for wid, w in wfs.items():
        used = w.get("quality_gates", []) or []
        for gid in used:
            g = gates.get(gid)
            if g is None:
                errors.append(f"{wid}: гейт '{gid}' отсутствует в quality/gates.yaml")
                continue
            appl = g.get("applicability", []) or []
            if "all" not in appl and wid not in appl:
                errors.append(f"{wid}: использует гейт '{gid}', но его applicability={appl} "
                              f"не включает {wid}")
        # WARN: применимый blocking-гейт, не включённый в workflow
        for gid, g in gates.items():
            appl = g.get("applicability", []) or []
            if g.get("blocking") and (wid in appl) and gid not in used:
                warns.append(f"{wid}: blocking-гейт '{gid}' применим (applicability), "
                             f"но не включён в quality_gates — возможный пропуск")
    return errors, warns


def run(as_json=False):
    gates, wfs = load()
    errors, warns = check(gates, wfs)
    if as_json:
        print(json.dumps({"schema_version": 1, "kind": "workflow-gate-consistency",
                          "errors": errors, "warns": warns}, ensure_ascii=False, indent=2))
    else:
        for w in warns:
            print(f"  WARN {w}")
        if errors:
            print(f"WORKFLOW-GATES: {len(errors)} ошибок согласованности:")
            for e in errors:
                print(f"  - {e}")
        else:
            print(f"WORKFLOW-GATES-OK: все quality_gates применимы к своим workflow"
                  + (f" ({len(warns)} WARN о возможных пропусках)." if warns else "."))
    return 1 if errors else 0


def selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    # реальный пакет: ошибок согласованности быть не должно
    gates, wfs = load()
    e, _ = check(gates, wfs)
    expect("реальный пакет: workflow↔gate согласованы", e == [])

    # синтетика: гейт вне applicability -> ошибка
    g = {"g1": {"applicability": ["ENGINEERING"], "blocking": True}}
    w = {"VISUAL": {"quality_gates": ["g1"]}}
    e2, _ = check(g, w)
    expect("гейт вне applicability -> ошибка", any("g1" in x for x in e2))

    # синтетика: applicability=all -> ок
    g3 = {"g2": {"applicability": ["all"], "blocking": False}}
    w3 = {"VISUAL": {"quality_gates": ["g2"]}}
    e3, _ = check(g3, w3)
    expect("applicability=all -> без ошибок", e3 == [])

    # синтетика: несуществующий гейт -> ошибка
    e4, _ = check({}, {"QUICK": {"quality_gates": ["ghost"]}})
    expect("несуществующий гейт -> ошибка", any("ghost" in x for x in e4))

    print("validate_workflow_gates selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    return run(as_json="--json" in argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
