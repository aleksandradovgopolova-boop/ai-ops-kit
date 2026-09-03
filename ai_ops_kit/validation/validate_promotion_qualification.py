#!/usr/bin/env python3
"""Validate PromotionQualificationPlan (v3.6.8 — Live Qualification & Controlled Promotion).

План живой квалификации и КОНТРОЛИРУЕМОГО promotion Context Engine v2 — это данные, а не живой прогон.
Валидатор стережёт инварианты, чтобы живая квалификация не пропускала шаги и не срезала доверие:

  1. форма (schema-mirror; без внешних зависимостей — только stdlib+pyyaml);
  2. promotion_sequence СТРОГО shadow -> hybrid -> default (никакого прямого v1->default flip);
  3. каждый run привязан к точному SHA (exact_sha_bound=true) — иначе binding декларативен;
  4. runs покрывают все три обязательных вида (python-child / ts-react-storybook / parallel-2);
  5. negative_scenarios покрывают ВЕСЬ обязательный набор негативов (10 шт);
  6. exit_criteria покрывают ВЕСЬ обязательный набор критериев (8 шт: 0 leaks / 100% bound / …);
  7. ЧЕСТНОСТЬ: каждый uses-инструмент существует в ai_ops_kit/ или validation/ (нет фантомных ссылок);
  8. blocked_by непуст (external-гейт live-квалификации объявлен явно, не спрятан).

Использование:
  validate_promotion_qualification.py [qualification/promotion/v3.6.8-plan.yaml]
  validate_promotion_qualification.py --selftest
Возврат 0 — ок, 1 — ошибки.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
            Path(__file__).resolve().parents[1])
DEFAULT_PLAN = PKG / "qualification" / "promotion" / "v3.6.8-plan.yaml"

REQUIRED_SEQUENCE = ["shadow", "hybrid", "default"]
REQUIRED_RUN_KINDS = {"python-child", "ts-react-storybook", "parallel-2"}
REQUIRED_NEGATIVES = {
    "write_scope_overlap", "package_fail", "contract_not_fixed", "duplicate_package_id",
    "merge_conflict", "base_moved", "aggregate_wrong_sha", "reviewer_abstain_twice",
    "mandatory_context_missing", "child_policy_changed"}
REQUIRED_CRITERIA = {
    "zero_access_leaks", "zero_stale_or_misbound_context", "zero_false_green", "zero_duplicate_pr",
    "mandatory_retained_or_block", "context_views_snapshot_bound", "package_evidence_sha_bound",
    "aggregate_evidence_integration_sha_bound"}


def _tool_exists(name, pkg=PKG):
    # v4.0: плоский слой `tools/` снят — инструмент ищется в пакетах ai_ops_kit/ (или validation/).
    if (pkg / "validation" / name).exists():
        return True
    return any("__pycache__" not in p.parts for p in (pkg / "ai_ops_kit").rglob(name))


def check(data, pkg=PKG):
    e = []
    if not isinstance(data, dict):
        return ["PromotionQualificationPlan не объект"]
    if data.get("schema_version") != 1:
        e.append("schema_version должен быть 1")
    if data.get("kind") != "PromotionQualificationPlan":
        e.append("kind должен быть PromotionQualificationPlan")
    if not str(data.get("plan_id", "")).startswith("PQP-"):
        e.append("plan_id должен быть PQP-NNN")
    for k in ("phase", "title"):
        if not data.get(k):
            e.append(f"нет обязательного поля: {k}")

    runs = data.get("runs") or []
    if len(runs) < 3:
        e.append("нужно >= 3 runs (python-child / ts-react-storybook / parallel-2)")
    run_ids, run_kinds = [], set()
    for r in runs:
        if not isinstance(r, dict):
            e.append("run не объект")
            continue
        rid = r.get("id", "")
        run_ids.append(rid)
        if not str(rid).startswith("run-"):
            e.append(f"run.id должен быть run-*: {rid}")
        run_kinds.add(r.get("kind"))
        if r.get("exact_sha_bound") is not True:
            e.append(f"{rid}: exact_sha_bound должен быть true (иначе binding декларативен)")
        if not (r.get("steps") and isinstance(r["steps"], list)):
            e.append(f"{rid}: steps непустой список обязателен")
        for u in r.get("uses") or []:
            if not _tool_exists(u, pkg):
                e.append(f"{rid}: uses ссылается на несуществующий инструмент {u} (честность)")
    if runs and not REQUIRED_RUN_KINDS <= run_kinds:
        e.append(f"runs не покрывают обязательные виды: не хватает {sorted(REQUIRED_RUN_KINDS - run_kinds)}")
    if len(set(run_ids)) != len(run_ids):
        e.append("дубликаты run.id")

    seq = [s.get("stage") for s in (data.get("promotion_sequence") or []) if isinstance(s, dict)]
    if seq != REQUIRED_SEQUENCE:
        e.append(f"promotion_sequence должен быть строго {REQUIRED_SEQUENCE} (никакого прямого v1->default), сейчас {seq}")

    negs = data.get("negative_scenarios") or []
    neg_ids = [n.get("id") for n in negs if isinstance(n, dict)]
    covers = {n.get("covers") for n in negs if isinstance(n, dict)}
    missing_neg = REQUIRED_NEGATIVES - covers
    if missing_neg:
        e.append(f"negative_scenarios не покрывают обязательные негативы: {sorted(missing_neg)}")
    if len(set(neg_ids)) != len(neg_ids):
        e.append("дубликаты negative_scenario.id")

    crits = data.get("exit_criteria") or []
    metrics = {c.get("metric") for c in crits if isinstance(c, dict)}
    missing_crit = REQUIRED_CRITERIA - metrics
    if missing_crit:
        e.append(f"exit_criteria не покрывают обязательные критерии: {sorted(missing_crit)}")

    if not (data.get("blocked_by") and isinstance(data["blocked_by"], list)):
        e.append("blocked_by непуст обязателен (external-гейт live-квалификации должен быть явным)")
    return e


def _good_plan():
    return {
        "schema_version": 1, "kind": "PromotionQualificationPlan", "plan_id": "PQP-001",
        "phase": "v3.6.8", "title": "t",
        "runs": [
            {"id": "run-a", "title": "t", "kind": "python-child", "steps": ["s"],
             "exact_sha_bound": True, "produces_pr": True, "uses": ["context_engine.py"]},
            {"id": "run-b", "title": "t", "kind": "ts-react-storybook", "steps": ["s"],
             "exact_sha_bound": True, "produces_pr": True, "uses": ["storybook_adapter.py"]},
            {"id": "run-c", "title": "t", "kind": "parallel-2", "steps": ["s"],
             "exact_sha_bound": True, "produces_pr": True, "uses": ["parallel_planner.py"]},
        ],
        "negative_scenarios": [{"id": f"neg-{c}", "scenario": "s", "expected": "block", "covers": c}
                               for c in REQUIRED_NEGATIVES],
        "promotion_sequence": [{"stage": s, "description": "d", "gate": "g"} for s in REQUIRED_SEQUENCE],
        "exit_criteria": [{"id": f"ec-{m}", "metric": m, "target": "0"} for m in REQUIRED_CRITERIA],
        "blocked_by": ["provider key rotation", "node/react toolchain"],
    }


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    path = Path(args[0]) if args else DEFAULT_PLAN
    if not path.exists():
        print(f"нет файла плана: {path}")
        return 1
    errors = check(yaml.safe_load(path.read_text(encoding="utf-8")))
    if errors:
        print(f"PROMOTION-QUALIFICATION-PLAN {path.name}: ошибки:")
        for x in errors:
            print(f"  - {x}")
        return 1
    print(f"PROMOTION-QUALIFICATION-PLAN-OK: {path.name} валиден.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
