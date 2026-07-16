#!/usr/bin/env python3
"""Единый execution-pipeline (v2.58, P0-эпик) — СБОРКА исполнения в один движок.

Аудит: компоненты есть, но не собраны; generic-путь гонял doc-оркестратор, а не tool-loop.
Этот модуль соединяет уже построенные части в ОДНУ цепочку:

  detect (RepositoryProfile) -> tool-loop (модель предлагает, Policy решает, Broker исполняет,
  результат в контекст) -> evidence collector (реальный прогон build/lint/typecheck/test через
  Broker) -> RunPlan-гейты (base_workflow + треки) -> единый отчёт.

Честная граница (НЕ имитируется): commit + reverify на точном SHA и открытие draft PR — ещё НЕ
здесь (нужен git-commit шаг и живой прогон); pipeline доводит до «изменения применены + evidence
собран + гейты оценены». Механика детерминирована и тестируется offline mock-предложителем;
живой предложитель — swap провайдера (как tool_loop.make_model_proposer).

Использование (программно):
  run_pipeline(task, signals, child_root, proposer, policy, budget, max_steps) -> отчёт.
  execution_pipeline.py --selftest
"""

import json
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
for _p in (PKG / "tools", PKG / "validation"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import project_detector      # noqa: E402
import tool_loop             # noqa: E402
import tool_broker           # noqa: E402
import evidence_collector    # noqa: E402
import run_plan              # noqa: E402
import gate_executor         # noqa: E402


def _profile_summary(profile):
    stacks = profile.get("stacks") or []
    langs = ", ".join(s.get("language", "?") for s in stacks) or "не определён"
    cmds = {}
    for s in stacks:
        for k, v in (s.get("commands") or {}).items():
            if v and k not in cmds:
                cmds[k] = v
    return f"Стек: {langs}. Команды проверки: {cmds or 'нет'}."


def run_pipeline(task, signals, child_root, proposer, policy=None, budget=None,
                 max_steps=20, feature=None):
    """Один прогон движка: детект -> правки через tool-loop -> evidence -> гейты RunPlan."""
    child_root = Path(child_root)
    signals = dict(signals or {})
    signals.setdefault("task_text", task)

    # 1. детект стека
    profile = project_detector.detect(child_root)

    # 2. план (base_workflow + треки -> агрегированные гейты)
    plan = run_plan.build_plan(signals, workitem_id=feature)

    # 3. политика по умолчанию: execution, запись в рамках репо (scope можно сузить снаружи)
    pol = policy or tool_broker.Policy(level="execution", child_root=str(child_root))

    # 4. tool-loop: модель применяет изменения (context = задача + профиль стека)
    ctx = f"{task}\n\n{_profile_summary(profile)}"
    loop = tool_loop.run_loop(proposer, child_root, pol, budget=budget,
                              max_steps=max_steps, base_context=ctx)

    # 5. evidence: реальный прогон команд профиля через Broker
    coll = evidence_collector.collect(profile, child_root, pol)

    # 6. гейты RunPlan (base + треки), c evidence из коллектора + сигналы (условный approval)
    gates = gate_executor.evaluate(plan["base_workflow"], coll["gate_evidence"],
                                   gate_ids=plan["gates"], signals=signals)

    applied = [e for e in loop["executed"] if e.get("op") == "write" and e.get("ok")]
    return {
        "schema_version": 1, "kind": "execution-pipeline",
        "workitem_id": plan["workitem_id"],
        "base_workflow": plan["base_workflow"],
        "profile": {"stacks": [s.get("language") for s in profile.get("stacks", [])],
                    "undetermined": profile.get("undetermined", [])},
        "loop": {"stopped": loop["stopped"], "steps": loop["steps"],
                 "applied_writes": len(applied), "denied": len(loop["denied"])},
        "checks": coll["checks"],
        "gates": {"evaluated": gates["evaluated_gates"], "unmet": gates["unmet_gates"],
                  "blocked": gates["blocked"]},
        # honest: «готово» = петля дошла до done И гейты не блокируют. Draft PR/commit — ещё не тут.
        "ready_for_pr": (loop["stopped"] == "done") and (not gates["blocked"]),
        "not_yet": ["commit+reverify на точном SHA", "открытие draft PR", "живой предложитель"],
    }


def selftest():
    import tempfile
    import subprocess
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        subprocess.run(["git", "-C", td, "init", "-q"])
        subprocess.run(["git", "-C", td, "config", "user.email", "t@t"])
        subprocess.run(["git", "-C", td, "config", "user.name", "t"])
        (root / "src").mkdir()
        # python-профиль с тривиальными проверками, которые пройдут
        (root / "pyproject.toml").write_text(
            "[tool.poetry]\nname='x'\n[tool.poetry.dependencies]\npytest='*'\n", encoding="utf-8")
        (root / "tests").mkdir()
        (root / "f").write_text("x", encoding="utf-8")
        subprocess.run(["git", "-C", td, "add", "-A"]); subprocess.run(["git", "-C", td, "commit", "-q", "-m", "i"])

        # mock-предложитель: пишет файл в scope, читает его, done
        script = [
            {"op": "write", "path": "src/add.py", "content": "def add(a,b): return a+b\n"},
            {"op": "read", "path": "src/add.py"},
            {"done": True, "summary": "добавил add"},
        ]
        it = iter(script)
        pol = tool_broker.Policy(level="execution", write_scope=["src/"])
        sig = {"task_type": "QUICK", "affected_areas": ["core"]}
        rep = run_pipeline("добавить функцию add", sig, root, lambda c: next(it),
                           policy=pol, budget={"max_model_calls": 10}, feature="add-fn")

        expect("pipeline: петля дошла до done", rep["loop"]["stopped"] == "done")
        expect("pipeline: изменение применено (write)", rep["loop"]["applied_writes"] == 1
               and (root / "src" / "add.py").exists())
        expect("pipeline: профиль определил python", "python" in rep["profile"]["stacks"])
        expect("pipeline: evidence-проверки собраны", isinstance(rep["checks"], dict) and rep["checks"])
        expect("pipeline: гейты RunPlan оценены (есть вердикт blocked)",
               "blocked" in rep["gates"] and isinstance(rep["gates"]["evaluated"], list))
        expect("pipeline: workitem привязан к именованной фиче", rep["workitem_id"] == "add-fn")
        expect("pipeline: честный not_yet (commit/PR/живой)", len(rep["not_yet"]) == 3)

        # write вне scope -> denied, файл не создан, но pipeline не падает
        it2 = iter([{"op": "write", "path": "config/x", "content": "y"}, {"done": True}])
        rep2 = run_pipeline("вне scope", sig, root, lambda c: next(it2), policy=pol,
                            budget={"max_model_calls": 5})
        expect("pipeline: out-of-scope запись отклонена (denied>0)", rep2["loop"]["denied"] >= 1
               and not (root / "config" / "x").exists())

    print("execution_pipeline selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
