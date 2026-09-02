#!/usr/bin/env python3
"""Жизненный цикл прогона ai-ops run: старт lifecycle, resume-гейт, commit-барьер,
доставка за барьером и финализация (стоимость + статус работы), а также вынесенные из
god-модуля пробируемые хелперы delivery/resume/provider: восстановление policy на resume
(`_restore_resume_policy`), резолв моделей по роли (`_resolve_models`), регистрация
active-work (`_register_active_work`), реконсиляция незавершённой доставки
(`_reconcile_pending_delivery`) и отказ прогона без живого провайдера (`live_provider_refusal`).

Вынесено из god-модуля `ai_ops_run` без изменения поведения (чистый перенос + ре-экспорт).
Зависимости берутся из РЕАЛЬНЫХ домов (shared/lifecycle/engine/gates/governance), а не из
ai_ops_run — иначе получился бы циклический импорт. Хелперы, оставшиеся в ai_ops_run
(`_resume_context_from_handoff`, `_note_bookkeeping_error`, `_outbox_dir`, `_unresolved_intents`,
`_nonfinal_receipt_intents`, `is_service_text`, `product_task_for_resume`, `_provider_trust`,
`_load_klp_by_env`, `_with_provider_fallback`), подтягиваются лениво внутри тела функций —
это же сохраняет их патчабельность из тестов (`ai_ops_run.<name>`).
"""
from __future__ import annotations

import contextlib
import sys

from ai_ops_kit.engine.pipeline_helpers import work_produced, delivery_pending  # noqa: E402
from ai_ops_kit.engine import work_areas as _work_areas       # noqa: E402
from ai_ops_kit.lifecycle import workitem          # noqa: E402
from ai_ops_kit.lifecycle import active_work        # noqa: E402
from ai_ops_kit.shared import lifecycle_store as _ls   # noqa: E402


def _commit_barrier(rep, child_root, features_dir, fid, lifecycle_errors):
    """Commit-barrier перед доставкой: durable RunHandoff + final report + journal-checkpoint.
    K6: вынесено из run() без изменения поведения; -> (jname, handoff_ok, report_ok, plan)."""
    _jp = features_dir / fid / "lifecycle-journal.jsonl"
    _jname = str(_jp)
    _handoff_ok = False
    from ai_ops_kit.engine import run_handoff
    try:
        wt = child_root / ".ai" / "worktrees" / fid
        handoff = run_handoff.build_handoff(rep, work_root=(wt if wt.is_dir() else child_root))
        _hw = _ls.durable_write(features_dir / fid / "run-handoff.yaml", handoff,
                                require_keys=("kind", "workitem_id"), keep_backup=True)
        if _hw.get("ok"):
            _handoff_ok = True
            rep["handoff"] = {"next_action": handoff["next_action"],
                              "resume_from_revision": handoff["resume_from_revision"],
                              "open_questions": handoff["open_questions"]}
        else:
            lifecycle_errors.append(f"run-handoff durable-write: {_hw.get('error')} "
                                    "(доставка НЕ выполняется — lifecycle не зафиксирован)")
    except Exception as _e:  # noqa: BLE001
        lifecycle_errors.append(f"run-handoff build/write: {type(_e).__name__}: {_e}")
    if lifecycle_errors:
        rep["lifecycle_errors"] = lifecycle_errors
    # durable final report (ДО доставки) — второй барьер
    _rw = _ls.durable_write_json(features_dir / fid / "run-report.json", rep, keep_backup=True)
    _report_ok = _rw.get("ok")
    if not _report_ok:
        rep.setdefault("lifecycle_errors", [])
        rep["lifecycle_errors"].append(f"run-report durable-write: {_rw.get('error')} "
                                       "(доставка НЕ выполняется)")
    # journal checkpoint: готовность к доставке + прошли ли барьеры
    _plan = rep.get("delivery_plan")
    _ls.journal_append(_jname, {"kind": "ready_for_delivery", "run_id": fid, "workitem_id": fid,
                                "ready_for_delivery": bool(_plan),
                                "handoff_durable": _handoff_ok, "report_durable": bool(_report_ok),
                                "commit": (rep.get("commit") or {}).get("sha")})
    return _jname, _handoff_ok, _report_ok, _plan


def _start_lifecycle(features_dir, fid, task_text, signals, plan, engine, base, resume, execute,
                     saved_task, sandbox, baseline_diff, require_fix, author, review, open_pr,
                     write_scope, max_steps, base_binding):
    """Durable lifecycle-start: workitem.start + RunPlan/run-settings (write-barrier) + journal
    run_start + per-run снимок. K6: вынесено из run(). -> (attempt_id, error|None)."""
    workitem.start(str(features_dir), fid, task_text,
                   task_type=signals.get("task_type"), risk=signals.get("risk"))
    # v3.0.15 (finding аудита P1): RunPlan — write BARRIER. Сбой durable-записи -> прогон НЕ начат
    # (0 вызовов модели): без надёжного плана нельзя доказать routing/гейты/resume.
    _pw = _ls.durable_write(features_dir / fid / "run-plan.yaml", plan, require_keys=("workitem_id",))
    if not _pw.get("ok"):
        return None, {"schema_version": 1, "kind": "execution-pipeline", "workitem_id": fid,
                "status": "error", "ready_for_pr": False,
                "error": f"lifecycle fail-closed: не удалось надёжно сохранить RunPlan ({_pw.get('error')}) "
                         "— прогон не начат (0 вызовов модели)"}
    # v3.0.14/v3.1 (trace v0.2): event journal — run_start. attempt_id = попытка прогона WorkItem
    # (resume/повтор -> новая попытка), детерминированно из числа снимков run-history.
    _jp = features_dir / fid / "lifecycle-journal.jsonl"
    _att = len(list((features_dir / fid / "run-history").glob("run-*.yaml"))) + 1
    _attempt_id = f"{fid}#a{_att}"
    _ls.journal_append(_jp, {"kind": "run_start", "run_id": fid, "workitem_id": fid,
                             "attempt_id": _attempt_id, "task_type": signals.get("task_type"),
                             "engine": engine, "base": base, "resume": bool(resume)})
    # v3.0-rc2 (P0.1): сохраняем ЭФФЕКТИВНУЮ политику прогона -> resume восстановит её, а не
    # переклассифицирует/деградирует до дефолтов. provider/model НЕ храним (runtime-выбор/секрет).
    if execute:
        _settings = {
            "schema_version": 1, "kind": "run-settings", "workitem_id": fid,
            # F-027: ПРОДУКТОВАЯ задача прогона хранится явно и переживает продолжение. Раньше
            # её не было нигде: signals пишутся без task_text, RunHandoff несёт только
            # next_action — и resume брал задачей служебное «что осталось». На продолжении
            # сохранённая задача не переписывается: она — идентичность работы, а не аргумент вызова.
            "task": (saved_task if (resume and saved_task) else task_text),
            "signals": {k: v for k, v in signals.items() if k != "task_text"},
            "policy": {"sandbox": sandbox, "baseline_diff": baseline_diff, "require_fix": require_fix,
                       "author": author, "review": review, "open_pr": open_pr,
                       "write_scope": write_scope, "max_steps": max_steps, "engine": engine,
                       "base": base,   # v3.0.2 (P0): резолвнутый base_ref (back-compat)
                       "base_binding": base_binding},   # v3.0.9 (P0.2): полный BaseBinding (ref+sha+mode+source)
        }
        # v3.0.12 (finding аудита блок B): run-settings — источник истины для resume, пишем DURABLE
        # (атомарно + fsync + перечитывание). Сбой записи -> FAIL-CLOSED отказ (без надёжной policy
        # resume восстановит мусор/дефолты). require_keys гарантируют, что перечитанный файл цел.
        _ws = _ls.durable_write(features_dir / fid / "run-settings.yaml", _settings,
                                require_keys=("kind", "policy", "signals"))
        if not _ws.get("ok"):
            return None, {"schema_version": 1, "kind": "execution-pipeline", "workitem_id": fid,
                    "status": "error", "ready_for_pr": False,
                    "error": (f"lifecycle fail-closed: не удалось надёжно сохранить run-settings "
                              f"({_ws.get('error')}) — без durable policy resume небезопасен; прогон "
                              "не начат")}
        # v3.0-rc4 (P0.1): per-run СНИМОК для аудита (не только последнее состояние). Нумеруем по
        # числу уже сохранённых снимков — детерминированно, без времени (совместимо с workflow-песочницей).
        _hist = features_dir / fid / "run-history"
        _hist.mkdir(parents=True, exist_ok=True)
        _n = len(list(_hist.glob("run-*.yaml"))) + 1
        _ls.durable_write(_hist / f"run-{_n:03d}.yaml", _settings)   # v3.0.14 (#2): атомарно
    return _attempt_id, None


