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
  orchestrator.py run <WORKFLOW> "<задача>" [child_root]   — прогон (mock-провайдер)
  orchestrator.py --selftest                                — QUICK на временной папке

Требует pyyaml.
"""

import json
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
                 provider=mock_provider, verbose=True):
    wf_all = yaml.safe_load((PKG / "registry" / "workflows.yaml").read_text(encoding="utf-8"))["workflows"]
    ag = yaml.safe_load((PKG / "registry" / "agents.yaml").read_text(encoding="utf-8"))
    agents_index = {a["id"]: a for a in ag.get("agents", [])}
    if workflow_id not in wf_all:
        raise SystemExit(f"неизвестный workflow '{workflow_id}' (есть: {', '.join(wf_all)})")
    w = wf_all[workflow_id]

    run_dir = child_root / ".ai" / "runtime" / "orchestrator" / workflow_id.lower()
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

    state["status"] = "done"
    state["current_phase"] = None
    save_state(run_dir, state)
    if verbose:
        print(f"OK: workflow {workflow_id} завершён sequential-режимом; "
              f"{len(state['completed_checks'])} стадий, состояние: {run_dir / 'TaskState.yaml'}")
    return state, run_dir


# ---------------- selftest ----------------

def selftest():
    ok = True
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        state, run_dir = run_workflow("QUICK", "поправить опечатку в README", root, verbose=False)
        if state["status"] != "done" or len(state["completed_checks"]) != 4:
            ok = False; print("FAIL QUICK не дошёл до done")
        else:
            print("PASS QUICK: 4 стадии, статус done")
        # resume: удалить состояние последней стадии и перезапустить
        st = load_state(run_dir)
        st["completed_checks"] = st["completed_checks"][:2]
        st["status"] = "in-progress"; st["next_action"] = "local-verify"
        save_state(run_dir, st)
        state2, _ = run_workflow("QUICK", "поправить опечатку в README", root, verbose=False)
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
    print("orchestrator selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv):
    if len(argv) > 1 and argv[1] == "--selftest":
        return selftest()
    if len(argv) >= 3 and argv[1] == "run":
        root = Path(argv[4]).resolve() if len(argv) > 4 else Path.cwd()
        run_workflow(argv[2], argv[3], root)
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
