#!/usr/bin/env python3
"""ai-ops run — единый контроллер задачи (v2.34, Execution Engine Фаза 2, срез 1).

Собирает разрозненные шаги в ОДНУ транзакцию: классификация/маршрут → RunPlan
(base_workflow + треки + агрегированные гейты) → WorkItem → регистрация в реестре
активных работ → исполнение → компактный отчёт. Раньше это были отдельные инструменты;
теперь — один вход, как обещает продукт.

Граница исполнения (честно, без переоценки):
- **claude-code и другие рантаймы с собственным tool loop**: контроллер готовит план и
  каркас состояния (RunPlan, WorkItem, active-work, TaskState), а стадии/патчи/тесты
  исполняет сам рантайм, следуя плану. status = `planned`. Кит не притворяется, что
  исполнил за рантайм.
- **generic-orchestrator** (наш sequential-движок): контроллер реально прогоняет стадии
  и гейты (tools/orchestrator.py) — status = done|blocked по evidence.

Аддитивно (2.x): ничего не ломает; `ai-ops run` как ОСНОВНОЙ путь и сплит на пакеты —
цель 3.0.

Использование:
  ai_ops_run.py run "<задача>" <child_root> [--signals '<json>'] [--features-dir dir]
       [--runtime claude-code|generic-orchestrator] [--provider mock] [--execute] [--json]
  ai_ops_run.py --selftest
"""

import argparse
import json
import sys
from pathlib import Path

import yaml