def _resume_gate(child_root, fid, base, force_resume, resume):
    """Resume-preflight гейт: продолжать WorkItem поверх подтверждённой работы или честный ранний
    выход (can_resume/base-rewritten/revalidation). K6: вынесено из run(). -> (pf, resume_ctx, error|None)."""
    resume_ctx = None
    pf = None
    if resume:
        from ai_ops_kit.engine import run_handoff
        pf = run_handoff.resume_preflight(child_root, fid, base=base)
        if not pf["can_resume"]:
            return None, None, {"schema_version": 1, "kind": "execution-pipeline", "workitem_id": fid,
                    "status": "error", "engine": "pipeline", "ready_for_pr": False,
                    "error": "resume невозможен: " + "; ".join(pf["reasons"]),
                    "resume": {"requested": True, "resumed": False, "can_resume": False,
                               "reasons": pf["reasons"]}}
        # v3.0.10 (finding аудита P0): base ПЕРЕПИСАН (force-push назад / пересоздан на несвязанном
        # SHA — сохранённый base_sha исходного прогона больше не предок текущего HEAD базы). Это НЕ
        # fast-forward: продолжать старую работу против ДРУГОЙ базы и выдать её за проверенную нельзя.
        # force_resume этот случай НЕ снимает (иначе можно тихо переобозначить базу) — только явный
        # replan (пересобрать план + переисполнить с новой базы) либо отмена.
        # v3.0.14 (finding аудита #1, вариант B): base СДВИНУЛСЯ с прошлого прогона — переписан
        # (rewrite) ИЛИ ушёл вперёд (fast-forward). В ОБОИХ случаях старая работа НЕ интегрирована с
        # новой базой: resume ПЕРЕИСПОЛЬЗУЕТ worktree, форкнутый от старой базы (не пере-форкает), а
        # baseline считался на старой — отдать PR против новой базы нельзя. Блок на resume-пути НЕ
        # снимается ни force_resume, ни replan (обе модификации resume реиспользуют устаревший worktree).
        # Recourse — СВЕЖИЙ прогон от новой базы (без --resume; --discard заменит устаревшую ветку):
        # он пере-форкает worktree от новой базы. Авто-интеграция при resume (rebase onto B + повтор
        # проверок) — запланирована на v3.1.
        if pf.get("base_rewritten") or pf.get("base_moved"):
            _kind = ("переписан (force-push/пересоздание)" if pf.get("base_rewritten")
                     else "ушёл вперёд (fast-forward)")
            return None, None, {"schema_version": 1, "kind": "execution-pipeline", "workitem_id": fid,
                    "status": "blocked", "engine": "pipeline", "ready_for_pr": False,
                    "error": (f"resume заблокирован: base {_kind} с прошлого прогона — старую работу "
                              "нельзя выдать за проверенную против новой базы (worktree форкнут от "
                              "старой базы и не интегрирован с новой). Ни force_resume, ни replan это "
                              # B2-10: здесь назывались флаги ВНУТРЕННЕЙ точки входа (`--resume`,
                              # `--discard`), которых у `ai-ops` нет вовсе. Человек читает это
                              # сообщение, работая через `ai-ops`, и набирает несуществующее.
                              "НЕ снимают. Нужен СВЕЖИЙ прогон от новой базы: удалите ветку "
                              f"прошлого прогона (`git branch -D ai-ops/{fid}`) и запустите "
                              f"`ai-ops run . --feature {fid} --execute`. " + "; ".join(pf["reasons"])),
                    "resume": {"requested": True, "resumed": False,
                               "base_rewritten": bool(pf.get("base_rewritten")),
                               "base_moved": bool(pf.get("base_moved")),
                               "revalidation_needed": True, "reasons": pf["reasons"]}}
        # ЧЕСТНОСТЬ: база/состояние изменились -> НЕ продолжаем молча на устаревшем evidence.
        if pf["revalidation_needed"] and not force_resume:
            return None, None, {"schema_version": 1, "kind": "execution-pipeline", "workitem_id": fid,
                    "status": "blocked", "engine": "pipeline", "ready_for_pr": False,
                    "error": "resume требует ревалидации (база/состояние изменились с прошлого "
                             "прогона) — перепроверь и запусти с force_resume=True (--force), "
                             "чтобы продолжить осознанно",
                    "resume": {"requested": True, "resumed": False, "revalidation_needed": True,
                               "reasons": pf["reasons"]}}
        # _resume_context_from_handoff остаётся в ai_ops_run (используется тестами) — ленивый импорт.
        from ai_ops_kit.engine.ai_ops_run import _resume_context_from_handoff
        resume_ctx = _resume_context_from_handoff(child_root, fid)
    return pf, resume_ctx, None


def _finalize_run_cost(rep, orchestrator, model, jname, fid, attempt_id, signals, plan,
                       model_resolution, child_root):
    """Агрегат run_cost (tokens/latency/cost) из вызовов модели + usage-ledger + очистка
    call-context. K6: вынесено из run(); мутирует rep, без ранних выходов."""
    # _note_bookkeeping_error остаётся в ai_ops_run (используется и forbidden-функциями/тестами) —
    # ленивый импорт, чтобы не замкнуть ai_ops_run <-> ai_ops_run_lifecycle.
    from ai_ops_kit.engine.ai_ops_run import _note_bookkeeping_error
    # v3.1 (trace v0.2): run_cost — агрегат tokens/latency/cost из вызовов модели (наблюдаемость).
    _stats_error = None
    try:
        _stats = orchestrator.drain_call_stats()
    except Exception as _se:  # noqa: BLE001 — сбор статистики не должен ронять уже сделанный прогон
        # но «не собрали» != «расхода не было»: инвариант Usage Truth требует unavailable,
        # а не тихий ноль.
        _stats, _stats_error = [], f"{type(_se).__name__}: {_se}"[:200]
        rep["run_cost"] = {"status": "unavailable", "reason": _stats_error}
    if _stats:
        _in = sum(s.get("input_tokens") or 0 for s in _stats)
        _out = sum(s.get("output_tokens") or 0 for s in _stats)
        _lat = round(sum(s.get("latency_s") or 0 for s in _stats), 3)
        _costs = [s.get("cost_usd_est") for s in _stats if s.get("cost_usd_est") is not None]
        _cost = round(sum(_costs), 6) if _costs else None
        _cost_rep = {"calls": len(_stats), "input_tokens": _in, "output_tokens": _out,
                     "latency_s": _lat, "cost_usd_est": _cost, "model": model}
        rep["cost"] = _cost_rep
        _ls.journal_append(jname, {"kind": "run_cost", "run_id": fid, "workitem_id": fid,
                                    "attempt_id": attempt_id, **_cost_rep})
        # v3.10.0 Usage Truth: персист КАЖДОГО вызова (writer/reviewer/fix-loop/fallback/escalation)
        # в ledger задачи + продукта. Честный usage_status; неизвестное -> unavailable, не 0.
        # v3.24.0 Cost & Architecture Accuracy: extra_context штампуется на все записи —
        # task_type/workflow/risk/size/writer_tier/execution_mode/stack для economic alternatives.
        try:
            from ai_ops_kit.shared import usage_ledger as _ul
            _extra = {
                "task_type": signals.get("task_type"),
                "workflow": (plan.get("base_workflow") if isinstance(plan, dict) else None),
                "risk": signals.get("risk"),
                "size": signals.get("size"),
                "writer_tier": ((model_resolution or {}).get("writer") or {}).get("tier"),
                "execution_mode": "sequential" if signals.get("_sequence_internal") else "single",
                "stack": ",".join(s.get("language", "") for s in (signals.get("_stacks") or [])) or None,
            }
            _ul.append(child_root, fid, _stats, run_id=fid, extra_context={k: v for k, v in _extra.items() if v is not None})
        except Exception as _ue:  # noqa: BLE001 — учёт usage не должен ронять прогон...
            # ...но и пропасть молча не должен: занижённая стоимость, поданная как факт, —
            # это нарушение той самой Usage Truth, ради которой ledger и существует.
            _note_bookkeeping_error(rep, "usage_ledger.append", _ue)
    # СРЕЗ engine РАТЧЕТА 2026-08-12: здесь стоял `try/except Exception: pass` без причины.
    # Подавлять нечего: `clear_call_context` — это `dict.clear()` над модульным `_CALL_CONTEXT`
    # (`providers/orchestrator_usage.py`), он не бросает. Пустой `except` защищал от
    # несуществующего сбоя и при этом был бы единственным местом, где утрата контекста вызова
    # (Usage Truth: role/trigger/provider) прошла бы молча, если бы функция когда-нибудь стала
    # бросать. Снят, а не задокументирован: подавление без риска — это шум, а не решение.
    orchestrator.clear_call_context()


