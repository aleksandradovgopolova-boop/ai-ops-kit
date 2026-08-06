#!/usr/bin/env python3
from __future__ import annotations
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

Модульная структура (v3.x):
  - orchestrator_http.py      — HTTP client (_http_post_json + retry)
  - orchestrator_providers.py — Provider implementations (mock/anthropic/openai/claude-cli)
  - orchestrator_usage.py     — Usage recording (_CALL_STATS, _CALL_CONTEXT, _record_call)
  - orchestrator.py           — Workflow execution (state, core, run_workflow, selftest)
"""

import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

PKG = Path(__file__).resolve().parents[1]

# ---------------- re-exports from submodules ----------------
# Backward compatibility: `import orchestrator; orchestrator.make_provider(...)` continues to work.

sys.path.insert(0, str(PKG / "tools"))
from orchestrator_http import _http_post_json
from orchestrator_usage import (
    _CALL_STATS, _CALL_CONTEXT, _PRICE_PER_MTOK,
    _record_call, drain_call_stats, set_call_context, clear_call_context,
)
from orchestrator_providers import (
    mock_provider, DEFAULT_MODELS, _MAX_TOKENS,
    _anthropic_call, _openai_call, _claude_cli_call,
    make_provider, make_claude_cli_provider, make_openai_provider,
)


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
             "рассуждения предыдущих ролей тебе не передаются.\n"
             "В КОНЦЕ ответа верни СТРУКТУРНОЕ заключение одним JSON-блоком (source of truth, "
             "не проза): {\"schema_version\":1,\"kind\":\"reviewer-result\",\"gate\":\"<gate id>\","
             "\"status\":\"pass|warn|fail\",\"checks\":[{\"id\":\"...\",\"status\":\"pass|warn|fail\"}],"
             "\"blockers\":[\"...при fail...\"]}.\n") if is_judge else ""
    return (f"{agent_body(agent_id, agents_index)}\n"
            f"{guard}\n## Задача\n{task_text}\n\n## Опубликованные артефакты\n{pub}\n")


def _write_reviewer_json(run_dir, sid, text):
    """Из ответа judge-роли достать JSON reviewer-result и, если валиден по схеме, записать
    stage-<sid>.reviewer.json (структурный источник истины). Иначе — ничего (фолбэк на markdown)."""
    import re as _re
    m = _re.search(r"\{.*\}", text or "", _re.S)
    if not m:
        return False
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return False
    if not (isinstance(obj, dict) and obj.get("kind") == "reviewer-result"
            and obj.get("status") in ("pass", "warn", "fail")):
        return False
    try:
        sys.path.insert(0, str(PKG / "validation"))
        import validate_reviewer_result as _vrr
        if _vrr.check(obj):           # непустой список ошибок -> невалидно
            return False
    except Exception:
        return False
    (run_dir / f"stage-{sid}.reviewer.json").write_text(
        json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def run_workflow(workflow_id: str, task_text: str, child_root: Path,
                 provider=mock_provider, verbose=True, gate_evidence=None,
                 collect=False, fresh=False, provider_name="mock", workitem_id=None,
                 budget=None, gate_ids=None, signals=None):
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

        # judge-стадии: извлечь СТРУКТУРНОЕ reviewer-result из ответа (source of truth для гейтов,
        # не regex по прозе — finding аудита). Пишем stage-<sid>.reviewer.json только если он
        # валиден по схеме; иначе остаётся markdown-фолбэк в collect_evidence.
        if stage.get("review_mode") == "read-only":
            _write_reviewer_json(run_dir, sid, result)

        # handoff: judge следующей стадии увидит только published
        handoff = {
            "schema_version": 1, "from_agent": owner,
            "to_agent": stages[stages.index(stage) + 1]["owner"] if stages.index(stage) + 1 < len(stages) else None,
            "stage_from": sid,
            "published_artifacts": sorted(p.relative_to(child_root).as_posix() for p in run_dir.glob("stage-*.md")),
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
                                   gate_ids=gate_ids,   # RunPlan-гейты (треки), если переданы
                                   signals=signals)     # условный human_approval по сигналам
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
        # v2.57: judge, вернувший JSON reviewer-result, -> валидный stage-*.reviewer.json
        def json_judge(prompt):
            if "read-only" in prompt:   # judge-стадия
                return ('Заключение.\n{"schema_version":1,"kind":"reviewer-result",'
                        '"gate":"code_review","status":"pass",'
                        '"checks":[{"id":"style","status":"pass"}]}')
            return "готово"
        st_j, run_dir_j = run_workflow("QUICK", "структурный вердикт judge", root,
                                       provider=json_judge, verbose=False, fresh=True)
        rj = list(Path(run_dir_j).glob("stage-*.reviewer.json"))
        if rj:
            print("PASS judge пишет структурный reviewer.json (не regex)")
        else:
            ok = False; print("FAIL reviewer.json не создан из JSON-вердикта judge")
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
    # v3.9.0 First-class Claude Code Adapter: claude-cli провайдер, runner заменяет subprocess.run
    # (не весь вызов) — production-path (time.monotonic, json parse, _record_call, retries) проходит полностью.
    # v3.21.1 (Runtime Trust Recovery): тест ловит NameError('time') — runner возвращает объект с
    # returncode/stdout/stderr, а не текст напрямую. Если import time сломан, тест упадёт на time.monotonic().
    import json as _test_json
    class _FakeResult:
        def __init__(self, stdout="", returncode=0, stderr=""):
            self.stdout = stdout
            self.returncode = returncode
            self.stderr = stderr
    _seen = {}
    _call_stats_before = len(_CALL_STATS)
    def _fake_runner(cmd):
        _seen["cmd"] = cmd
        return _FakeResult(stdout=_test_json.dumps({
            "result": "PROPOSED-ACTIONS-JSON",
            "usage": {"input_tokens": 100, "output_tokens": 50},
            "model": "claude-opus",
            "total_cost_usd": 0.01
        }))
    _prov = make_claude_cli_provider(model="claude-opus", runner=_fake_runner)
    _out = _prov("сгенерируй tool-loop действия")
    if _out == "PROPOSED-ACTIONS-JSON":
        print("PASS claude-cli: возвращает текст-предложение модели (кит исполняет)")
    else:
        ok = False; print("FAIL claude-cli: не вернул текст провайдера")
    # v3.21.1 регрессия: _record_call вызван (usage измеряется), time.monotonic() не упал
    _call_stats_after = len(_CALL_STATS)
    if _call_stats_after > _call_stats_before:
        _last_call = _CALL_STATS[-1]
        _has_tokens = _last_call.get("input_tokens") == 100 and _last_call.get("output_tokens") == 50
        _has_cost = _last_call.get("cost_usd_est") is not None
        _has_latency = _last_call.get("latency") is not None and _last_call["latency"] >= 0
        if _has_tokens and _has_latency:
            print("PASS claude-cli: production-path пройден (time.monotonic + _record_call + usage)")
        else:
            ok = False; print(f"FAIL claude-cli: production-path неполный — tokens={_has_tokens}, latency={_has_latency}, call={_last_call}")
    else:
        ok = False; print("FAIL claude-cli: _record_call не вызван (production-path не пройден)")
    _c = _seen.get("cmd") or []
    _allowed = []
    if "--allowedTools" in _c:
        _i = _c.index("--allowedTools") + 1
        while _i < len(_c) and not _c[_i].startswith("--"):
            _allowed.append(_c[_i]); _i += 1
    _read_only = bool(_allowed) and set(_allowed) <= {"Read", "Grep", "Glob"} and "Read" in _allowed
    _no_mutate = not any(t in _c for t in ("Write", "Edit", "Bash"))
    if "-p" in _c and _read_only and _no_mutate:
        print("PASS claude-cli: read-only (Read/Grep/Glob) -> Claude читает, но НЕ мутирует/не исполняет")
    else:
        ok = False; print("FAIL claude-cli: инструменты не ограничены read-only (риск прямого действия Claude в обход кита)")
    if callable(make_provider("claude-cli")):
        print("PASS claude-cli: зарегистрирован как first-class провайдер")
    else:
        ok = False; print("FAIL claude-cli: не резолвится через make_provider")
    # v3.21.1 регрессия: retry-loop + sleep проходят без NameError
    _retry_calls = []
    def _flaky_runner(cmd):
        _retry_calls.append(1)
        if len(_retry_calls) < 3:
            return _FakeResult(returncode=1, stderr="transient error")
        return _FakeResult(stdout=_test_json.dumps({"result": "ok", "usage": {}}))
    _retry_prov = make_claude_cli_provider(runner=_flaky_runner)
    _retry_out = _retry_prov("тест retry")
    if _retry_out == "ok" and len(_retry_calls) == 3:
        print("PASS claude-cli: retry-loop + sleep работают (3 попытки, time.monotonic не упал)")
    else:
        ok = False; print(f"FAIL claude-cli: retry не сработал — calls={len(_retry_calls)}, out={_retry_out}")
        if _kb is not None:
            _os.environ["OPENAI_COMPATIBLE_API_KEY"] = _kb

    # v2.74 (finding живого прогона): _http_post_json ретраит ТРАНЗИЕНТНЫЕ сбои (SSL-timeout
    # оборвал задачу). Монкипатчим urlopen + sleep: 2 сетевых сбоя -> успех; 4xx не ретраится.
    import urllib.request as _ur
    import urllib.error as _ue
    import time as _time
    _real_open, _real_sleep = _ur.urlopen, _time.sleep
    _time.sleep = lambda *_a, **_k: None                     # без реальных пауз в тесте

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"ok": true}'

    try:
        calls = {"n": 0}
        def flaky(req, timeout=0):
            calls["n"] += 1
            if calls["n"] < 3:
                raise _ue.URLError("ssl handshake timed out")
            return _Resp()
        _ur.urlopen = flaky
        r = _http_post_json("http://x", {}, {}, retries=3)
        expect_ok = r.get("ok") is True and calls["n"] == 3
        print(("PASS" if expect_ok else "FAIL")
              + " http-retry: 2 транзиентных сбоя -> успех на 3-й попытке")
        ok = ok and expect_ok

        calls2 = {"n": 0}
        def not_found(req, timeout=0):
            calls2["n"] += 1
            raise _ue.HTTPError("http://x", 404, "not found", {}, None)
        _ur.urlopen = not_found
        try:
            _http_post_json("http://x", {}, {}, retries=3)
            ok = False; print("FAIL http-retry: 404 не должен возвращать успех")
        except _ue.HTTPError:
            good = calls2["n"] == 1                          # 4xx не ретраится
            print(("PASS" if good else "FAIL") + " http-retry: 4xx (404) не ретраится (1 попытка)")
            ok = ok and good
    finally:
        _ur.urlopen = _real_open
        _time.sleep = _real_sleep

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
