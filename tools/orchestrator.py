#!/usr/bin/env python3
"""Sequential-mode оркестратор (минимальный общий знаменатель, принцип 29).

Исполняет workflow-контракт последовательно одной моделью с изоляцией ролей:
  - для каждой стадии строится ОТДЕЛЬНЫЙ role prompt из markdown-агента;
  - judge-стадии (review_mode: read-only) получают ТОЛЬКО опубликованные артефакты
    предыдущих стадий (handoff), без рассуждений автора;
  - промежуточные результаты сохраняются на диск (возобновляемость);
  - состояние — TaskState.yaml; при прерывании перезапуск продолжает с next_action.

Провайдер подключается как callable "role prompt -> text" (provider-agnostic):
  - mock (по умолчанию): детерминированный ответ без сети — для selftest/CI;
  - anthropic: api.anthropic.com, ключ ANTHROPIC_API_KEY;
  - openai: api.openai.com, ключ OPENAI_API_KEY;
  - openai-compatible: любой OpenAI-совместимый endpoint (DeepSeek, local, GigaChat-gw…)
    через env OPENAI_COMPATIBLE_BASE_URL + OPENAI_COMPATIBLE_API_KEY + --model.
  Ключ — ТОЛЬКО из env (не в репо/логах); без ключа — честная ошибка, не тихий mock.

Использование:
  orchestrator.py run <WF> "<задача>" [child_root] [--workitem-id <id>] [--evidence <file>] [--collect-evidence] [--fresh|--resume]
  # состояние: .ai/runtime/workitems/<id>/ (по WorkItem, не по workflow — параллельные задачи не делят состояние)
        — прогон (mock-провайдер). --evidence <file>: gate-evidence по
          schemas/gate-evidence.schema.json (валидируется). --collect-evidence: вывести evidence из
          вердиктов reviewer-стадий. --fresh: начать заново; без него — resume из TaskState.
          Без evidence блокирующие гейты честно не пройдены -> status blocked.
  orchestrator.py --selftest                                — QUICK на временной папке

Требует pyyaml.
"""

import hashlib
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


# --- живые провайдеры (v2.18): реальная модель по ключу из env ---
# Секреты НЕ в репо: ключ читается ТОЛЬКО из переменной окружения. Сеть — через
# системный прокси (urllib берёт HTTPS_PROXY автоматически). Без ключа — честная
# ошибка, а не тихий фолбэк на mock (иначе «живой» прогон был бы фикцией).
DEFAULT_MODELS = {"anthropic": "claude-sonnet-5", "openai": "gpt-4o"}
_MAX_TOKENS = 2048