def _finalize_run(rep, fid, child_root, jname, attempt_id, aw_path):
    """Финализация прогона: событие run_completed + журнал run_end + вывод статуса работы
    (done/blocked) + снятие active-work с учёта. K6: вынесено из run(); -> rep."""
    # v3.16.0 Development Culture Guardrails (WP5): каждый прогон завершается SessionRecommendation
    # (гигиена сессии/контекста) с точной командой. ADVISE-ONLY: НЕ блокирует прогон/доставку.
    # v3.38 (W3.2): ядро НЕ импортирует спутники — session recommendation через событие run_completed.
    # Подписчик (engops/session_guardrails) реагирует синхронно и пишет в rep in-place.
    from ai_ops_kit.shared.events import emit as _emit
    try:
        _emit("run_completed", {
            "event_type": "run_completed",
            "workitem_id": fid,
            "child_root": str(child_root),
            "status": rep.get("overall_status") or ("ready" if rep.get("ready_for_pr") else "not-ready"),
            "ready_for_pr": bool(rep.get("ready_for_pr")),
            "report": rep,
        })
    except Exception:  # noqa: BLE001,S110 — событие ADVISE-ONLY: его утрата не меняет вердикт
        pass
    # run_end (исход прогона, включая итог доставки)
    _ls.journal_append(jname, {"kind": "run_end", "run_id": fid, "workitem_id": fid,
                                "attempt_id": attempt_id,
                                "status": rep.get("overall_status") or ("ready" if rep.get("ready_for_pr")
                                                                        else "not-ready"),
                                "ready_for_pr": bool(rep.get("ready_for_pr")),
                                "commit": (rep.get("commit") or {}).get("sha")})
    # F-012: `done` только когда работа действительно доведена. NOT_READY -> blocked, иначе
    # `ai-ops status` показывает пустоту при незакрытых гейтах и ненаписанном коде.
    _ready = bool(rep.get("ready_for_pr"))
    _unmet = (rep.get("gates") or {}).get("unmet") or []
    # НАХОДКА ИИ-СРЕДЫ (ежедневная): факт работы брался из счётчика write-операций брокера, а
    # писать могут иначе — writer уровня `claude -p` своими инструментами, `sed -i` в shell,
    # и модель может закоммитить сама. Тогда `applied_writes == 0` при живом коммите, и статус
    # работы становился «blocked: код не написан — правок 0». По отчёту выглядело, будто кит не
    # работает, хотя он работал. Ground truth — git: коммит и его файлы.
    _wrote = work_produced(rep)
    if _ready:
        _st, _why = "done", None
    elif _wrote:
        _st, _why = "blocked", f"гейты не закрыты: {', '.join(_unmet) or 'см. отчёт'}"
    else:
        _st, _why = "blocked", "код не написан — правок 0 (нужен живой провайдер или внешний исполнитель)"
    # B2-20 (повтор B2-12, живой прогон 14.08.2026): `resume` завершённой-но-НЕДОСТАВЛЕННОЙ работы
    # заново звал писателя, получал ноль правок — потому что делать уже нечего — и хоронил готовый
    # READY_FOR_PR в `blocked: код не написан`. Работа с коммитом на ветке пропадала из активного
    # состояния, и владелец видел «кит не справился» там, где кит справился и ждал доставки.
    # Продолжение поверх существующей ветки без новых правок — это НЕ «код не написан».
    if _st == "blocked" and delivery_pending(rep):
        print("  работа прошлого прогона на ветке, дописывать нечего — нужна ДОСТАВКА, а не "
              "повторный прогон: запусти с open_pr (и GITHUB_TOKEN), либо открой PR из ветки сам")
        with contextlib.redirect_stdout(sys.stderr):
            active_work.finish_cmd(aw_path, fid, status="blocked",
                                   reason="ждёт доставки: работа готова на ветке, новых правок нет")
        _ls.merge_bookkeeping_losses(rep)
        return rep
    with contextlib.redirect_stdout(sys.stderr):
        active_work.finish_cmd(aw_path, fid, status=_st, reason=_why)
    _ls.merge_bookkeeping_losses(rep)   # утраченные записи журнала называются в отчёте, а не пропадают
    return rep