PKG = Path(__file__).resolve().parents[1]
for _p in (PKG / "tools", PKG / "validation"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import run_plan          # noqa: E402
import workitem          # noqa: E402
import active_work       # noqa: E402


def run(task_text, signals, child_root: Path, features_dir=None,
        runtime="claude-code", provider_name="mock", session="cli", execute=False,
        feature=None):
    signals = dict(signals or {})
    signals.setdefault("task_text", task_text)
    child_root = Path(child_root)
    features_dir = Path(features_dir) if features_dir else child_root / "features"

    # 1-2. RunPlan (route + треки + агрегированные гейты).
    # feature (v2.51): привязка WorkItem к ИМЕНОВАННОЙ фиче — иначе wid=wi-<hash>, и срезы
    # истории падают на новую фичу с 1 срезом (baseline не двигается — finding обкатки 5).
    plan = run_plan.build_plan(signals, workitem_id=feature)
    fid = plan["workitem_id"]
    base_wf = plan["base_workflow"]

    # 3. WorkItem
    workitem.start(str(features_dir), fid, task_text,
                   task_type=signals.get("task_type"), risk=signals.get("risk"))

    # 4. RunPlan на диск (рядом с WorkItem)
    (features_dir / fid / "run-plan.yaml").write_text(
        yaml.safe_dump(plan, allow_unicode=True, sort_keys=False), encoding="utf-8")

    # 5. регистрация активной работы (координация параллельных сессий)
    aw_path = child_root / ".ai" / "runtime" / "active-work.yaml"
    areas = signals.get("affected_areas") or ["unspecified"]
    active_work.register(aw_path, fid, f"feature/{fid}", areas, session,
                         workitem=f"features/{fid}/workitem.yaml")

    # 6. исполнение
    status, run_state = "planned", f".ai/runtime/workitems/{fid}/TaskState.yaml"
    run_state_materialized = False   # честно: в planned run_state — обещание пути, не файл
    if execute or runtime == "generic-orchestrator":
        import orchestrator
        st, run_dir = orchestrator.run_workflow(
            base_wf, task_text, child_root,
            provider=orchestrator.make_provider(provider_name),
            provider_name=provider_name, verbose=False, workitem_id=fid,
            budget=plan.get("execution_budget"),   # v2.38: потолок вызовов из RunPlan
            gate_ids=plan.get("gates"))            # v2.54: прогон оценивает ГЕЙТЫ RUNPLAN (base+треки)
        status = st["status"]
        run_state = str(Path(run_dir) / "TaskState.yaml")
        run_state_materialized = True

    # 7. компактный отчёт
    report = {
        "schema_version": 1, "kind": "run-report",
        "workitem_id": fid, "base_workflow": base_wf,
        "required_tracks": [t["track"] for t in plan["required_tracks"]],
        "conditional_tracks": [t["track"] for t in plan["conditional_tracks"]],
        "skipped_tracks": [{"track": t["track"], "reason": t["reason"]} for t in plan["skipped_tracks"]],
        "gates": plan["gates"],
        "runtime": runtime, "execution": "orchestrated" if (execute or runtime == "generic-orchestrator") else "planned",
        "status": status, "run_state": run_state,
        # честно: в planned run_state — ОБЕЩАНИЕ пути; папку workitems/<id>/ создаёт
        # рантайм при реальном исполнении стадий, не контроллер. Не полагаться на её
        # наличие после planned-прогона (finding обкатки v2.34).
        "run_state_materialized": run_state_materialized,
        "artifacts": {"workitem": f"features/{fid}/workitem.yaml",
                      "run_plan": f"features/{fid}/run-plan.yaml"},
    }
    (features_dir / fid / "run-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def print_human(r):
    print(f"ai-ops run → WorkItem {r['workitem_id']} [{r['status']}]")
    print(f"  base_workflow: {r['base_workflow']} · execution: {r['execution']} ({r['runtime']})")
    if r["required_tracks"]:
        print(f"  треки (required): {', '.join(r['required_tracks'])}")
    if r["conditional_tracks"]:
        print(f"  треки (conditional): {', '.join(r['conditional_tracks'])}")
    print(f"  гейты ({len(r['gates'])}): {', '.join(r['gates'])}")
    for s in r["skipped_tracks"]:
        print(f"  · пропущен {s['track']}: {s['reason']}")
    if r["status"] == "planned":
        print("  → план и каркас готовы; стадии исполняет рантайм (claude-code) по плану.")


def selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    sig = {"task_type": "PRODUCT", "risk": "medium",
           "available_providers": ["anthropic"], "available_runtimes": ["claude-code"],
           "ui_changed": True, "measurable_behavior": True, "user_facing_change": True,
           "affected_areas": ["catalog", "orders-api"]}

    # planned-путь (claude-code): каркас есть, статус planned
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        r = run("фильтр по статусу в каталоге заказов", sig, root, runtime="claude-code")
        fid = r["workitem_id"]
        expect("planned: статус planned", r["status"] == "planned")
        expect("planned: run_state НЕ материализован (обещание пути)",
               r["run_state_materialized"] is False)
        expect("planned: RunPlan записан", (root / "features" / fid / "run-plan.yaml").exists())
        expect("planned: WorkItem записан", (root / "features" / fid / "workitem.yaml").exists())
        expect("planned: run-report записан", (root / "features" / fid / "run-report.json").exists())
        expect("planned: active-work зарегистрирована",
               (root / ".ai" / "runtime" / "active-work.yaml").exists())
        expect("треки VISUAL/ANALYTICS в отчёте", {"VISUAL", "ANALYTICS"} <= set(r["required_tracks"]))
        expect("гейты треков агрегированы (ux_review/analytics_readiness)",
               {"ux_review", "analytics_readiness"} <= set(r["gates"]))
        expect("planned: без --feature wid = wi-<hash>", fid.startswith("wi-"))

    # v2.51: привязка к ИМЕНОВАННОЙ фиче — срезы истории копятся на неё, не на wi-<hash>
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        rf = run("фильтр по типу в библиотеке", sig, root, runtime="claude-code",
                 feature="library-view")
        expect("feature: WorkItem привязан к именованной фиче",
               rf["workitem_id"] == "library-view"
               and (root / "features" / "library-view" / "run-plan.yaml").exists())

    # orchestrated-путь (generic-orchestrator, mock без evidence -> blocked, но транзакция прошла)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        r2 = run("починить опечатку", {"task_type": "QUICK", "affected_areas": ["docs"]},
                 root, runtime="generic-orchestrator", provider_name="mock", execute=True)
        expect("orchestrated: исполнение прошло, статус blocked|done",
               r2["status"] in ("blocked", "done") and r2["execution"] == "orchestrated")
        expect("orchestrated: состояние по WorkItem",
               f"workitems/{r2['workitem_id']}" in r2["run_state"])

    print("ai_ops_run selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    ap = argparse.ArgumentParser(prog="ai_ops_run.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("run")
    rp.add_argument("task"); rp.add_argument("child_root")
    rp.add_argument("--signals", default="{}")
    rp.add_argument("--features-dir")
    rp.add_argument("--runtime", default="claude-code")
    rp.add_argument("--provider", default="mock")
    rp.add_argument("--session", default="cli")
    rp.add_argument("--execute", action="store_true")
    rp.add_argument("--feature", help="имя существующей фичи — привязать WorkItem к ней "
                                      "(иначе wi-<hash>; срезы истории не накопятся на одну фичу)")
    rp.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "run":
        report = run(a.task, json.loads(a.signals), Path(a.child_root), a.features_dir,
                     a.runtime, a.provider, a.session, a.execute, feature=a.feature)
        if a.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print_human(report)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
