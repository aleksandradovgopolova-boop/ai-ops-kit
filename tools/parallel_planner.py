#!/usr/bin/env python3
"""parallel_planner.py (v3.6.5) — bounded parallel-2 execution planner (детерминированный, offline).

Планирует исполнение WorkGraph по решениям ParallelSafetyDecision и правилам безопасности, и решает
fan-in. Живой parallel-run (реальные worktrees + модель + PR) — квалификация v3.6.6/v3.8 (нужен ключ);
здесь — детерминированный ПЛАН и РЕШЕНИЯ (то, что проверяют обязательные сценарии владельца).

Правила параллельности (bounded: максимум 2 пакета одновременно):
  - два пакета параллельны, только если нет depends_on между ними И непересекающиеся write_scope;
  - общий контракт -> контракт фиксируется ПЕРВЫМ (contract_first); иначе — блок;
  - пересечение write_scope -> сериализация.
Решение fan-in (integration_decision):
  - любой пакет не pass -> fan-in НЕ начинается;
  - конфликт слияния -> block;
  - base сдвинулась -> revalidation;
  - все pass, нет конфликта, база стабильна -> нужен НОВЫЙ integration-SHA; PR открывается только
    при зелёной aggregate-проверке (иначе PR не открывается).

CLI: parallel_planner.py [examples/work-graph-demo] [--json] | --selftest
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

PKG = Path(__file__).resolve().parents[1]
WG_DEMO = PKG / "examples" / "work-graph-demo" / "work-graph.yaml"
MAX_PARALLEL = 2


def _prefix(glob):
    return (glob or "").split("*")[0].rstrip("/")


def _overlap(a_scopes, b_scopes):
    for a in a_scopes or []:
        aa = _prefix(a) + "/"
        for b in b_scopes or []:
            bb = _prefix(b) + "/"
            if aa.startswith(bb) or bb.startswith(aa):
                return True
    return False


def can_parallel(pa, pb):
    """(bool, reason): два пакета безопасно параллельны?"""
    ia, ib = pa.get("id"), pb.get("id")
    if ib in (pa.get("depends_on") or []) or ia in (pb.get("depends_on") or []):
        return False, f"depends_on между {ia},{ib} -> сериализация"
    if _overlap(pa.get("write_scope"), pb.get("write_scope")):
        return False, f"пересечение write_scope {ia},{ib} -> сериализация"
    return True, "непересекающиеся, независимые -> параллельно"


def plan(wg: dict) -> dict:
    pkgs = wg.get("packages", []) or []
    by_id = {p["id"]: p for p in pkgs if isinstance(p, dict) and p.get("id")}
    ids = list(by_id)
    independent = [p for p in pkgs if not (p.get("depends_on"))]
    dependent = [p for p in pkgs if p.get("depends_on")]

    # contract-first: контракт, разделяемый >= 2 пакетами
    contract_count = {}
    for p in pkgs:
        for c in p.get("shared_contracts") or []:
            contract_count[c] = contract_count.get(c, 0) + 1
    contract_first = sorted([c for c, n in contract_count.items() if n >= 2])

    # bounded parallel-2 группы среди независимых с непересекающимися scope
    groups, used = [], set()
    for i, pa in enumerate(independent):
        if pa["id"] in used:
            continue
        group = [pa["id"]]
        used.add(pa["id"])
        for pb in independent[i + 1:]:
            if pb["id"] in used or len(group) >= MAX_PARALLEL:
                continue
            okp, _ = can_parallel(pa, pb)
            if okp:
                group.append(pb["id"])
                used.add(pb["id"])
        groups.append(group)

    has_parallel = any(len(g) >= 2 for g in groups)
    if len(pkgs) <= 1:
        mode = "single"
    elif has_parallel and dependent:
        mode = "hybrid"
    elif has_parallel:
        mode = "parallel"
    else:
        mode = "sequential"

    # integration_order — топологический (пакет после depends_on)
    order, placed = [], set()
    guard = 0
    remaining = list(ids)
    while remaining and guard < len(ids) + 2:
        guard += 1
        for pid in list(remaining):
            deps = by_id[pid].get("depends_on") or []
            if all(d in placed for d in deps):
                order.append(pid)
                placed.add(pid)
                remaining.remove(pid)
    return {"kind": "parallel-plan", "mode": mode, "max_parallel": MAX_PARALLEL,
            "parallel_groups": groups, "dependent": [p["id"] for p in dependent],
            "contract_first": contract_first, "integration_order": order,
            "fan_in_required": len(pkgs) > 1}


def integration_decision(package_results: dict, conflicts=0, base_moved=False, aggregate_ok=True):
    """package_results: {pkg_id: 'pass'|'fail'|...}. Решение о fan-in/интеграции/PR."""
    if any(v != "pass" for v in package_results.values()):
        failed = [k for k, v in package_results.items() if v != "pass"]
        return {"proceed": False, "integration_sha_required": False, "open_pr": False,
                "reason": f"пакет(ы) не pass {failed} -> fan-in НЕ начинается"}
    if conflicts and conflicts > 0:
        return {"proceed": False, "integration_sha_required": False, "open_pr": False,
                "reason": "merge conflict при fan-in -> block"}
    if base_moved:
        return {"proceed": False, "integration_sha_required": True, "open_pr": False,
                "revalidation_required": True, "reason": "base сдвинулась -> integration revalidation"}
    # все pass, нет конфликта, база стабильна
    return {"proceed": True, "integration_sha_required": True, "open_pr": bool(aggregate_ok),
            "reason": ("aggregate green -> новый integration-SHA + один draft PR" if aggregate_ok
                       else "aggregate FAIL -> integration-SHA есть, но PR НЕ открывается")}


def selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    # реальный demo WG-001 (api||ui + wiring)
    if WG_DEMO.exists():
        wg = yaml.safe_load(WG_DEMO.read_text(encoding="utf-8"))
        p = plan(wg)
        expect("WG-001: api,ui в одной параллельной группе (непересекающиеся)",
               any(set(g) == {"api", "ui"} for g in p["parallel_groups"]))
        expect("WG-001: mode=hybrid (parallel + зависимый wiring)", p["mode"] == "hybrid")
        expect("WG-001: contract_first содержит OrderContract (общий у api,ui)",
               "OrderContract" in p["contract_first"])
        expect("WG-001: integration_order топологичен (wiring последним)", p["integration_order"][-1] == "wiring")
        expect("WG-001: fan_in_required", p["fan_in_required"] is True)

    # сценарий: непересекающиеся независимые -> parallel
    okp, _ = can_parallel({"id": "a", "write_scope": ["src/a/**"]},
                          {"id": "b", "write_scope": ["src/b/**"]})
    expect("непересекающиеся независимые -> parallel", okp is True)
    # пересечение write_scope -> serialize
    okp, r = can_parallel({"id": "a", "write_scope": ["src/**"]},
                          {"id": "b", "write_scope": ["src/b/**"]})
    expect("пересечение write_scope -> сериализация", okp is False and "write_scope" in r)
    # depends_on -> serialize
    okp, r = can_parallel({"id": "a", "write_scope": ["x/**"]},
                          {"id": "b", "write_scope": ["y/**"], "depends_on": ["a"]})
    expect("depends_on -> сериализация", okp is False and "depends_on" in r)

    # общий контракт -> contract_first
    wg2 = {"packages": [{"id": "a", "write_scope": ["a/**"], "shared_contracts": ["C"]},
                        {"id": "b", "write_scope": ["b/**"], "shared_contracts": ["C"]}]}
    expect("общий контракт C -> contract_first", plan(wg2)["contract_first"] == ["C"])

    # integration decision — обязательные сценарии
    expect("один пакет fail -> fan-in НЕ начинается",
           integration_decision({"a": "pass", "b": "fail"})["proceed"] is False)
    d = integration_decision({"a": "pass", "b": "pass"}, conflicts=0, base_moved=False, aggregate_ok=True)
    expect("оба pass, нет конфликта, aggregate green -> integration-SHA + PR",
           d["proceed"] and d["integration_sha_required"] and d["open_pr"])
    expect("merge conflict -> block",
           integration_decision({"a": "pass", "b": "pass"}, conflicts=1)["proceed"] is False)
    dbm = integration_decision({"a": "pass", "b": "pass"}, base_moved=True)
    expect("base moved -> revalidation, PR не открыт",
           dbm.get("revalidation_required") is True and dbm["open_pr"] is False)
    dagg = integration_decision({"a": "pass", "b": "pass"}, aggregate_ok=False)
    expect("aggregate fail -> integration-SHA есть, PR НЕ открывается",
           dagg["integration_sha_required"] is True and dagg["open_pr"] is False)

    # single / sequential режимы
    expect("один пакет -> single", plan({"packages": [{"id": "a", "write_scope": ["a/**"]}]})["mode"] == "single")
    seq = plan({"packages": [{"id": "a", "write_scope": ["a/**"]},
                             {"id": "b", "write_scope": ["b/**"], "depends_on": ["a"]}]})
    expect("цепочка зависимостей -> sequential", seq["mode"] == "sequential")

    print("parallel_planner selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    args = [a for a in argv if not a.startswith("--")]
    wg_path = Path(args[0]) / "work-graph.yaml" if args else WG_DEMO
    p = plan(yaml.safe_load(Path(wg_path).read_text(encoding="utf-8")))
    print(json.dumps(p, ensure_ascii=False, indent=2) if "--json" in argv
          else f"PLAN mode={p['mode']} groups={p['parallel_groups']} order={p['integration_order']} "
               f"contract_first={p['contract_first']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