def _deliver(ctx, rep, *, plan, handoff_ok, report_ok, jname, fid):
    """Транзакционная доставка за commit-барьером: governance-gate -> DeliveryIntent -> внешнее
    действие (PR, идемпотентно) -> DeliveryReceipt. K6: вынесено из run() без изменения поведения.

    DELIVERY — только за барьером: план готов И обе критические записи durable. v3.0.16 Phase A:
    DELIVERY OUTBOX — внешнее действие (PR) и локальная запись НЕ атомарны, поэтому durable
    DeliveryIntent -> external delivery (идемпотентно) -> durable DeliveryReceipt; если запись
    Receipt упала -> outcome_unknown + reconciliation_required. GOVERNANCE (Фаза 4): решение политики
    впрыскивается здесь (decision_log ВСЕГДА; блокирует только в enforcement=block, по умолчанию
    observe). Мутирует `rep` на месте (delivery/overall_status/lifecycle_errors); -> None.
    """
    from ai_ops_kit.engine import execution_pipeline
    # _outbox_dir/_unresolved_intents остаются в ai_ops_run (последний нужен и forbidden-функции
    # _reconcile_pending_delivery) — ленивый импорт, чтобы не замкнуть импорт-граф.
    from ai_ops_kit.engine.ai_ops_run import _outbox_dir, _unresolved_intents
    child_root, features_dir = ctx.child_root, ctx.features_dir
    _gate = None
    if plan and handoff_ok and report_ok:
        from ai_ops_kit.governance import enforcement as _enf
        _gate = _enf.gate_delivery(child_root, target=fid)
        rep.setdefault("governance", {})["delivery"] = _gate
    if _gate and _gate.get("blocked"):
        rep["delivery"] = {"requested": True, "status": "blocked-by-policy",
                           "reason": f"policy: {_gate.get('reason')} — доставка остановлена "
                                     "governance (режим block)"}
        rep["overall_status"] = "delivery-blocked"
        _ls.durable_write_json(features_dir / fid / "run-report.json", rep)
    elif plan and handoff_ok and report_ok:
        import hashlib as _hl
        from ai_ops_kit.gates import concurrency_preflight as _cpp
        _branch = plan["work_branch"]
        _csha = plan["committed_sha"]
        # repository identity (owner/name из origin) — часть СТРОГОЙ идентичности доставки
        _ru = execution_pipeline._git(child_root, "remote", "get-url", "origin")
        _orn = _cpp._parse_owner_repo(_ru[1]) if _ru[0] == 0 else None
        _repo = f"{_orn[0]}/{_orn[1]}" if _orn else None
        # delivery_id детерминирован по (repository, wid, branch, commit) — идемпотентный ключ
        _did = _hl.sha256(f"{_repo}:{fid}:{_branch}:{_csha}".encode("utf-8")).hexdigest()[:16]
        _obx = _outbox_dir(features_dir, fid)
        _ip = _obx / f"{_did}.intent.yaml"
        _rp = _obx / f"{_did}.receipt.yaml"
        # v3.0.17 (P0): НЕразрешённая доставка (Intent без Receipt) на ЭТОЙ ветке (иной delivery_id)
        # БЛОКИРУЕТ новую внешнюю доставку до reconciliation — не затираем неизвестный исход.
        _blocking = [d for (d, _i) in _unresolved_intents(features_dir, fid, branch=_branch) if d != _did]
        if _blocking:
            rep["delivery"] = {"requested": True, "status": "blocked-unresolved-delivery",
                               "reason": f"есть неразрешённая доставка {_blocking[0]} на ветке {_branch} "
                                         "(нет DeliveryReceipt) — новая доставка запрещена до reconciliation"}
            rep["overall_status"] = "delivery-failed"
            _ls.durable_write_json(features_dir / fid / "run-report.json", rep)
        else:
            # DeliveryIntent (BARRIER) со СТРОГОЙ идентичностью
            _intent = {"schema_version": 1, "kind": "DeliveryIntent", "delivery_id": _did,
                       "workitem_id": fid, "repository": _repo, "branch": _branch,
                       "base_ref": plan["base_ref"], "base_sha": plan["base_sha"],
                       "commit_sha": _csha, "status": "intended"}
            _iw = _ls.durable_write(_ip, _intent,
                                    require_keys=("kind", "delivery_id", "commit_sha", "repository"),
                                    keep_backup=True)
            if not _iw.get("ok"):
                rep["delivery"] = {"requested": True, "status": "blocked-lifecycle",
                                   "reason": f"DeliveryIntent не зафиксирован durable ({_iw.get('error')}) "
                                             "— внешнее действие не выполняется"}
                rep["overall_status"] = "delivery-failed"
                _ls.durable_write_json(features_dir / fid / "run-report.json", rep)
            else:
                _ls.journal_append(jname, {"kind": "delivery_intent", "run_id": fid, "workitem_id": fid,
                                           "delivery_id": _did, "branch": _branch, "commit": _csha,
                                           "repository": _repo})
                # ВНЕШНЕЕ ДЕЙСТВИЕ (идемпотентно; delivery_id вшивается в тело PR)
                _dv = execution_pipeline._deliver_pr(
                    plan["work_root"], _branch, plan["base_ref"], plan["base_sha"],
                    plan["base_binding"], _csha, plan["wid"], plan["task"], delivery_id=_did)
                _st = _dv.get("status")
                _pr = _dv.get("pr") or {}
                if _st == "outcome_unknown":
                    # неоднозначный POST -> НЕ пишем confirmed Receipt; помечаем Intent (BARRIER).
                    _uw = _ls.durable_write(_ip, {**_intent, "status": "outcome_unknown",
                                                  "reconciliation_required": True},
                                            require_keys=("kind", "delivery_id", "status"))
                    rep["delivery"] = {**_dv, "delivery_id": _did, "reconciliation_required": True,
                                       "intent_marker_durable": bool(_uw.get("ok"))}
                    rep["overall_status"] = "delivery-outcome-unknown"
                    _ls.durable_write_json(features_dir / fid / "run-report.json", rep)
                    _ls.journal_append(jname, {"kind": "delivery_outcome_unknown", "run_id": fid,
                                               "workitem_id": fid, "delivery_id": _did, "cause": "ambiguous-post"})
                else:
                    _delivered = _st in ("opened", "updated")
                    _remote_sha = _pr.get("head_sha")
                    _sha_ok = (_remote_sha == _csha) if _remote_sha else None
                    _receipt = {"schema_version": 1, "kind": "DeliveryReceipt", "delivery_id": _did,
                                "workitem_id": fid, "repository": _repo, "branch": _branch,
                                "commit_sha": _csha, "base_ref": plan["base_ref"], "status": _st,
                                "remote_sha": _remote_sha, "sha_verified": _sha_ok,
                                "pr_url": _pr.get("url"), "pr_number": _pr.get("number")}
                    # v3.38 (K7): инварианты DeliveryReceipt — fail-closed.
                    from ai_ops_kit.gates.invariants import check_invariant as _ci
                    _del_breaches = []
                    for _inv_id, _kw in [
                        ("INV-DELIVERY-001", {"sha_verified": _sha_ok, "remote_sha": _remote_sha}),
                        ("INV-DELIVERY-002", {"status": _st, "sha_verified": _sha_ok}),
                        ("INV-DELIVERY-003", {"commit_sha": _csha, "branch": _branch}),
                    ]:
                        try:
                            if not _ci(_inv_id, **_kw):
                                _del_breaches.append(_inv_id)
                        except (KeyError, TypeError):
                            pass
                    if _del_breaches:
                        _receipt["invariant_breaches"] = _del_breaches
                    _cw = _ls.durable_write(_rp, _receipt,
                                            require_keys=("kind", "delivery_id", "status"), keep_backup=True)
                    if _cw.get("ok"):
                        _ls.durable_write(_ip, {**_intent, "status": "completed"})   # receipt авторитетен
                        rep["delivery"] = {**_dv, "delivery_id": _did, "remote_sha": _remote_sha,
                                           "sha_verified": _sha_ok,
                                           "receipt": f"features/{fid}/delivery-outbox/{_did}.receipt.yaml"}
                        rep["overall_status"] = "delivered" if _delivered else "delivery-failed"
                        _ls.journal_append(jname, {"kind": "delivery_receipt", "run_id": fid,
                                                   "workitem_id": fid, "delivery_id": _did, "status": _st,
                                                   "delivered": _delivered, "remote_sha": _remote_sha,
                                                   "pr_url": _pr.get("url")})
                        _dw = _ls.durable_write_json(features_dir / fid / "run-report.json", rep,
                                                     keep_backup=True)
                        if not _dw.get("ok"):
                            rep.setdefault("lifecycle_errors", [])
                            rep["lifecycle_errors"].append(f"delivery-report durable-write: {_dw.get('error')}")
                    else:
                        # ВНЕШНЕЕ ДЕЙСТВИЕ ВЫПОЛНЕНО, Receipt НЕ сохранён -> outcome_unknown (Intent BARRIER).
                        # Даже если и эта запись упадёт: reconciliation ловит Intent-БЕЗ-Receipt по факту.
                        _uw = _ls.durable_write(_ip, {**_intent, "status": "outcome_unknown",
                                                      "reconciliation_required": True,
                                                      "observed": {"status": _st, "pr_url": _pr.get("url")}},
                                                require_keys=("kind", "delivery_id", "status"))
                        rep["delivery"] = {**_dv, "delivery_id": _did, "status": "outcome_unknown",
                                           "reconciliation_required": True,
                                           "intent_marker_durable": bool(_uw.get("ok")),
                                           "reason": f"внешнее действие выполнено, но DeliveryReceipt не "
                                                     f"зафиксирован durable ({_cw.get('error')}) — исход "
                                                     "сверится с remote при следующем прогоне (идемпотентно)"}
                        rep["overall_status"] = "delivery-outcome-unknown"
                        _ls.durable_write_json(features_dir / fid / "run-report.json", rep)
                        _ls.journal_append(jname, {"kind": "delivery_outcome_unknown", "run_id": fid,
                                                   "workitem_id": fid, "delivery_id": _did,
                                                   "cause": "receipt-write-failed"})
    elif plan and not (handoff_ok and report_ok):
        # барьер не пройден -> доставку запрещаем fail-closed (не отдаём непрозафиксированное наружу)
        rep["delivery"] = {"requested": True, "status": "blocked-lifecycle",
                           "reason": "durable RunHandoff/final report не зафиксированы — доставка "
                                     "запрещена до надёжной фиксации доказательств и состояния"}
        rep["overall_status"] = "delivery-failed"
        _ls.durable_write_json(features_dir / fid / "run-report.json", rep)