def _http_post_json(url, headers, payload, timeout=120):
    import json as _json
    import urllib.request
    req = urllib.request.Request(url, data=_json.dumps(payload).encode("utf-8"),
                                 headers={**headers, "content-type": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:   # прокси — из env
        return _json.loads(r.read().decode("utf-8"))


def _anthropic_call(prompt, model):
    import os
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise SystemExit("ANTHROPIC_API_KEY не задан — живой прогон невозможен. "
                         "Задайте ключ в окружении или используйте --provider mock (офлайн).")
    data = _http_post_json(
        "https://api.anthropic.com/v1/messages",
        {"x-api-key": key, "anthropic-version": "2023-06-01"},
        {"model": model, "max_tokens": _MAX_TOKENS,
         "messages": [{"role": "user", "content": prompt}]})
    parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    return "\n".join(parts).strip() or "(пустой ответ модели)"


def _openai_call(prompt, model, base_url="https://api.openai.com/v1/chat/completions",
                 key_env="OPENAI_API_KEY"):
    """OpenAI Chat Completions и любой OpenAI-совместимый endpoint (DeepSeek, local, …)
    через base_url + ключ из указанной env. Секрет — только из env, не в репо/логах."""
    import os
    key = os.environ.get(key_env)
    if not key:
        raise SystemExit(f"{key_env} не задан — живой прогон невозможен. "
                         "Задайте ключ в окружении или используйте --provider mock (офлайн).")
    data = _http_post_json(
        base_url, {"authorization": f"Bearer {key}"},
        {"model": model, "max_tokens": _MAX_TOKENS,
         "messages": [{"role": "user", "content": prompt}]})
    return (data.get("choices", [{}])[0].get("message", {}).get("content") or "").strip() \
        or "(пустой ответ модели)"


def make_provider(name: str, model: str = None):
    """Вернуть callable(role_prompt)->text для провайдера.
    'mock' (по умолчанию, офлайн, детерминированный) | 'anthropic' | 'openai'.
    Живые провайдеры вызывают реальный API по ключу из env; без ключа — честная ошибка.
    ВАЖНО: живой путь опционален (opt-in через --provider) — CI/selftest офлайн на mock."""
    if name in (None, "mock"):
        return mock_provider
    if name == "anthropic":
        m = model or DEFAULT_MODELS["anthropic"]
        return lambda prompt: _anthropic_call(prompt, m)
    if name == "openai":
        m = model or DEFAULT_MODELS["openai"]
        return lambda prompt: _openai_call(prompt, m)
    if name == "openai-compatible":
        # DeepSeek / local / любой OpenAI-совместимый: base_url + ключ из env (provider-agnostic).
        import os
        base = os.environ.get("OPENAI_COMPATIBLE_BASE_URL")
        if not base:
            raise SystemExit("OPENAI_COMPATIBLE_BASE_URL не задан — для openai-совместимого "
                             "провайдера (напр. DeepSeek: https://api.deepseek.com/chat/completions) "
                             "укажите base URL в env.")
        if not model:
            raise SystemExit("--model обязателен для openai-compatible (напр. deepseek-chat).")
        return lambda prompt: _openai_call(prompt, model, base_url=base,
                                           key_env="OPENAI_COMPATIBLE_API_KEY")
    raise SystemExit(f"неизвестный провайдер '{name}' (есть: mock, anthropic, openai, openai-compatible)")


# ---------------- state ----------------

def load_state(run_dir: Path):
    p = run_dir / "TaskState.yaml"
    if p.exists():
        return yaml.safe_load(p.read_text(encoding="utf-8"))
    return None


def save_state(run_dir: Path, state: dict):
    (run_dir / "TaskState.yaml").write_text(
        yaml.safe_dump(state, allow_unicode=True, sort_keys=False), encoding="utf-8")


def append_interaction_log(child_root: Path, record: dict):
    """Append-only аудит действий ИИ (security-posture: audit-log). Пишет одну JSONL-запись
    в <child>/.ai/runtime/interaction-log.jsonl: кто/что/когда/итог. Секреты/сырые данные
    не пишем (только имена и статусы). Только дозапись — не перезапись."""
    from datetime import datetime, timezone
    log = child_root / ".ai" / "runtime" / "interaction-log.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    rec = {"ts": datetime.now(timezone.utc).isoformat(), **record}
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return log


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
                 collect=False, fresh=False, provider_name="mock", workitem_id=None,
                 budget=None, gate_ids=None):
    wf_all = yaml.safe_load((PKG / "registry" / "workflows.yaml").read_text(encoding="utf-8"))["workflows"]
    ag = yaml.safe_load((PKG / "registry" / "agents.yaml").read_text(encoding="utf-8"))
    agents_index = {a["id"]: a for a in ag.get("agents", [])}
    if workflow_id not in wf_all:
        raise SystemExit(f"неизвестный workflow '{workflow_id}' (есть: {', '.join(wf_all)})")
    w = wf_all[workflow_id]

    # Per-WorkItem состояние (Ф0): путь по id задачи, не по workflow — иначе две задачи
    # одного workflow делят состояние. Без явного id — детерминированный из хэша задачи.
    task_hash = hashlib.sha256(task_text.encode("utf-8")).hexdigest()[:12]
    wid = workitem_id or f"wi-{task_hash}"
    run_dir = child_root / ".ai" / "runtime" / "workitems" / wid
    if fresh and run_dir.exists():        # --fresh: начать с чистого состояния (иначе — resume)
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    existing = load_state(run_dir)
    # resume-идентичность: нельзя «продолжить» чужую задачу под тем же id
    if existing and existing.get("task_hash") and existing["task_hash"] != task_hash:
        raise SystemExit(f"resume-конфликт: под '{wid}' сохранена другая задача "
                         f"(task_hash {existing['task_hash']} != {task_hash}). "
                         f"Используйте другой --workitem-id или --fresh.")
    state = existing or {
        "schema_version": 1, "task_id": wid, "workitem_id": wid, "task_hash": task_hash,
        "status": "in-progress", "workflow": workflow_id, "goal": task_text,
        "execution_mode": "sequential", "current_phase": None,
        "completed_checks": [], "artifacts": [], "next_action": w["stages"][0]["id"],
    }
    # resume-идентичность по workflow тоже (та же задача, но другой маршрут — не resume)
    if existing and existing.get("workflow") != workflow_id:
        raise SystemExit(f"resume-конфликт: под '{wid}' сохранён workflow "
                         f"{existing.get('workflow')} != {workflow_id}. Используйте --fresh.")

    # execution budget (v2.38): жёсткий потолок вызовов модели; enforcement ДО вызова
    import budget as _budget_mod
    bud = budget if isinstance(budget, _budget_mod.Budget) else _budget_mod.Budget.from_dict(budget)
    budget_exceeded = None

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
        try:
            bud.charge_call()          # потолок проверяется ДО вызова — превышение = не вызываем
        except _budget_mod.BudgetExceeded as e:
            budget_exceeded = str(e)
            if verbose:
                print(f"  BUDGET: остановка перед стадией {sid}: {e}")
            break
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
                                   tested_revision=state.get("tested_revision"),
                                   gate_ids=gate_ids)   # RunPlan-гейты (треки), если переданы
    (run_dir / "GateReport.json").write_text(
        json.dumps(gates, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    state["current_phase"] = None
    state["gate_report"] = "GateReport.json"
    state["budget"] = bud.to_dict()
    if budget_exceeded:
        # бюджет исчерпан до завершения стадий — честный blocked с причиной
        state["status"] = "blocked"
        state["budget_exceeded"] = budget_exceeded
        state["unmet_gates"] = gates.get("unmet_gates", [])
    elif gates["blocked"]:
        state["status"] = "blocked"
        state["unmet_gates"] = gates["unmet_gates"]
    else:
        state["status"] = "done"
        state.pop("unmet_gates", None)
    save_state(run_dir, state)
    # append-only аудит-лог действия ИИ (security-posture: audit-log)
    # Ф0: НЕ писать сырой task_text (может содержать ПДн/секреты) — только id и хэш.
    append_interaction_log(child_root, {
        "workitem_id": wid, "task_hash": task_hash,
        "workflow": workflow_id, "status": state["status"],
        "unmet_gates": gates.get("unmet_gates", []), "provider": provider_name,
        "stages": len(state.get("completed_checks", [])),
        "model_calls": bud.model_calls,
        "budget_exceeded": bool(budget_exceeded)})
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
            "provided": ["build_passed", "lint_passed", "typecheck_passed", "tests_passed", "tested_revision"]},
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
    # --collect-evidence: вердикты reviewer-стадий собираются, НО детерминированные гейты
    # (build/lint/typecheck/tests) словом «pass» не закрываются (дисциплина evidence v2.16) —
    # QUICK остаётся blocked без реальных доказательств. Раньше тест ждал done — это была дыра.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        def verdict_provider(role_prompt):
            return "status: passed\nРезультат стадии готов согласно контракту роли."
        sc, _ = run_workflow("QUICK", "поправить опечатку", root, provider=verdict_provider,
                             verbose=False, collect=True)
        if sc["status"] == "blocked" and "implementation_verification" in sc.get("unmet_gates", []):
            print("PASS collect-evidence: слова ревьюера не закрывают детерминированные гейты -> blocked")
        else:
            ok = False; print(f"FAIL ожидался blocked на implementation_verification, получено {sc['status']}")
    # аудит-лог (v2.20): append-only запись действия ИИ появляется после прогона
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        run_workflow("QUICK", "починить опечатку", root, verbose=False)
        run_workflow("QUICK", "починить ещё раз", root, verbose=False, fresh=True)
        log = root / ".ai" / "runtime" / "interaction-log.jsonl"
        recs = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x.strip()] if log.exists() else []
        if len(recs) == 2 and all({"ts", "workflow", "status", "provider"} <= set(r) for r in recs):
            print("PASS audit-log: append-only записи действий ИИ (ts/workflow/status/provider)")
        else:
            ok = False; print(f"FAIL audit-log: ожидалось 2 валидных записи, получено {len(recs)}")

    # провайдер-адаптер (v2.18): mock офлайн; живой требует ключ (честная ошибка без него)
    import os as _os
    if make_provider("mock") is mock_provider:
        print("PASS provider: mock — офлайн-провайдер по умолчанию")
    else:
        ok = False; print("FAIL provider: mock не резолвится в mock_provider")
    _saved = _os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        make_provider("anthropic")("тест")
        ok = False; print("FAIL provider: anthropic без ключа должен падать честной ошибкой")
    except SystemExit:
        print("PASS provider: anthropic без ключа -> честная ошибка (не тихий mock)")
    finally:
        if _saved is not None:
            _os.environ["ANTHROPIC_API_KEY"] = _saved
    try:
        make_provider("bogus")
        ok = False; print("FAIL provider: неизвестный провайдер должен падать")
    except SystemExit:
        print("PASS provider: неизвестный провайдер -> ошибка")
    # openai-compatible (v2.39): DeepSeek/local через base_url; ключ из env, без — честная ошибка
    _b = _os.environ.pop("OPENAI_COMPATIBLE_BASE_URL", None)
    try:
        make_provider("openai-compatible", "deepseek-chat")
        ok = False; print("FAIL openai-compatible без BASE_URL должен падать")
    except SystemExit:
        print("PASS openai-compatible без BASE_URL -> ошибка")
    _os.environ["OPENAI_COMPATIBLE_BASE_URL"] = "https://api.deepseek.com/chat/completions"
    _kb = _os.environ.pop("OPENAI_COMPATIBLE_API_KEY", None)
    try:
        try:
            make_provider("openai-compatible")   # без model
            ok = False; print("FAIL openai-compatible без model должен падать")
        except SystemExit:
            print("PASS openai-compatible без --model -> ошибка")
        try:
            make_provider("openai-compatible", "deepseek-chat")("тест")   # base есть, ключа нет
            ok = False; print("FAIL openai-compatible без ключа должен падать")
        except SystemExit:
            print("PASS openai-compatible c BASE_URL, но без ключа -> честная ошибка")
    finally:
        if _b is None:
            _os.environ.pop("OPENAI_COMPATIBLE_BASE_URL", None)
        else:
            _os.environ["OPENAI_COMPATIBLE_BASE_URL"] = _b
        if _kb is not None:
            _os.environ["OPENAI_COMPATIBLE_API_KEY"] = _kb

    # execution budget (v2.38): max_model_calls останавливает до завершения стадий
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        st, rd = run_workflow("QUICK", "любая задача", root, verbose=False,
                              budget={"max_model_calls": 1})
        if st["status"] == "blocked" and st.get("budget_exceeded") and st["budget"]["model_calls"] == 1 \
                and len(st["completed_checks"]) == 1:
            print("PASS budget: max_model_calls=1 -> 1 стадия, blocked с budget_exceeded")
        else:
            ok = False; print(f"FAIL budget не сработал: {st.get('status')}, "
                              f"calls={st.get('budget',{}).get('model_calls')}")

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
        # провайдер: mock (по умолчанию, офлайн) | anthropic | openai (живая модель по ключу env)
        prov_name, model = "mock", None
        if "--provider" in rest:
            i = rest.index("--provider"); prov_name = rest[i + 1]; del rest[i:i + 2]
        if "--model" in rest:
            i = rest.index("--model"); model = rest[i + 1]; del rest[i:i + 2]
        workitem_id = None
        if "--workitem-id" in rest:
            i = rest.index("--workitem-id"); workitem_id = rest[i + 1]; del rest[i:i + 2]
        provider = make_provider(prov_name, model)
        wf = rest[0]
        task = rest[1] if len(rest) > 1 else ""
        root = Path(rest[2]).resolve() if len(rest) > 2 else Path.cwd()
        if prov_name != "mock":
            print(f"[live] провайдер {prov_name}, модель {model or DEFAULT_MODELS.get(prov_name)} "
                  f"— реальная модель, gates принудительны.")
        run_workflow(wf, task, root, provider=provider, provider_name=prov_name,
                     gate_evidence=gate_evidence, collect=collect, fresh=fresh,
                     workitem_id=workitem_id)
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
