#!/usr/bin/env python3
"""Sequential-mode оркестратор (минимальный общий знаменатель, принцип 29).

Исполняет workflow-контракт последовательно одной моделью с изоляцией ролей:
  - для каждой стадии строится ОТДЕЛЬНЫЙ role prompt из markdown-агента;
  - judge-стадии (review_mode: read-only) получают ТОЛЬКО опубликованные артефакты
    предыдущих стадий (handoff), без рассуждений автора;
  - промежуточные результаты сохраняются на диск (возобновляемость);
  - состояние — TaskState.yaml; при прерывании перезапуск продолжает с next_action.

Провайдер подключается как callable "role prompt -> text":
  - mock (по умолчанию): детерминированный ответ без сети — для selftest/CI;
  - openai-compatible HTTP-адаптер подключается снаружи (env OPENAI_COMPATIBLE_BASE_URL
    + ключ) — сетевые вызовы сознательно вынесены из этого файла.

Использование:
  orchestrator.py run <WF> "<задача>" [child_root] [--evidence <file>] [--collect-evidence] [--fresh|--resume]
        — прогон (mock-провайдер). --evidence <file>: gate-evidence по
          schemas/gate-evidence.schema.json (валидируется). --collect-evidence: вывести evidence из
          вердиктов reviewer-стадий. --fresh: начать заново; без него — resume из TaskState.
          Без evidence блокирующие гейты честно не пройдены -> status blocked.
  orchestrator.py --selftest                                — QUICK на временной папке

Требует pyyaml.
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

PKG = Path(__file__).resolve().parents[1]


# ---------------- provider ----------------

def mock_provider(role_prompt: str) -> str:
    """Детерминированный офлайн-провайдер: возвращает структурированную заглушку."""
    first = role_prompt.splitlines()[0][:80] if role_prompt else ""
    return (f"[mock-provider] Роль принята: {first}\n"
            f"Результат стадии подготовлен согласно контракту роли.")


# ---------------- state ----------------

def load_state(run_dir: Path):
    p = run_dir / "TaskState.yaml"
    if p.exists():
        return yaml.safe_load(p.read_text(encoding="utf-8"))
    return None


def save_state(run_dir: Path, state: dict):
    (run_dir / "TaskState.yaml").write_text(
        yaml.safe_dump(state, allow_unicode=True, sort_keys=False), encoding="utf-8")


# ---------------- core ----------------

def agent_body(agent_id: str, agents_index: dict):
    rel = (agents_index.get(agent_id) or {}).get("file")
    if rel and (PKG / rel).exists():
        return (PKG / rel).read_text(encoding="utf-8")
    return f"# {agent_id}\n(тело роли не найдено в пакете — используется контракт из registry)"


def build_role_prompt(stage, agent_id, agents_index, task_text, published):
    """Изолированный промпт роли: тело агента + задача + ТОЛЬКО опубликованные артефакты."""
    is_judge = stage.get("review_mode") == "read-only"
    pub = "\n".join(f"--- {name} ---\n{content}" for name, content in published.items()) or "(пока нет)"
    guard = ("\nВНИМАНИЕ: ты judge (read-only). Не изменяй проверяемые артефакты; "
             "верни только заключение. Тебе доступны ТОЛЬКО опубликованные артефакты ниже — "
             "рассуждения предыдущих ролей тебе не передаются.\n") if is_judge else ""
    return (f"{agent_body(agent_id, agents_index)}\n"
            f"{guard}\n## Задача\n{task_text}\n\n## Опубликованные артефакты\n{pub}\n")


def run_workflow(workflow_id: str, task_text: str, child_root: Path,
                 provider=mock_provider, verbose=True, gate_evidence=None,
                 collect=False, fresh=False):
    wf_all = yaml.safe_load((PKG / "registry" / "workflows.yaml").read_text(encoding="utf-8"))["workflows"]
    ag = yaml.safe_load((PKG / "registry" / "agents.yaml").read_text(encoding="utf-8"))
    agents_index = {a["id"]: a for a in ag.get("agents", [])}
    if workflow_id not in wf_all:
        raise SystemExit(f"неизвестный workflow '{workflow_id}' (есть: {', '.join(wf_all)})")
    w = wf_all[workflow_id]

    run_dir = child_root / ".ai" / "runtime" / "orchestrator" / workflow_id.lower()
    if fresh and run_dir.exists():        # --fresh: начать с чистого состояния (иначе — resume)
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    state = load_state(run_dir) or {
        "schema_version": 1, "task_id": f"seq-{workflow_id.lower()}",
        "status": "in-progress", "workflow": workflow_id, "goal": task_text,
        "execution_mode": "sequential", "current_phase": None,
        "completed_checks": [], "artifacts": [], "next_action": w["stages"][0]["id"],
    }

    stages = w["stages"]
    done_ids = {s for s in state.get("completed_checks", [])}
    published = {}  # name -> content (опубликованные артефакты)
    # восстановить опубликованное с диска (resume)
    for f in sorted(run_dir.glob("stage-*.md")):
        published[f.stem] = f.read_text(encoding="utf-8")

    for stage in stages:
        sid = stage["id"]
        if sid in done_ids:
            continue
        owner = stage.get("owner")
        state["current_phase"] = sid
        state["next_action"] = sid
        save_state(run_dir, state)

        prompt = build_role_prompt(stage, owner, agents_index, task_text, published)
        result = provider(prompt)

        # опубликовать результат стадии (это и есть handoff-артефакт)
        out = run_dir / f"stage-{sid}.md"
        out.write_text(result, encoding="utf-8")
        published[out.stem] = result

        # handoff: judge следующей стадии увидит только published
        handoff = {
            "schema_version": 1, "from_agent": owner,
            "to_agent": stages[stages.index(stage) + 1]["owner"] if stages.index(stage) + 1 < len(stages) else None,
            "stage_from": sid,
            "published_artifacts": sorted(str(p.relative_to(child_root)) for p in run_dir.glob("stage-*.md")),
        }
        (run_dir / "TaskHandoff.json").write_text(
            json.dumps(handoff, indent=2, ensure_ascii=False), encoding="utf-8")

        state["completed_checks"].append(sid)
        state["artifacts"] = handoff["published_artifacts"]
        nxt = stages.index(stage) + 1
        state["next_action"] = stages[nxt]["id"] if nxt < len(stages) else None
        save_state(run_dir, state)
        if verbose:
            role = "judge" if stage.get("review_mode") == "read-only" else "writer"
            print(f"  stage {sid} [{owner}/{role}] -> stage-{sid}.md")

    # gate executor: контур замыкается здесь — workflow НЕ done, пока блокирующие
    # гейты контракта не выполнены (writer ≠ judge; честный отказ вместо тихого done).
    sys.path.insert(0, str(PKG / "tools"))
    import gate_executor
    gate_ev = dict(gate_evidence or {})
    if collect:      # вывести evidence из вердиктов reviewer-стадий; явный --evidence имеет приоритет
        gate_ev = {**gate_executor.collect_evidence(workflow_id, run_dir), **gate_ev}
    gates = gate_executor.evaluate(workflow_id, gate_ev,
                                   tested_revision=state.get("tested_revision"))
    (run_dir / "GateReport.json").write_text(
        json.dumps(gates, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    state["current_phase"] = None
    state["gate_report"] = "GateReport.json"
    if gates["blocked"]:
        state["status"] = "blocked"
        state["unmet_gates"] = gates["unmet_gates"]
    else:
        state["status"] = "done"
        state.pop("unmet_gates", None)
    save_state(run_dir, state)
    if verbose:
        if gates["blocked"]:
            print(f"BLOCKED: workflow {workflow_id} прошёл {len(state['completed_checks'])} стадий, "
                  f"но блокирующие гейты не выполнены: {', '.join(gates['unmet_gates'])}. "
                  f"Отчёт гейтов: {run_dir / 'GateReport.json'}")
        else:
            print(f"OK: workflow {workflow_id} завершён sequential-режимом; "
                  f"{len(state['completed_checks'])} стадий, все блокирующие гейты выполнены; "
                  f"состояние: {run_dir / 'TaskState.yaml'}")
    return state, run_dir


# ---------------- selftest ----------------

def selftest():
    ok = True
    # evidence, эмулирующий выполненные блокирующие гейты QUICK (в реальном прогоне
    # его дают reviewer-стадии/валидаторы; в mock — подаём явно, чтобы дойти до done)
    quick_evidence = {
        "intake_completeness": {"status": "pass", "provided": ["classified_type", "size", "risk"]},
        "implementation_verification": {"status": "pass",
            "provided": ["build_passed", "lint_passed", "tests_passed", "tested_revision"]},
    }
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # 1. без evidence блокирующие гейты не выполнены -> workflow BLOCKED (не done)
        sb, rdb = run_workflow("QUICK", "поправить опечатку в README", root, verbose=False)
        if sb["status"] == "blocked" and set(sb.get("unmet_gates", [])) == {
                "intake_completeness", "implementation_verification"} and len(sb["completed_checks"]) == 4:
            print("PASS QUICK без evidence: 4 стадии, но статус blocked (гейты не выполнены)")
        else:
            ok = False; print(f"FAIL ожидался blocked с невыполненными гейтами, получено {sb['status']}")
        if (rdb / "GateReport.json").exists():
            print("PASS GateReport.json записан")
        else:
            ok = False; print("FAIL нет GateReport.json")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # 2. с полным evidence -> done
        state, run_dir = run_workflow("QUICK", "поправить опечатку в README", root,
                                      verbose=False, gate_evidence=quick_evidence)
        if state["status"] != "done" or len(state["completed_checks"]) != 4:
            ok = False; print("FAIL QUICK с evidence не дошёл до done")
        else:
            print("PASS QUICK с evidence: 4 стадии, статус done")
        # resume: удалить состояние последней стадии и перезапустить
        st = load_state(run_dir)
        st["completed_checks"] = st["completed_checks"][:2]
        st["status"] = "in-progress"; st["next_action"] = "local-verify"
        save_state(run_dir, st)
        state2, _ = run_workflow("QUICK", "поправить опечатку в README", root,
                                 verbose=False, gate_evidence=quick_evidence)
        if state2["status"] == "done" and len(state2["completed_checks"]) == 4:
            print("PASS resume: продолжил с прерванного места до done")
        else:
            ok = False; print("FAIL resume не сработал")
        # изоляция judge: в handoff только published-артефакты
        h = json.loads((run_dir / "TaskHandoff.json").read_text(encoding="utf-8"))
        if all(a.startswith(".ai/runtime/") and "stage-" in a for a in h["published_artifacts"]):
            print("PASS handoff содержит только опубликованные артефакты")
        else:
            ok = False; print("FAIL handoff содержит лишнее")
        # judge-промпт содержит read-only guard
        wf = yaml.safe_load((PKG / "registry" / "workflows.yaml").read_text(encoding="utf-8"))["workflows"]["QUICK"]
        judge_stage = next(s for s in wf["stages"] if s.get("review_mode") == "read-only")
        ag = yaml.safe_load((PKG / "registry" / "agents.yaml").read_text(encoding="utf-8"))
        idx = {a["id"]: a for a in ag["agents"]}
        p = build_role_prompt(judge_stage, judge_stage["owner"], idx, "t", {})
        if "read-only" in p and "рассуждения предыдущих ролей тебе не передаются" in p:
            print("PASS judge-промпт изолирован (read-only guard)")
        else:
            ok = False; print("FAIL нет read-only guard в judge-промпте")
    # --collect-evidence: провайдер, эмитящий вердикт, -> evidence собирается со стадий, done
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        def verdict_provider(role_prompt):
            return "status: passed\nРезультат стадии готов согласно контракту роли."
        sc, _ = run_workflow("QUICK", "поправить опечатку", root, provider=verdict_provider,
                             verbose=False, collect=True)
        if sc["status"] == "done":
            print("PASS collect-evidence: вердикты стадий собраны -> done без ручного evidence")
        else:
            ok = False; print(f"FAIL collect-evidence не дал done ({sc['status']})")
    print("orchestrator selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv):
    if len(argv) > 1 and argv[1] == "--selftest":
        return selftest()
    if len(argv) >= 3 and argv[1] == "run":
        rest = list(argv[2:])
        collect = "--collect-evidence" in rest
        fresh = "--fresh" in rest
        # --resume — поведение по умолчанию (продолжение из TaskState); принимаем явно
        for fl in ("--collect-evidence", "--fresh", "--resume"):
            while fl in rest:
                rest.remove(fl)
        gate_evidence = None
        if "--evidence" in rest:            # JSON по schemas/gate-evidence.schema.json (валидируется)
            i = rest.index("--evidence")
            sys.path.insert(0, str(PKG / "tools"))
            import gate_executor
            gate_evidence = gate_executor.load_evidence(rest[i + 1])
            del rest[i:i + 2]
        wf = rest[0]
        task = rest[1] if len(rest) > 1 else ""
        root = Path(rest[2]).resolve() if len(rest) > 2 else Path.cwd()
        run_workflow(wf, task, root, gate_evidence=gate_evidence, collect=collect, fresh=fresh)
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