def live_provider_refusal(res, explicit):
    """F-026 (поле 2026-08-15, дочка ai-ops-cockpit): исполняющий прогон с заглушкой — ложный green.

    `resume --execute` уходил в `mock`: правок продукта ноль, а отчёт говорил `resumed=True`, и
    отличить это от работы можно было только в `--json` («provider»: «mock»). Печати решения мало:
    прогон, который НЕ ВЫЗЫВАЕТ модель, не должен доводиться до вердикта и коммита служебных файлов.
    Поэтому: живого нашли — идём; не нашли — ОТКАЗ с названной причиной. Офлайн остаётся доступен,
    но становится осознанным (`--provider mock`).

    Отказ только для случая `source == "fallback"` — автовыбор реально искал и не нашёл. Явный
    выбор человека и выключенный автовыбор (`AI_OPS_PROVIDER_AUTORESOLVE=0`, pytest/CI —
    офлайн-детерминизм) остаются как были. -> текст отказа или None."""
    if explicit or not isinstance(res, dict):
        return None
    if res.get("provider") != "mock" or res.get("source") != "fallback":
        return None
    checked = "; ".join(res.get("checked") or []) or "проверять было нечего"
    return ("живого провайдера не нашлось, а с заглушкой (mock) прогон не вызывает модель и правок "
            "не делает — отчёт об успехе был бы ложным. Проверено: " + checked
            + ". Дайте живого: ключ провайдера в окружении и `providers.default` в .ai-ops.yaml, "
              "либо локальный `claude` в PATH. Нужен именно офлайн — попросите его прямо: "
              "`--provider mock`.")


def _reconcile_pending_delivery(features_dir, fid, child_root):
    """v3.0.16/v3.0.17 (finding аудита #2/P0): сверить с remote КАЖДУЮ незавершённую доставку (Intent без
    Receipt) и дописать DeliveryReceipt — но ТОЛЬКО при СТРОГОМ совпадении идентичности PR с Intent
    (repository + head.sha == commit_sha + base.ref). PR той же ветки, но с ДРУГИМ коммитом НЕ
    засчитывается за подтверждение старой доставки. Все записи — обязательные барьеры (реконсиляция НЕ
    рапортует успех, если Receipt фактически не сохранился). Идемпотентно, ничего не создаёт на remote.
    -> список исходов по delivery_id | None (нечего сверять)."""
    from pathlib import Path as _P
    # _outbox_dir/_unresolved_intents/_nonfinal_receipt_intents остаются в ai_ops_run (первые два
    # нужны и forbidden-функции/тестам) — ленивый импорт, чтобы не замкнуть импорт-граф.
    from ai_ops_kit.engine.ai_ops_run import (
        _outbox_dir, _unresolved_intents, _nonfinal_receipt_intents)
    # незавершённые (Intent без Receipt) + #400: не-финальные receipt (sha_verified != True) —
    # ложный false из гонки P0 больше не залипает, а перепроверяется против свежего remote.
    pending = _unresolved_intents(features_dir, fid) + _nonfinal_receipt_intents(features_dir, fid)
    if not pending:
        return None
    from ai_ops_kit.delivery import pr_open
    d = _outbox_dir(features_dir, fid)
    jn = _P(features_dir) / fid / "lifecycle-journal.jsonl"
    results = []
    for did, intent in pending:
        rp = d / f"{did}.receipt.yaml"
        branch = intent.get("branch")
        try:
            rc = pr_open.reconcile_delivery(child_root, branch)
        except Exception as e:  # noqa: BLE001
            results.append({"delivery_id": did, "status": "unavailable", "reason": str(e)})
            continue
        _base = {"schema_version": 1, "kind": "DeliveryReceipt", "delivery_id": did, "workitem_id": fid,
                 "repository": intent.get("repository"), "branch": branch,
                 "commit_sha": intent.get("commit_sha"), "base_ref": intent.get("base_ref"),
                 "reconciled": True}
        if rc.get("status") == "unavailable":
            results.append({"delivery_id": did, "status": "unavailable"})   # оставляем на следующий прогон
            continue
        if rc.get("status") == "absent":
            _w = _ls.durable_write(rp, {**_base, "status": "not-delivered", "remote_sha": None},
                                   require_keys=("kind", "delivery_id", "status"))
            results.append({"delivery_id": did, "status": "reconciled-absent" if _w.get("ok")
                            else "receipt-write-failed"})
            continue
        # rc.status == found: СТРОГАЯ сверка идентичности (не доверяем имени ветки)
        _idn = (rc.get("repository") == intent.get("repository")
                and rc.get("head_sha") == intent.get("commit_sha")
                and rc.get("base_ref") == intent.get("base_ref"))
        if not _idn:
            # PR ветки есть, но это НЕ та доставка (другой SHA/base/repo) -> НЕ подтверждаем старую.
            _w = _ls.durable_write(rp, {**_base, "status": "mismatch", "remote_sha": rc.get("head_sha"),
                                        "remote_base_ref": rc.get("base_ref"),
                                        "remote_repository": rc.get("repository"), "sha_verified": False,
                                        "pr_url": rc.get("url"), "pr_number": rc.get("number")},
                                   require_keys=("kind", "delivery_id", "status"), keep_backup=True)
            results.append({"delivery_id": did, "status": "mismatch" if _w.get("ok")
                            else "receipt-write-failed", "remote_sha": rc.get("head_sha")})
            continue
        # R-41: `sha_verified` отвечает на вопрос «это наш коммит», и только на него. Отдельно
        # записываем, ПРОВЕРЯЛ ли доставку кто-нибудь: ноль прогонов больше не выглядит как зелёный.
        # Поля-факты (`checks_status`/`total`/`failed`) и поле-вердикт (`checks_verified`) пишутся из
        # одного источника — `pr_open.checks_verified()`, чтобы вердикт нельзя было проставить мимо фактов.
        _chk = rc.get("checks") or {"status": "unavailable"}
        _w = _ls.durable_write(rp, {**_base, "status": "reconciled", "remote_sha": rc.get("head_sha"),
                                    "sha_verified": True, "pr_url": rc.get("url"),
                                    "pr_number": rc.get("number"), "pr_state": rc.get("pr_state"),
                                    "merged": rc.get("merged"),
                                    "checks_status": _chk.get("status"),
                                    "checks_total": _chk.get("total"),
                                    "checks_failed": _chk.get("failed"),
                                    "checks_verified": pr_open.checks_verified(_chk)},
                               require_keys=("kind", "delivery_id", "status"), keep_backup=True)
        if not _w.get("ok"):
            results.append({"delivery_id": did, "status": "receipt-write-failed"})   # НЕ рапортуем успех
            continue
        _ls.journal_append(jn, {"kind": "delivery_reconciled", "run_id": fid, "workitem_id": fid,
                                "delivery_id": did, "pr_url": rc.get("url"), "remote_sha": rc.get("head_sha")})
        results.append({"delivery_id": did, "status": "reconciled", "pr_url": rc.get("url")})
    return results


