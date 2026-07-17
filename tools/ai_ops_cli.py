#!/usr/bin/env python3
"""Intent-based UX поверх движка (v2.102, эпик Context Engineering, этап 6).

Снаружи AI Ops должен быть проще внутренней архитектуры. Обычный сценарий управляется намерениями,
а не флагами: пользователю не нужно помнить --engine pipeline / --author / --review / --baseline-diff
/ --sandbox — система сама подбирает workflow, стадии и нужные флаги (presets) и ПОКАЗЫВАЕТ
execution preview до запуска. Низкоуровневые флаги остаются доступны, но не обязательны.

Команды намерений:
  new · onboard · discuss · specify · plan · run · resume · review · status · health

Использование:
  ai_ops_cli.py <intent> [задача] <child_root> [--signals '{...}'] [--feature name] [--json] [--execute]
  ai_ops_cli.py preview <intent> [задача] <child_root> ...
  ai_ops_cli.py --selftest
"""

import argparse
import json
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
for _p in (PKG / "tools",):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# intent -> (описание, какое действие, нужен ли текст задачи)
INTENTS = {
    "new":     ("создать новую фичу/каркас", "scaffold", False),
    "onboard": ("определить стек и команды репозитория", "onboard", False),
    "discuss": ("обсудить идею до спецификации (discovery)", "discuss", True),
    "specify": ("построить спецификацию нужной глубины", "specify", True),
    "plan":    ("построить RunPlan + контекст + оценку пакета (без правок)", "plan", True),
    "run":     ("выполнить задачу движком (авто-подбор стадий)", "run", True),
    "resume":  ("продолжить прерванную работу по фиче", "resume", False),
    "review":  ("независимый ревью произведённого", "review", True),
    "status":  ("статус активной работы", "status", False),
    "health":  ("здоровье продукта", "health", False),
}


def resolve_flags(signals):
    """Авто-подбор внутренних флагов по классу задачи (preset). Пользователь их не задаёт вручную."""
    tt = (signals.get("task_type") or "QUICK").upper()
    flags = {"engine": "pipeline", "sandbox": True, "baseline_diff": True,
             "review": False, "author": False}
    if tt in ("ENGINEERING", "PRODUCT", "CRITICAL", "AI_FEATURE", "RESEARCH"):
        flags["review"] = True
        flags["author"] = True
    if signals.get("fix") or tt == "QUICK" and signals.get("require_fix"):
        flags["require_fix"] = True
    return flags


def build_preview(intent, task, child_root, signals):
    """Execution preview: что понято, что будет сделано, какие данные, какие approvals, результат."""
    import run_plan
    import context_compiler
    import spec_levels
    import atomic_planner
    signals = dict(signals or {})
    if task:
        signals.setdefault("task_text", task)
    plan = run_plan.build_plan(signals, workitem_id=signals.get("feature"))
    # v2.107 (finding аудита): единый результат классификации. Раньше router мог решить ENGINEERING,
    # а preset/Spec-First — QUICK (task_type по умолчанию) -> противоречивый режим (workflow
    # ENGINEERING, spec L0, review/author off -> закономерный блок). Теперь task_type берём из
    # РЕШЕНИЯ роутера (base_workflow), и его же используют resolve_flags и spec_levels.
    if not signals.get("task_type"):
        signals["task_type"] = plan["base_workflow"]
    flags = resolve_flags(signals)
    bundle = None
    try:
        bundle = context_compiler.compile_bundle(signals, child_root, plan=plan)
    except Exception:  # noqa: BLE001
        bundle = None
    cov = spec_levels.assess(signals)
    wp = atomic_planner.assess(signals, child_root=child_root, bundle=bundle)

    # approvals: CRITICAL уровень, needs_human разделы, human-approval сигналы
    approvals = []
    if cov["level"] >= 3:
        approvals.append("человек: критическое/необратимое изменение (L3 CRITICAL)")
    if cov["needs_human"]:
        approvals.append("человек: разделы спецификации " + ", ".join(cov["needs_human"]))
    if signals.get("secret_boundary") or signals.get("destructive"):
        approvals.append("человек: затронута граница секретов/деструктивное действие")

    expected = ("проверяемый draft PR (если гейты закрыты)" if intent == "run"
                else {"plan": "RunPlan + оценка без изменений кода",
                      "specify": f"спецификация уровня {cov['level_name']}",
                      "review": "вердикты независимых ревьюеров",
                      "onboard": "RepositoryProfile (стек/команды)",
                      "status": "список активной работы", "health": "Product Health Score",
                      "discuss": "черновик проблемы/гипотез (discovery)",
                      "new": "каркас фичи",
                      "resume": "продолжение с последнего подтверждённого шага"}.get(intent, "результат намерения"))

    return {
        "schema_version": 1, "kind": "ExecutionPreview",
        "intent": intent, "understood": {"task": task, "task_type": signals.get("task_type", "QUICK"),
                                          "workflow": plan["base_workflow"],
                                          "spec_level": cov["level_name"]},
        "will_do": {"stages": plan["gates"], "tracks": [t["track"] for t in plan.get("required_tracks", [])],
                    "auto_flags": flags},
        "data_used": {"agents": (bundle or {}).get("included", {}).get("agents", []),
                      "rules": (bundle or {}).get("included", {}).get("rules", []),
                      "estimated_tokens": (bundle or {}).get("estimated_tokens"),
                      "context_budget": (bundle or {}).get("context_budget")},
        "approvals_needed": approvals,
        "decomposition_advised": wp["should_decompose"],
        "expected_result": expected,
    }


def selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    expect("10 intent-команд", len(INTENTS) == 10
           and {"new", "onboard", "discuss", "specify", "plan", "run", "resume", "review",
                "status", "health"} == set(INTENTS))

    # preset: QUICK -> без review/author; ENGINEERING -> review+author; всегда sandbox+baseline
    fq = resolve_flags({"task_type": "QUICK"})
    expect("QUICK preset: sandbox+baseline, без review/author",
           fq["sandbox"] and fq["baseline_diff"] and not fq["review"] and not fq["author"])
    fe = resolve_flags({"task_type": "ENGINEERING"})
    expect("ENGINEERING preset: review+author включены", fe["review"] and fe["author"])

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "package.json").write_text('{"dependencies":{"react":"^18"}}', encoding="utf-8")
        pv = build_preview("run", "добавить фильтр", root,
                           {"task_type": "ENGINEERING", "risk": "medium", "affected_areas": ["core"]})
        expect("preview: kind=ExecutionPreview", pv["kind"] == "ExecutionPreview")
        expect("preview: понял workflow ENGINEERING", pv["understood"]["workflow"] == "ENGINEERING")
        expect("preview: авто-флаги без ручного ввода (engine=pipeline)",
               pv["will_do"]["auto_flags"]["engine"] == "pipeline")
        expect("preview: данные — агенты и токены измерены", isinstance(pv["data_used"]["agents"], list)
               and pv["data_used"]["estimated_tokens"] is not None)
        expect("preview: ожидаемый результат назван", bool(pv["expected_result"]))

        # CRITICAL -> approval человека
        pc = build_preview("run", "миграция схемы", root,
                           {"task_type": "CRITICAL", "risk": "critical", "affected_areas": ["db"]})
        expect("preview CRITICAL: требует human approval",
               any("человек" in a for a in pc["approvals_needed"]))

        # v2.107: единая классификация — без task_type preset/spec берут решение роутера (не расходятся)
        pv_u = build_preview("run", "поправить логику расчёта", root,
                             {"affected_areas": ["core"], "risk": "medium"})  # без task_type
        wf_u = pv_u["understood"]["workflow"]
        af_u = pv_u["will_do"]["auto_flags"]
        # если роутер выбрал ENGINEERING+ -> review/author включены (согласовано, не противоречиво)
        expect("v2.107: без task_type preset согласован с роутером (нет ENGINEERING+L0+review off)",
               (wf_u in ("QUICK",)) or (af_u["review"] and af_u["author"]))

        # много подсистем -> decomposition_advised
        pd = build_preview("run", "большой рефактор", root,
                           {"task_type": "ENGINEERING", "affected_areas": ["a", "b", "c", "d"], "size": "large"})
        expect("preview: советует декомпозицию для большой задачи", pd["decomposition_advised"] is True)

    print("ai_ops_cli selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def _print_preview(pv):
    u = pv["understood"]
    print(f"■ intent: {pv['intent']} · {INTENTS.get(pv['intent'], ('',))[0]}")
    print(f"  понял: {u['task_type']} -> workflow {u['workflow']} · спецификация {u['spec_level']}")
    af = pv["will_do"]["auto_flags"]
    print(f"  сделаю: гейтов {len(pv['will_do']['stages'])} · авто-режим "
          f"(engine={af['engine']}, review={af['review']}, author={af['author']}, sandbox={af['sandbox']})")
    du = pv["data_used"]
    print(f"  данные: агентов {len(du['agents'])} · ~{du['estimated_tokens']}/{du['context_budget']} ток.")
    if pv["approvals_needed"]:
        for a in pv["approvals_needed"]:
            print(f"  approval: {a}")
    if pv["decomposition_advised"]:
        print("  ⚠ советую разбить задачу (превышает атомарный размер)")
    print(f"  ожидаю: {pv['expected_result']}")


def main(argv):
    if "--selftest" in argv:
        return selftest()
    ap = argparse.ArgumentParser(prog="ai_ops_cli.py")
    ap.add_argument("intent", choices=list(INTENTS) + ["preview"])
    ap.add_argument("rest", nargs="*")
    ap.add_argument("--signals", default="{}")
    ap.add_argument("--feature")
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    intent = a.intent
    rest = list(a.rest)
    if intent == "preview":
        intent = rest.pop(0) if rest else "run"
    # разбор [задача] child_root
    needs_task = INTENTS.get(intent, ("", "", False))[2]
    task, child_root = None, "."
    if needs_task:
        task = rest.pop(0) if rest else ""
    child_root = rest.pop(0) if rest else "."
    signals = json.loads(a.signals)
    if a.feature:
        signals["feature"] = a.feature

    if intent == "resume":
        import ai_ops_run
        return ai_ops_run.main(["resume", child_root, a.feature or (task or "")])

    pv = build_preview(intent, task, Path(child_root), signals)
    if a.json:
        print(json.dumps(pv, ensure_ascii=False, indent=2))
    else:
        _print_preview(pv)

    # только `run --execute` реально запускает движок; остальное — превью/делегация
    if intent == "run" and a.execute:
        import ai_ops_run
        flags = pv["will_do"]["auto_flags"]
        print("— запускаю —")
        rep = ai_ops_run.run(task, signals, Path(child_root), engine=flags["engine"],
                             feature=a.feature, execute=True, sandbox=flags["sandbox"],
                             baseline_diff=flags["baseline_diff"], review=flags["review"],
                             author=flags["author"])
        ai_ops_run.print_human(rep)
        return ai_ops_run.exit_code(rep)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