def _register_active_work(child_root, signals, write_scope, fid, session, lifecycle_errors,
                          takeover=False, takeover_reason=None):
    """Регистрация active-work + concurrency-preflight (координация параллельных сессий).
    K6: вынесено из run() без изменения поведения. -> (aw_path, preflight, error|None)."""
    aw_path = child_root / ".ai" / "runtime" / "active-work.yaml"
    # v3.0.12 (finding аудита блок B): общий реестр координации повреждён -> FAIL-CLOSED (не стартуем
    # вслепую: пустая карта скрыла бы чужую активную работу и две сессии столкнулись бы). Проверяем
    # ДО preflight/register, чтобы register не наткнулся на corrupt-raise без обработки.
    _awg = _ls.load_guarded(aw_path, kind="active-work")
    if _awg["state"] == "corrupt":
        return None, None, {"schema_version": 1, "kind": "execution-pipeline", "workitem_id": fid,
                "status": "error", "ready_for_pr": False,
                "error": (f"active-work реестр повреждён ({_awg['reason']}) — прогон не начат, чтобы не "
                          "потерять координацию параллельных сессий (пустая карта скрыла бы коллизии). "
                          "Нужна явная recovery .ai/runtime/active-work.yaml.")}
    # ЗАЯВКА #138: здесь стояло `or ["unspecified"]`, а `affected_areas` на одиночном пути в
    # сигналы не кладёт НИКТО — поэтому пересечение зон находилось со ВСЕМИ активными записями
    # сразу (неизвестность считалась совпадением). Зоны выводятся из `write_scope` тем же
    # правилом, что на пакетном пути (`work_areas` — одна формула на оба пути).
    areas = _work_areas.areas_for(signals, write_scope)
    # concurrency preflight ДО регистрации/изменения файлов: пересечения по областям с ДРУГОЙ
    # активной работой (тихо, через classify — без печати и без себя). Advisory в отчёт.
    try:
        _aw = active_work.load(aw_path)
        _conf = active_work.classify(
            [w for w in _aw.get("active", []) if w.get("id") != fid],
            {"id": fid, "affected_areas": list(areas), "depends_on": [], "shared_contracts": []})
        preflight = {"conflicts": _conf}
    except Exception as _pe:  # noqa: BLE001 — preflight не должен ронять прогон...
        # ...но и выглядеть пройденным не должен: при preflight=None отчёт печатал
        # «preflight-конфликтов: 0», то есть заявлял «конфликтов нет» там, где проверки
        # вообще не было. Записываем сбой явно.
        preflight = {"error": f"{type(_pe).__name__}: {_pe}"[:200], "conflicts": None}
    # регистрация активной работы (координация) — человекочитаемые строки в stderr, чтобы
    # stdout оставался чистым для --json.
    # КОД ВОЗВРАТА РЕГИСТРАЦИИ ЧИТАЕТСЯ (замер 18.08.2026). Прежде он отбрасывался в обеих
    # точках вызова: `register` мог отказать (цикл зависимостей, работа в main, нет зон) — и
    # прогон всё равно продолжался. С отказом второй сессии на ту же работу/ветку цена этого
    # молчания стала прямой: заявка потребителя #150 — два PR на одну ветку и выброшенная
    # половина работы. Отказ обязан останавливать прогон ДО правок, а не после.
    _reg_rc = 1
    with contextlib.redirect_stdout(sys.stderr):
        try:
            _reg_rc = active_work.register(aw_path, fid, f"ai-ops/{fid}", areas, session,
                                           workitem=f"features/{fid}/workitem.yaml",
                                           child_root=child_root,
                                           takeover=takeover, takeover_reason=takeover_reason,
                                           published=active_work.publication_enabled(child_root))
        except active_work.ActiveWorkCorrupt as _e:   # v3.0.12: сбой durable-записи реестра не молчит
            lifecycle_errors.append(f"active-work register: {_e}")
            _reg_rc = 0        # сбой записи реестра уже назван выше — не путать его с отказом
    if _reg_rc:
        return None, None, {"schema_version": 1, "kind": "run-report", "workitem_id": fid,
                "status": "blocked",
                "blocked_by": "active-work",
                "error": ("работа не начата: заявку на эту работу или ветку держит другая сессия "
                          "(причина и держатель названы выше). Перенять её можно осознанно — "
                          "`active_work.py register … --takeover --takeover-reason \"почему\"`.")}
    return aw_path, preflight, None


def _restore_resume_policy(ctx, resume):
    """v3.0-rc2 (P0.1) Canonical Resume Context: при resume восстановить ПОЛИТИКУ исходного прогона.

    K6: вынесено из run() без изменения поведения. Мутирует `ctx` (signals/task_type/risk +
    sandbox/baseline_diff/require_fix/author/review/open_pr/write_scope/max_steps/base/task_text/
    saved_task; sandbox здесь — policy enforcement, не security isolation: флаг политики прогона)
    из сохранённого run-settings.yaml — иначе resume молча теряет политику и
    переклассифицирует задачу. provider/model/base приходят от вызывающего (runtime-выбор);
    изменение базы/состояния уже требует явной ревалидации (resume_preflight). -> error-dict | None.

    v3.0-rc4 (P0.1): immutable-resume — ТОЛЬКО для пользовательского resume задачи. Внутренний
    per-package resume executor'а (каждый пакет — своя подсистема/affected_areas, поверх общей
    ветки) НЕ является сменой классификации: executor сам управляет policy пакета. Помечен
    _sequence_internal -> пропускаем drift-проверку и restore run-settings.
    """
    # is_service_text/product_task_for_resume остаются в ai_ops_run (используются тестами и CLI) —
    # ленивый импорт, чтобы не замкнуть импорт-граф и сохранить патчабельность.
    from ai_ops_kit.engine.ai_ops_run import is_service_text, product_task_for_resume
    ctx.saved_task = None    # F-027: продуктовая задача исходного прогона (переживает продолжение)
    if resume and ctx.feature and not ctx.signals.get("_sequence_internal"):
        _sp = ctx.features_dir / ctx.feature / "run-settings.yaml"
        # v3.0.12 (finding аудита блок B): FAIL-CLOSED чтение. Прежде safe_load(...) or {} трактовал
        # битый/пустой run-settings как «отсутствует» -> resume тихо откатывался к дефолтам вызова
        # (терял классификацию/policy/BaseBinding) И перезаписывал файл дефолтами (контракт исходного
        # прогона уничтожался навсегда). Теперь: повреждён -> явный отказ (не дефолт, не перезапись).
        _g = _ls.load_guarded(_sp, required_keys=("kind", "policy"), kind="run-settings")
        if _g["state"] == "corrupt":
            return {"schema_version": 1, "kind": "execution-pipeline", "workitem_id": ctx.feature,
                    "status": "error", "ready_for_pr": False,
                    "error": (f"run-settings повреждён ({_g['reason']}) — resume не может восстановить "
                              "policy/классификацию исходного прогона. Нужна явная recovery (не тихий "
                              "дефолт: иначе прогон переклассифицируется и перезапишет контракт)."),
                    "resume": {"requested": True, "resumed": False}}
        if _g["state"] == "ok":
            _saved = _g["data"]
            _ss, _pp = (_saved.get("signals") or {}), (_saved.get("policy") or {})
            if isinstance(_saved.get("task"), str) and _saved["task"].strip():
                ctx.saved_task = _saved["task"]
            # v3.0-rc4 (P0.1) IMMUTABLE resume: resume НЕ меняет классификацию/policy. Если новый
            # вызов пытается переопределить routing-сигнал (task_type/risk/size/affected_areas) или
            # write_scope значением, отличным от сохранённого — это НЕ resume, а replan: требуется
            # явный replan=True (+ ревалидация). Иначе можно было бы тихо продолжить ENGINEERING как QUICK.
            _POLICY_KEYS = ("task_type", "risk", "size", "affected_areas")
            _drift = [k for k in _POLICY_KEYS
                      if k in ctx.signals and k in _ss and ctx.signals[k] != _ss[k]]
            if ctx.write_scope is not None and _pp.get("write_scope") is not None \
                    and ctx.write_scope != _pp.get("write_scope"):
                _drift.append("write_scope")
            if _drift and not ctx.replan:
                return {"schema_version": 1, "kind": "execution-pipeline", "workitem_id": ctx.feature,
                        "status": "error", "ready_for_pr": False,
                        "error": ("resume не меняет классификацию/policy исходного прогона "
                                  f"(drift: {', '.join(_drift)}). Это replan — запусти с replan=True "
                                  "(ревалидация + новый план), а не resume."),
                        "resume": {"requested": True, "resumed": False, "drift": _drift}}
            # восстанавливаем СОХРАНЁННУЮ policy как источник истины (не «or», а точное значение),
            # кроме случая replan, где новый вызов осознанно задаёт новую policy.
            if not ctx.replan:
                ctx.signals = {**ctx.signals, **_ss}          # saved policy побеждает
                ctx.sandbox = bool(_pp.get("sandbox", ctx.sandbox))
                ctx.baseline_diff = bool(_pp.get("baseline_diff", ctx.baseline_diff))
                ctx.require_fix = bool(_pp.get("require_fix", ctx.require_fix))
                ctx.author = bool(_pp.get("author", ctx.author))
                ctx.review = bool(_pp.get("review", ctx.review))
                ctx.open_pr = bool(_pp.get("open_pr", ctx.open_pr))
                ctx.write_scope = _pp.get("write_scope") if ctx.write_scope is None else ctx.write_scope
                if ctx.max_steps == 40 and _pp.get("max_steps"):
                    ctx.max_steps = _pp["max_steps"]
                # v3.0.2/v3.0.9 (P0): base восстанавливается из saved BaseBinding (точная база исходного
                # запуска), с фолбэком на плоское поле base (совместимость со старыми run-settings).
                ctx.base = ((_pp.get("base_binding") or {}).get("base_ref")) or _pp.get("base", ctx.base)
        # F-027: задача исполнителя на продолжении обязана остаться ПРОДУКТОВОЙ. Служебный
        # next_action кита («закрыть незакрытые гейты: …») сюда доезжал как task_text — и автор
        # честно писал требования про гейты кита, заводил под них openspec-изменение и
        # validate_gates.py. Продуктовая спека при этом цела, потому и выглядело осмысленно.
        # Проверка стоит в движке, а не только в CLI: путь resume есть и у прямых вызывающих.
        if is_service_text(ctx.task_text):
            _pt = product_task_for_resume(ctx.child_root, ctx.feature, ctx.features_dir)
            if not _pt["task"]:
                return {"schema_version": 1, "kind": "execution-pipeline", "workitem_id": ctx.feature,
                        "status": "error", "ready_for_pr": False,
                        "error": ("продолжение получило служебный текст кита вместо продуктовой "
                                  f"задачи («{(ctx.task_text or '')[:60]}…»), а восстановить исходную "
                                  "не из чего (нет ни task в run-settings, ни задачи в "
                                  "workitem.yaml, ни раздела goal в спеке). Назовите задачу явно: "
                                  "--task \"<что делаем для продукта>\". Служебное «что осталось» "
                                  "задачей исполнителя не бывает."),
                        "resume": {"requested": True, "resumed": False}}
            ctx.task_text = _pt["task"]
            ctx.signals["task_text"] = ctx.task_text
    return None


def _resolve_models(ctx):
    """v3.7.12 Router->runtime: без явного --model резолвим модель ПО РОЛИ через model_router и
    физически диспатчим на endpoint вендора (provider_endpoints) -> writer≠judge по МОДЕЛИ.

    K6: вынесено из run() без изменения поведения. Мутирует `ctx` (writer/reviewer model+prov,
    model_resolution, sec_qualified, klp_by_env/trust_cache/trust_now/trust_env). Явный --model =
    override (записывается). Всё под fail-safe: нет резолва/ключа/endpoint -> прежнее поведение
    (passthrough --model) + честная запись в отчёт. JIT provider-preflight PRIMARY не пройден ->
    возвращает blocked-preflight-отчёт (fail-closed, provider не строится). -> error-dict | None.
    """
    from ai_ops_kit.providers import orchestrator
    # _load_klp_by_env/_provider_trust/_with_provider_fallback остаются в ai_ops_run (patched тестами,
    # нужны и _execute_with_fix_loop) — ленивый импорт сохраняет патчабельность (`ai_ops_run.<name>`).
    from ai_ops_kit.engine.ai_ops_run import (
        _load_klp_by_env, _provider_trust, _with_provider_fallback)
    ctx.writer_model, ctx.writer_prov, ctx.rev_model, ctx.rev_prov = ctx.model, None, ctx.model, None
    try:
        from ai_ops_kit.providers import model_router as _mr
        from ai_ops_kit.providers import provider_endpoints as _pe
        _plan = _mr.plan_run(signals=ctx.signals)   # v3.9.0-rc3: signals -> preferred_writer_tier
        ctx.model_resolution = {"kind": "ModelResolution", "plan": _plan, "applied": False,
                                "mode": "explicit-override" if ctx.model else "router", "notes": []}
        # v3.8.3-rc3 Dynamic Model Trust: JIT provider-preflight для КАЖДОЙ реально вызываемой модели
        # (primary/reviewer/fallback/escalation), а не только primary+reviewer. Trust-переменные видны
        # и в fix-loop (эскалация проверяет trust там).
        import os as _os
        import datetime as _dt
        ctx.trust_cache = {}
        ctx.klp_by_env = _load_klp_by_env(ctx.child_root)
        ctx.trust_now = _dt.date.today().isoformat()
        ctx.trust_env = dict(_os.environ)
        if ctx.model is None and ctx.provider_name == "openai-compatible":
            impl, rev = _plan.get("implementation") or {}, _plan.get("code_review") or {}
            if impl.get("resolved") and _pe.key_available(impl.get("provider")):
                ep = _pe.endpoint_for(impl["provider"])
                # JIT trust PRIMARY: не готов -> blocked-preflight (fail-closed, как раньше)
                _pt = _provider_trust(impl["provider"], ep["key_env"], ctx.klp_by_env, ctx.trust_env, ctx.trust_now, ctx.trust_cache)
                ctx.model_resolution["key_preflight"] = _pt.get("preflight") or {"ready": _pt["ready"], "blocks": ([] if _pt["ready"] else [_pt.get("reason")])}
                if not _pt["ready"]:
                    ctx.model_resolution["preflight_blocked"] = True
                ctx.writer_model = impl["model_id"]
                ctx.writer_prov = orchestrator.make_openai_provider(impl["model_id"], ep["base_url"], ep["key_env"])
                ctx.model_resolution["applied"] = True
                ctx.model_resolution["initial_model"] = impl["model_id"]
                ctx.model_resolution["effective_model"] = impl["model_id"]   # обновится при эскалации/fallback
                ctx.model_resolution["writer"] = {"model_id": impl["model_id"], "provider": impl["provider"],
                                                  "cost_basis": impl.get("cost_basis")}
                ctx.model_resolution["model_attempts"] = [
                    {"attempt": 1, "model": impl["model_id"], "provider": impl["provider"],
                     "trigger": "initial", "outcome": "pending"}]
                # v3.9.0-rc3 COMPLEXITY-AWARE ROUTING: сложный класс задачи -> сильный executor (Claude
                # Code adapter, claude-cli) СРАЗУ, не cheap-then-fix-loop. Честный fallback: нет локального
                # claude CLI -> остаёмся на дешёвом money-mode writer + пишем причину. Реестр/ключи не нужны
                # (локальная сессия). Escalation-ladder чистим: некуда «эскалировать» сильного вниз на kimi/qwen.
                _tier = _plan.get("preferred_writer_tier") or {}
                if _tier.get("tier") == "strong-executor":
                    # СПРАШИВАЕМ ТЕМ ЖЕ, ЧЕМ ЗАПУСТИМ (замер 18.08.2026). Здесь стоял голый
                    # `shutil.which("claude")`, а `make_claude_cli_provider()` запускает то, что
                    # найдёт `claude_lookup` — то есть путь, названный владельцем в
                    # AI_OPS_CLAUDE_BIN, сильнее PATH. Расхождение давало ровно тот класс, из-за
                    # которого функция и заводилась: рабочий исполнитель назван, но не в PATH ->
                    # «strong executor недоступен» и тихий откат на дешёвого writer'а; битый
                    # названный путь при claude в PATH -> writer выбран, а первый же вызов модели
                    # отказывается работать посреди начатого прогона.
                    if orchestrator.claude_binary():
                        ctx.writer_model = "claude-code-local"
                        ctx.writer_prov = orchestrator.make_claude_cli_provider()
                        ctx.model_resolution["effective_model"] = "claude-code-local"
                        ctx.model_resolution["writer"] = {"model_id": "claude-code-local", "provider": "claude-cli",
                                                          "tier": "strong-executor", "reason": _tier.get("reason")}
                        ctx.model_resolution["model_attempts"][0].update(
                            model="claude-code-local", provider="claude-cli", trigger="complexity-routing")
                        if isinstance(impl, dict):
                            impl["escalation_ladder"] = []   # сильный executor — вниз не даунгрейдим
                        ctx.model_resolution["notes"].append(
                            "complexity-aware: сложный класс -> writer=claude-cli (сильный executor) сразу")
                    else:
                        ctx.model_resolution["strong_executor_unavailable"] = True
                        _look = orchestrator.claude_lookup()
                        ctx.model_resolution["notes"].append(
                            "complexity-aware: класс требует strong-executor, но локальный claude CLI "
                            "недоступен ("
                            + ("назван путь AI_OPS_CLAUDE_BIN, файла нет или он не исполняемый"
                               if _look["where"] == "named" else "в PATH процесса кита не найден")
                            + ") -> честный fallback на money-mode дешёвый writer")
                # reviewer — JIT trust отдельного провайдера (writer≠judge по модели).
                # v3.9.0-rc3: сравниваем с ЭФФЕКТИВНЫМ writer'ом (ctx.writer_model), а не с registry-impl —
                # иначе при complexity-override (writer=claude-cli) deepseek-ревьюер ложно считался
                # «не независим» (deepseek==registry-impl) и откатывался в self-model -> no-verdict.
                _rev_trusted = (rev.get("resolved") and rev.get("model_id") != ctx.writer_model
                                and _pe.key_available(rev.get("provider"))
                                and _provider_trust(rev["provider"], _pe.endpoint_for(rev["provider"])["key_env"],
                                                    ctx.klp_by_env, ctx.trust_env, ctx.trust_now, ctx.trust_cache)["ready"])
                if _rev_trusted:
                    ep2 = _pe.endpoint_for(rev["provider"])
                    ctx.rev_model = rev["model_id"]
                    ctx.rev_prov = orchestrator.make_openai_provider(rev["model_id"], ep2["base_url"], ep2["key_env"])
                    ctx.model_resolution["reviewer"] = {"model_id": rev["model_id"], "provider": rev["provider"], "independent_by_model": True}
                elif (ctx.writer_model == "claude-code-local" and impl.get("resolved")
                      and _pe.key_available(impl.get("provider"))):
                    # v3.9.0-rc3 complexity-routing: writer=claude-cli (сильный executor) -> ревьюер =
                    # ДЕШЁВЫЙ qualified impl-судья (deepseek), независим от claude-cli по модели, даже если
                    # отдельная code_review-роль не резолвится в реестре. Это и есть owner-план review->deepseek.
                    _iep = _pe.endpoint_for(impl["provider"])
                    ctx.rev_model = impl["model_id"]
                    ctx.rev_prov = orchestrator.make_openai_provider(impl["model_id"], _iep["base_url"], _iep["key_env"])
                    ctx.model_resolution["reviewer"] = {"model_id": impl["model_id"], "provider": impl["provider"],
                                                        "independent_by_model": True,
                                                        "reason": "дешёвый qualified судья vs сильный writer=claude-cli"}
                else:
                    ctx.rev_model, ctx.rev_prov = ctx.writer_model, ctx.writer_prov
                    ctx.model_resolution["reviewer"] = {"model_id": ctx.writer_model, "independent_by_model": False,
                                                        "reason": "code_review не резолвится/нет ключа/trust -> self-model review (writer=judge по модели)"}
                    ctx.model_resolution["notes"].append("reviewer=writer по модели: нет отдельной допущенной+trusted модели")
                # v3.8.3-rc2 (#6) PROVIDER FALLBACK на RETRYABLE infra-сбое. rc3: fallback — НЕОБЯЗАТЕЛЬНЫЙ
                # кандидат: JIT trust; НЕ готов -> ИСКЛЮЧАЕМ (не блокируем primary) + пишем причину.
                _fb = impl.get("fallback") or {}
                if _fb.get("model_id") and _fb.get("provider"):
                    _fpt = (_provider_trust(_fb["provider"], _pe.endpoint_for(_fb["provider"])["key_env"],
                                            ctx.klp_by_env, ctx.trust_env, ctx.trust_now, ctx.trust_cache)
                            if _pe.key_available(_fb.get("provider")) else {"ready": False, "reason": "ключ отсутствует в env"})
                    if _fpt["ready"]:
                        try:
                            _fbep = _pe.endpoint_for(_fb["provider"])
                            _fb_prov = orchestrator.make_openai_provider(_fb["model_id"], _fbep["base_url"], _fbep["key_env"])
                            _sw = {"switched_to": None}
                            ctx.writer_prov = _with_provider_fallback(
                                ctx.writer_prov, _fb_prov,
                                on_switch=lambda e, _s=_sw, _m=_fb["model_id"]: _s.update(switched_to=_m))
                            ctx.model_resolution["writer_fallback"] = {
                                "model_id": _fb["model_id"], "provider": _fb["provider"],
                                "trigger": "retryable-infra-failure-only", "switch_state": _sw}
                            if not (ctx.model_resolution.get("reviewer") or {}).get("independent_by_model"):
                                ctx.rev_prov = ctx.writer_prov
                        except Exception as _fbe:  # noqa: BLE001 — сбой построения fallback не роняет прогон
                            ctx.model_resolution["writer_fallback"] = {"error": f"{type(_fbe).__name__}: {_fbe}"[:160]}
                    else:
                        ctx.model_resolution["writer_fallback"] = {
                            "excluded_model": _fb["model_id"], "provider": _fb.get("provider"),
                            "reason": _fpt.get("reason"),
                            "note": "необязательный fallback ИСКЛЮЧЁН по JIT-trust (не блокирует primary)"}
            else:
                ctx.model_resolution["notes"].append("router не применён (implementation не резолвится/нет ключа) -> passthrough --model")
    except Exception as _e:  # noqa: BLE001
        ctx.model_resolution = {"kind": "ModelResolution", "error": str(_e)[:200], "applied": False,
                                "mode": "explicit-override" if ctx.model else "router"}
    # v3.7.3 (#5 flip): security needs_review закрывает ТОЛЬКО КВАЛИФИЦИРОВАННЫЙ security-судья
    # (security_review.resolved в plan_run) ЛИБО человек (ApprovalRecord). Общий code reviewer — НЕТ.
    # Пока qualified security-судьи нет (до Bench v2) -> security needs_review -> pending_human до
    # человеческого ApprovalRecord (реальный human-fallback). Отдельный security_reviewer_proposer.
    ctx.sec_qualified = bool(((ctx.model_resolution.get("plan") or {}).get("security_review") or {}).get("resolved"))
    # v3.7.1 (#4) РЕАЛЬНЫЙ security-барьер: key preflight не пройден (ключ/ротация) -> блок ПРОГОНА
    # (не строим proposer, не зовём провайдера). Честный blocked-preflight-отчёт, ready_for_pr=false.
    if isinstance(ctx.model_resolution, dict) and ctx.model_resolution.get("preflight_blocked"):
        _kpf = ctx.model_resolution.get("key_preflight", {})
        return {"schema_version": 1, "kind": "execution-pipeline", "status": "blocked-preflight",
                "ready_for_pr": False, "provider": ctx.provider_name, "model": ctx.writer_model,
                "model_resolution": ctx.model_resolution, "key_preflight": _kpf,
                "blocked_reason": "key preflight не пройден до provider-вызова: "
                                  + "; ".join(_kpf.get("blocks", []) or ["ключ/ротация"]),
                "not_yet": ["security key preflight: " + "; ".join(_kpf.get("blocks", []) or ["ключ отсутствует/просрочен"])]}
    return None
