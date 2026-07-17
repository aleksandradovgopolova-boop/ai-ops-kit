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
       [--runtime claude-code|generic-orchestrator] [--provider mock] [--model ID]
       [--engine controller|pipeline] [--execute] [--open-pr] [--json]
  ai_ops_run.py --selftest
Код возврата: 0 — успех/ready; 1 — blocked или pipeline не готов к PR; 2 — ошибка прогона.
"""

import argparse
import contextlib
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


def _resume_context_from_handoff(child_root, fid):
    """v2.109 Real Resume: собрать из RunHandoff текст-состояние для prompt tool-loop, чтобы модель
    ПРОДОЛЖИЛА, а не переделала подтверждённое. Детерминированно, из features/<fid>/run-handoff.yaml."""
    hp = Path(child_root) / "features" / fid / "run-handoff.yaml"
    if not hp.is_file():
        return None
    h = yaml.safe_load(hp.read_text(encoding="utf-8")) or {}
    lines = ["=== RESUME: ПРОДОЛЖЕНИЕ РАБОТЫ (НЕ начинай заново, НЕ переделывай уже подтверждённое) ==="]
    if h.get("completed"):
        lines.append("Уже сделано:\n" + "\n".join(f"- {c}" for c in h["completed"]))
    dec = [d for d in (h.get("decisions") or []) if isinstance(d, dict)]
    if dec:
        lines.append("Принятые решения (не пересматривай без причины):\n"
                     + "\n".join(f"- {d.get('id', '?')}: {d.get('summary', '')}" for d in dec))
    if h.get("changed_files"):
        lines.append("Уже изменены файлы: " + ", ".join(h["changed_files"]))
    if h.get("open_questions"):
        lines.append("Открытые вопросы / осталось:\n" + "\n".join(f"- {q}" for q in h["open_questions"]))
    if h.get("next_action"):
        lines.append("СЛЕДУЮЩИЙ БЕЗОПАСНЫЙ ШАГ: " + str(h["next_action"]))
    return "\n\n".join(lines)


def run(task_text, signals, child_root: Path, features_dir=None,
        runtime="claude-code", provider_name="mock", session="cli", execute=False,
        feature=None, engine="controller", proposer=None, open_pr=False, model=None,
        baseline_diff=False, require_fix=False, max_steps=40, discard_previous=False,
        sandbox=False, review=False, reviewer_proposer=None,
        author=False, author_proposer=None, install_deps=True,
        resume=False, force_resume=False, base="main"):
    signals = dict(signals or {})
    signals.setdefault("task_text", task_text)
    child_root = Path(child_root)
    features_dir = Path(features_dir) if features_dir else child_root / "features"

    # engine=pipeline (v2.63): собранный единый движок как РЕАЛЬНЫЙ путь из контроллера
    # (adversarial-review: раньше execution_pipeline вызывался только из selftest). Делегируем
    # весь прогон в execution_pipeline.run_pipeline; proposer — из провайдера (или передан).
    if engine == "pipeline":
        import execution_pipeline
        import tool_loop
        import orchestrator
        prop = proposer or tool_loop.make_model_proposer(
            orchestrator.make_provider(provider_name, model))
        # v2.83: независимый ревьюер — ОТДЕЛЬНЫЙ провайдер (writer ≠ judge на уровне вызова),
        # petля даёт ему read-only-политику. Тот же класс модели — более слабая, но реальная
        # независимость (отдельный вызов+роль); полностью независимый судья (другая модель/человек)
        # — сильнее, это осознанная граница. Для mock-провайдера ревью не имеет смысла (нет вердикта).
        rev_prop = reviewer_proposer
        if review and rev_prop is None and provider_name != "mock":
            rev_prop = orchestrator.make_provider(provider_name, model)
        # v2.86: author-модель для артефактов requirements/plan (отдельный вызов провайдера).
        auth_prop = author_proposer
        if author and auth_prop is None and provider_name != "mock":
            auth_prop = orchestrator.make_provider(provider_name, model)

        # v2.94 (One Run Transaction, аудит #2): pipeline БОЛЬШЕ НЕ обходит lifecycle. Один план
        # строится здесь и передаётся в движок (не второй раз внутри); WorkItem/RunPlan/active-work/
        # concurrency-preflight/run-report — как в controller-пути. Прежде было «два мира»: движок
        # возвращал отчёт, не создавая WorkItem/active-work/run-report.
        plan = run_plan.build_plan(signals, workitem_id=feature)
        fid = plan["workitem_id"]

        # v2.109 Real Resume: продолжить WorkItem поверх подтверждённой работы (не начинать заново).
        # Проверяем ДО регистрации/изменения состояния, чтобы честный ранний выход ничего не оставил.
        resume_ctx = None
        if resume:
            import run_handoff
            pf = run_handoff.resume_preflight(child_root, fid, base=base)
            if not pf["can_resume"]:
                return {"schema_version": 1, "kind": "execution-pipeline", "workitem_id": fid,
                        "status": "error", "engine": "pipeline", "ready_for_pr": False,
                        "error": "resume невозможен: " + "; ".join(pf["reasons"]),
                        "resume": {"requested": True, "resumed": False, "can_resume": False,
                                   "reasons": pf["reasons"]}}
            # ЧЕСТНОСТЬ: база/состояние изменились -> НЕ продолжаем молча на устаревшем evidence.
            if pf["revalidation_needed"] and not force_resume:
                return {"schema_version": 1, "kind": "execution-pipeline", "workitem_id": fid,
                        "status": "blocked", "engine": "pipeline", "ready_for_pr": False,
                        "error": "resume требует ревалидации (база/состояние изменились с прошлого "
                                 "прогона) — перепроверь и запусти с force_resume=True (--force), "
                                 "чтобы продолжить осознанно",
                        "resume": {"requested": True, "resumed": False, "revalidation_needed": True,
                                   "reasons": pf["reasons"]}}
            resume_ctx = _resume_context_from_handoff(child_root, fid)

        workitem.start(str(features_dir), fid, task_text,
                       task_type=signals.get("task_type"), risk=signals.get("risk"))
        (features_dir / fid / "run-plan.yaml").write_text(
            yaml.safe_dump(plan, allow_unicode=True, sort_keys=False), encoding="utf-8")
        # v2.107 (finding аудита): ошибки слоя контекста больше НЕ гаснут молча — фиксируем в
        # lifecycle_errors и в отчёт (критический слой не должен исчезать без следа).
        lifecycle_errors = []
        # v2.97 Context Compiler: минимальный релевантный ContextBundle для WorkItem (детерминированно).
        import context_compiler
        try:
            bundle = context_compiler.compile_bundle(signals, child_root, plan=plan)
            (features_dir / fid / "context-bundle.yaml").write_text(
                yaml.safe_dump(bundle, allow_unicode=True, sort_keys=False), encoding="utf-8")
        except Exception as e:  # noqa: BLE001 — не роняем прогон, но и не молчим
            bundle = None; lifecycle_errors.append(f"context_compiler: {type(e).__name__}: {e}")
        # v2.108 Operational Context: compiled payload -> реально в prompt модели (context_prelude).
        payload = None
        try:
            payload = context_compiler.build_payload(signals, child_root, plan=plan, bundle=bundle, model=model)
            (features_dir / fid / "context-payload.yaml").write_text(
                yaml.safe_dump({k: v for k, v in payload.items() if k != "text"},
                               allow_unicode=True, sort_keys=False), encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            payload = None; lifecycle_errors.append(f"context_payload: {type(e).__name__}: {e}")
        # v2.98 Adaptive Spec-First: уровень спецификации (L0..L3) по сигналам + эскалация по риску.
        import spec_levels
        try:
            spec_cov = spec_levels.assess(signals)
            (features_dir / fid / "spec-coverage.yaml").write_text(
                yaml.safe_dump(spec_cov, allow_unicode=True, sort_keys=False), encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            spec_cov = None; lifecycle_errors.append(f"spec_levels: {type(e).__name__}: {e}")
        # v2.100 Atomic Planning: оценка размера пакета + нужна ли декомпозиция по контекстному бюджету.
        import atomic_planner
        try:
            work_pkg = atomic_planner.assess(signals, child_root=child_root, bundle=bundle)
            (features_dir / fid / "work-package.yaml").write_text(
                yaml.safe_dump(work_pkg, allow_unicode=True, sort_keys=False), encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            work_pkg = None; lifecycle_errors.append(f"atomic_planner: {type(e).__name__}: {e}")
        aw_path = child_root / ".ai" / "runtime" / "active-work.yaml"
        areas = signals.get("affected_areas") or ["unspecified"]
        # concurrency preflight ДО регистрации/изменения файлов: пересечения по областям с ДРУГОЙ
        # активной работой (тихо, через classify — без печати и без себя). Advisory в отчёт.
        try:
            _aw = active_work.load(aw_path)
            _conf = active_work.classify(
                [w for w in _aw.get("active", []) if w.get("id") != fid],
                {"id": fid, "affected_areas": list(areas), "depends_on": [], "shared_contracts": []})
            preflight = {"conflicts": _conf}
        except Exception:  # noqa: BLE001 — preflight не должен ронять прогон
            preflight = None
        # регистрация активной работы (координация) — человекочитаемые строки в stderr, чтобы
        # stdout оставался чистым для --json.
        with contextlib.redirect_stdout(sys.stderr):
            active_work.register(aw_path, fid, f"ai-ops/{fid}", areas, session,
                                 workitem=f"features/{fid}/workitem.yaml")

        # v2.107 (finding аудита): если pipeline упадёт, active-work обязана закрыться (иначе запись
        # останется in-progress навсегда) — гарантируем через except+re-raise.
        try:
            rep = execution_pipeline.run_pipeline(
                task_text, signals, child_root, prop, feature=feature, plan=plan,
                commit=execute, isolate=execute, open_pr=open_pr, baseline_diff=baseline_diff,
                require_fix=require_fix, max_steps=max_steps, discard_previous=discard_previous,
                sandbox=sandbox, review=review, reviewer_proposer=rev_prop,
                author=author, author_proposer=auth_prop, install_deps=install_deps,
                context_prelude=(payload or {}).get("text"),
                resume=resume, resume_context=resume_ctx)
        except BaseException:
            with contextlib.redirect_stdout(sys.stderr):
                active_work.finish_cmd(aw_path, fid)
            raise
        rep["runtime"] = runtime
        rep["engine"] = "pipeline"
        rep["provider"] = provider_name
        rep["model"] = model
        # v2.109 Real Resume: если продолжали — честно фиксируем в отчёте preflight-контекст (в т.ч.
        # что ревалидация требовалась и была осознанно переопределена --force), не только факт reuse.
        if resume and isinstance(rep.get("resume"), dict):
            rep["resume"]["preflight_reasons"] = pf["reasons"]
            rep["resume"]["revalidation_needed"] = pf["revalidation_needed"]
            rep["resume"]["revalidation_overridden"] = bool(pf["revalidation_needed"] and force_resume)
        # v2.94: единая транзакция — фиксируем lifecycle-артефакты в отчёте и на диске
        rep["lifecycle"] = {
            "workitem": f"features/{fid}/workitem.yaml",
            "run_plan": f"features/{fid}/run-plan.yaml",
            "context_bundle": (f"features/{fid}/context-bundle.yaml" if bundle else None),
            "context_payload": (f"features/{fid}/context-payload.yaml" if payload else None),
            "spec_coverage": (f"features/{fid}/spec-coverage.yaml" if spec_cov else None),
            "work_package": (f"features/{fid}/work-package.yaml" if work_pkg else None),
            "active_work": ".ai/runtime/active-work.yaml",
            "run_report": f"features/{fid}/run-report.json",
            "run_handoff": f"features/{fid}/run-handoff.yaml",
            "concurrency_preflight": preflight,
        }
        if bundle:
            rep["context_bundle"] = {"estimated_tokens": bundle["estimated_tokens"],
                                     "context_budget": bundle["context_budget"],
                                     "overflow": bundle["overflow"],
                                     "agents": bundle["included"]["agents"],
                                     "rules": bundle["included"]["rules"],
                                     "excluded_count": len(bundle["excluded"])}
        if payload:
            rep["context_payload"] = {"payload_tokens": payload["payload_tokens"],
                                      "payload_budget": payload["payload_budget"],
                                      "context_budget": payload["context_budget"],
                                      "included_items": len(payload["included_items"]),
                                      "excluded_for_budget": len(payload["excluded_for_budget"]),
                                      "fed_to_model": bool(payload.get("text"))}
        if spec_cov:
            rep["spec_coverage"] = {"level": spec_cov["level"], "level_name": spec_cov["level_name"],
                                    "escalated_from": spec_cov["escalated_from"],
                                    "blocking_missing": spec_cov["blocking_missing"],
                                    "needs_human": spec_cov["needs_human"]}
        if work_pkg:
            rep["work_package"] = {"atomic": work_pkg["atomic"],
                                   "should_decompose": work_pkg["should_decompose"],
                                   "decomposition_axes": work_pkg["decomposition_axes"],
                                   "decomposition_reasons": work_pkg["decomposition_reasons"]}
        if lifecycle_errors:
            rep["lifecycle_errors"] = lifecycle_errors   # v2.107: сбои слоя контекста видны, не гаснут
        try:
            (features_dir / fid / "run-report.json").write_text(
                json.dumps(rep, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        except OSError:
            pass
        # v2.99 Context Lifecycle: RunHandoff — состояние для продолжения в новой сессии (что сделано,
        # проверки, следующий безопасный шаг, актуальный SHA). Не начинать заново -> resume читает его.
        import run_handoff
        try:
            wt = child_root / ".ai" / "worktrees" / fid
            handoff = run_handoff.build_handoff(rep, work_root=(wt if wt.is_dir() else child_root))
            (features_dir / fid / "run-handoff.yaml").write_text(
                yaml.safe_dump(handoff, allow_unicode=True, sort_keys=False), encoding="utf-8")
            rep["handoff"] = {"next_action": handoff["next_action"],
                              "resume_from_revision": handoff["resume_from_revision"],
                              "open_questions": handoff["open_questions"]}
        except Exception:  # noqa: BLE001
            pass
        # закрываем активную работу по завершении прогона (была in-progress -> done)
        with contextlib.redirect_stdout(sys.stderr):
            active_work.finish_cmd(aw_path, fid)
        return rep

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
            gate_ids=plan.get("gates"),            # v2.54: прогон оценивает ГЕЙТЫ RUNPLAN (base+треки)
            signals=signals)                       # v2.55: условный human_approval по сигналам задачи
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


def _print_pipeline(r):
    """Человекочитаемый вывод отчёта собранного движка (kind=execution-pipeline).

    finding аудита (P0.1): print_human безусловно читал ключи controller-отчёта
    (status/execution/required_tracks) и падал KeyError на pipeline-отчёте. Формат отчёта
    движка иной (loop/commit/checks/gates/ready_for_pr) — печатаем его явно.
    """
    if r.get("status") == "error":
        print(f"ai-ops run (pipeline) → WorkItem {r.get('workitem_id')} [ОШИБКА]")
        print(f"  {r.get('error')}")
        return
    loop = r.get("loop") or {}
    commit = r.get("commit") or {}
    gates = r.get("gates") or {}
    ready = r.get("ready_for_pr")
    print(f"ai-ops run (pipeline) → WorkItem {r.get('workitem_id')} "
          f"[{'READY_FOR_PR' if ready else 'NOT_READY'}]")
    prov = r.get("provider") or "?"
    model = f"/{r['model']}" if r.get("model") else ""
    print(f"  base_workflow: {r.get('base_workflow')} · провайдер: {prov}{model} ({r.get('runtime')})")
    print(f"  стек: {', '.join(r.get('profile', {}).get('stacks') or ['не определён'])}")
    print(f"  tool-loop: {loop.get('stopped')} · шагов {loop.get('steps')} · "
          f"правок {loop.get('applied_writes')} · отклонено {loop.get('denied')}")
    iso = (r.get("isolation") or {}).get("worktree")
    print(f"  изоляция: {iso or 'основное дерево (без worktree)'}")
    if commit.get("sha"):
        print(f"  commit: {commit['sha'][:12]} на {commit.get('branch')} · "
              f"evidence на точном SHA: {commit.get('evidence_on_exact_sha')} · "
              f"дерево чистое: {commit.get('tree_clean_before_checks')}")
    if r.get("exemptions"):
        print(f"  освобождены (не применимо): {', '.join(r['exemptions'])}")
    if r.get("tests_warn"):
        print(f"  ⚠ {r['tests_warn']}")
    print(f"  гейты: оценено {len(gates.get('evaluated') or [])} · "
          f"не закрыто {gates.get('unmet') or []} · блокирует: {gates.get('blocked')}")
    lc = r.get("lifecycle")
    if lc:
        pf = (lc.get("concurrency_preflight") or {})
        conflicts = len(pf.get("conflicts") or []) if isinstance(pf, dict) else 0
        print(f"  lifecycle: WorkItem+RunPlan+active-work+run-report записаны · "
              f"preflight-конфликтов: {conflicts}")
    cb = r.get("context_bundle")
    if cb:
        print(f"  context: ~{cb['estimated_tokens']}/{cb['context_budget']} ток."
              f"{' ⚠OVERFLOW' if cb.get('overflow') else ''} · агентов {len(cb['agents'])} · "
              f"исключено {cb['excluded_count']} источн.")
    sc = r.get("spec_coverage")
    if sc:
        esc = f" (эскалация с L{sc['escalated_from']})" if sc.get("escalated_from") is not None else ""
        print(f"  spec-level: {sc['level_name']}{esc} · не хватает разделов: "
              f"{len(sc['blocking_missing'])} · needs_human: {len(sc['needs_human'])}")
    wp = r.get("work_package")
    if wp and wp.get("should_decompose"):
        print(f"  ⚠ пакет не атомарен — рекомендуется декомпозиция ({', '.join(wp['decomposition_axes'])})")
    pr = r.get("draft_pr")
    if pr:
        print(f"  draft PR: {pr.get('status')}" + (f" — {pr.get('url')}" if pr.get('url') else ""))
    for n in r.get("not_yet") or []:
        print(f"  · not_yet: {n}")


def print_human(r):
    # pipeline-отчёт имеет свою форму — не смешиваем с controller-отчётом (P0.1)
    if r.get("kind") == "execution-pipeline":
        return _print_pipeline(r)
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


def exit_code(r):
    """Код возврата CLI по отчёту (finding аудита P0.1: раньше всегда 0).

    pipeline: 2 при status=error, 1 если не ready_for_pr (гейты/петля/коммит не сошлись), 0 если ready.
    controller: 1 при status=blocked, 0 иначе (planned/done — успешная транзакция).
    """
    if r.get("kind") == "execution-pipeline":
        if r.get("status") == "error":
            return 2
        return 0 if r.get("ready_for_pr") else 1
    return 1 if r.get("status") == "blocked" else 0


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

    # v2.63 (adversarial-review): engine=pipeline РЕАЛЬНО делегирует в собранный движок из
    # контроллера (а не только selftest). Проверяем mock-предложителем в git-репо.
    import subprocess
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        subprocess.run(["git", "-C", td, "init", "-q"])
        subprocess.run(["git", "-C", td, "config", "user.email", "t@t"])
        subprocess.run(["git", "-C", td, "config", "user.name", "t"])
        (root / "src").mkdir(); (root / "f").write_text("x", encoding="utf-8")
        subprocess.run(["git", "-C", td, "add", "-A"]); subprocess.run(["git", "-C", td, "commit", "-q", "-m", "i"])
        pscript = iter([{"op": "write", "path": "src/a.py", "content": "a=1\n"}, {"done": True}])
        rp = run("добавить a", {"task_type": "QUICK", "size": "small", "risk": "low",
                                "affected_areas": ["core"]}, root, engine="pipeline",
                 proposer=lambda c: next(pscript))
        expect("engine=pipeline: контроллер делегирует в собранный движок",
               rp.get("engine") == "pipeline" and rp.get("kind") == "execution-pipeline")
        expect("engine=pipeline: движок применил изменение",
               rp["loop"]["applied_writes"] == 1 and (root / "src" / "a.py").exists())
        # v2.94 One Run Transaction: pipeline-путь проходит ЕДИНЫЙ lifecycle (не обходит его)
        pfid = rp["workitem_id"]
        expect("v2.94: pipeline создал WorkItem", (root / "features" / pfid / "workitem.yaml").exists())
        expect("v2.94: pipeline записал RunPlan", (root / "features" / pfid / "run-plan.yaml").exists())
        expect("v2.94: pipeline записал run-report", (root / "features" / pfid / "run-report.json").exists())
        expect("v2.94: pipeline зарегистрировал active-work",
               (root / ".ai" / "runtime" / "active-work.yaml").exists())
        expect("v2.94: lifecycle-артефакты в отчёте", isinstance(rp.get("lifecycle"), dict)
               and rp["lifecycle"].get("workitem") == f"features/{pfid}/workitem.yaml")
        _awd = active_work.load(root / ".ai" / "runtime" / "active-work.yaml")
        expect("v2.94: active-work закрыта (done) по завершении прогона",
               any(w.get("id") == pfid and w.get("status") == "done" for w in _awd.get("active", [])))
        expect("v2.94: единый план — движок НЕ строил второй (workitem_id совпал)",
               rp["workitem_id"] == pfid)
        # v2.97 Context Compiler: у прогона сохранён ContextBundle, размер измерен ДО модели
        expect("v2.97: ContextBundle сохранён рядом с планом",
               (root / "features" / pfid / "context-bundle.yaml").exists())
        expect("v2.97: context измерен (estimated_tokens>0) + бюджет в отчёте",
               isinstance(rp.get("context_bundle"), dict)
               and rp["context_bundle"]["estimated_tokens"] > 0
               and rp["context_bundle"]["context_budget"] > 0)
        # v2.108 Operational Context: compiled payload собран, сохранён и помечен как поданный модели
        expect("v2.108: ContextPayload сохранён", (root / "features" / pfid / "context-payload.yaml").exists())
        expect("v2.108: payload подан модели (fed_to_model) + бюджет с резервом",
               isinstance(rp.get("context_payload"), dict)
               and rp["context_payload"]["fed_to_model"] is True
               and rp["context_payload"]["payload_budget"] < rp["context_payload"]["context_budget"])
        # v2.98 Adaptive Spec-First: уровень спецификации определён и сохранён
        expect("v2.98: SpecCoverage сохранён", (root / "features" / pfid / "spec-coverage.yaml").exists())
        expect("v2.98: spec-level в отчёте (QUICK -> L0)",
               isinstance(rp.get("spec_coverage"), dict) and rp["spec_coverage"]["level"] == 0)
        # v2.99 Context Lifecycle: RunHandoff сохранён + next_action для resume
        expect("v2.99: RunHandoff сохранён", (root / "features" / pfid / "run-handoff.yaml").exists())
        expect("v2.99: handoff несёт next_action (следующий шаг)",
               isinstance(rp.get("handoff"), dict) and bool(rp["handoff"].get("next_action")))
        # resume-preflight по этому WorkItem: handoff есть -> can_resume
        import run_handoff as _rh
        _pf = _rh.resume_preflight(root, pfid, base=_rh._git(root, "rev-parse", "--abbrev-ref", "HEAD")[1])
        expect("v2.99: resume-preflight видит handoff (can_resume=True)", _pf["can_resume"] is True)
        # v2.100 Atomic Planning: оценка пакета сохранена + в отчёте
        expect("v2.100: WorkPackagePlan сохранён", (root / "features" / pfid / "work-package.yaml").exists())
        expect("v2.100: work_package в отчёте (QUICK/1 подсистема -> atomic)",
               isinstance(rp.get("work_package"), dict) and rp["work_package"]["atomic"] is True)
        # P0.1: print_human не падает KeyError на pipeline-отчёте (раньше читал controller-ключи)
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                print_human(rp); ph_ok = True
            except KeyError:
                ph_ok = False
        expect("P0.1: print_human форматирует pipeline-отчёт без KeyError",
               ph_ok and "pipeline" in buf.getvalue())
        # P0.1: exit_code ненулевой, когда движок не дошёл до ready_for_pr (dry-run, commit=False)
        expect("P0.1: exit_code != 0 при not ready_for_pr", exit_code(rp) != 0)
        expect("P0.1: exit_code == 2 при status=error",
               exit_code({"kind": "execution-pipeline", "status": "error"}) == 2)

    # v2.109 Real Resume (контроллер): первый прогон коммитит + пишет RunHandoff; resume ПРОДОЛЖАЕТ
    # поверх той же ветки (не рестарт, работа не потеряна), а не выдаёт ошибку про несохранённые коммиты.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        subprocess.run(["git", "-C", td, "init", "-q"])
        subprocess.run(["git", "-C", td, "config", "user.email", "t@t"])
        subprocess.run(["git", "-C", td, "config", "user.name", "t"])
        (root / "src").mkdir(); (root / "seed").write_text("x", encoding="utf-8")
        subprocess.run(["git", "-C", td, "add", "-A"]); subprocess.run(["git", "-C", td, "commit", "-q", "-m", "i"])
        cur = subprocess.run(["git", "-C", td, "rev-parse", "--abbrev-ref", "HEAD"],
                             capture_output=True, text=True).stdout.strip()
        sig_r = {"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]}
        s1 = iter([{"op": "write", "path": "src/phase1.py", "content": "p=1\n"}, {"done": True}])
        r_p1 = run("фаза 1", sig_r, root, engine="pipeline", proposer=lambda c: next(s1),
                   execute=True, feature="ctl-resume", install_deps=False)
        expect("v2.109 ctl: фаза 1 закоммичена + handoff записан",
               bool((r_p1.get("commit") or {}).get("sha"))
               and (root / "features" / "ctl-resume" / "run-handoff.yaml").exists())
        # resume БЕЗ execute-параметра тут не нужен — вызываем run(resume=True); ветка переиспользуется
        s2 = iter([{"op": "write", "path": "src/phase2.py", "content": "p=2\n"}, {"done": True}])
        r_p2 = run("фаза 2", sig_r, root, engine="pipeline", proposer=lambda c: next(s2),
                   execute=True, feature="ctl-resume", install_deps=False, resume=True, base=cur)
        expect("v2.109 ctl: resume продолжил (не ошибка про несохранённые коммиты)",
               r_p2.get("status") != "error" and (r_p2.get("resume") or {}).get("resumed") is True)
        wt_c = root / ".ai" / "worktrees" / "ctl-resume"
        expect("v2.109 ctl: обе фазы в worktree (продолжили поверх, не с нуля)",
               (wt_c / "src" / "phase1.py").exists() and (wt_c / "src" / "phase2.py").exists())
        # честность: нечего продолжать -> resume даёт honest error (не притворяется свежим прогоном)
        r_none = run("продолжить пустоту", sig_r, root, engine="pipeline",
                     proposer=lambda c: {"done": True}, execute=True, feature="never-ran",
                     install_deps=False, resume=True, base=cur)
        expect("v2.109 ctl: resume без прошлого -> honest error (can_resume=False)",
               r_none.get("status") == "error" and (r_none.get("resume") or {}).get("can_resume") is False)
        # честность: base ушёл вперёд -> resume БЕЗ --force блокируется (не продолжаем молча на устаревшем)
        (root / "moved.txt").write_text("z", encoding="utf-8")
        subprocess.run(["git", "-C", td, "add", "-A"]); subprocess.run(["git", "-C", td, "commit", "-q", "-m", "base+1"])
        s3 = iter([{"op": "write", "path": "src/phase3.py", "content": "p=3\n"}, {"done": True}])
        r_block = run("фаза 3", sig_r, root, engine="pipeline", proposer=lambda c: next(s3),
                      execute=True, feature="ctl-resume", install_deps=False, resume=True, base=cur)
        expect("v2.109 ctl: устаревшая база -> resume блокируется без --force (честно, не молча)",
               r_block.get("status") == "blocked"
               and (r_block.get("resume") or {}).get("revalidation_needed") is True)
        # с --force продолжает осознанно, и отчёт ЧЕСТНО помечает, что ревалидация переопределена
        s4 = iter([{"op": "write", "path": "src/phase4.py", "content": "p=4\n"}, {"done": True}])
        r_force = run("фаза 4", sig_r, root, engine="pipeline", proposer=lambda c: next(s4),
                      execute=True, feature="ctl-resume", install_deps=False, resume=True,
                      force_resume=True, base=cur)
        expect("v2.109 ctl: --force продолжает + отчёт помечает revalidation_overridden=True (честно)",
               r_force.get("status") != "error"
               and (r_force.get("resume") or {}).get("resumed") is True
               and (r_force.get("resume") or {}).get("revalidation_overridden") is True)

    # orchestrated-путь (generic-orchestrator, mock без evidence -> blocked, но транзакция прошла)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        r2 = run("починить опечатку", {"task_type": "QUICK", "affected_areas": ["docs"]},
                 root, runtime="generic-orchestrator", provider_name="mock", execute=True)
        expect("orchestrated: исполнение прошло, статус blocked|done",
               r2["status"] in ("blocked", "done") and r2["execution"] == "orchestrated")
        expect("orchestrated: состояние по WorkItem",
               f"workitems/{r2['workitem_id']}" in r2["run_state"])
        # P0.1: exit_code для controller — blocked -> 1, planned/done -> 0
        expect("P0.1: exit_code(blocked)=1", exit_code(r2) == (1 if r2["status"] == "blocked" else 0))
        expect("P0.1: exit_code(planned)=0", exit_code({"status": "planned"}) == 0)

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
    rp.add_argument("--engine", default="controller", choices=["controller", "pipeline"],
                    help="controller (план+каркас) или pipeline (собранный движок: detect->tool-loop->evidence->гейты->PR)")
    rp.add_argument("--model", help="ID модели для провайдера (напр. deepseek-chat); engine=pipeline")
    rp.add_argument("--open-pr", action="store_true",
                    help="открыть draft PR по результату (нужен GITHUB_TOKEN); engine=pipeline")
    rp.add_argument("--baseline-diff", action="store_true",
                    help="судить по 'нет новых провалов против базы' (пред-существующие красные "
                         "проверки репо не блокируют); engine=pipeline")
    rp.add_argument("--require-fix", action="store_true",
                    help="для fix-задач: ready требует, чтобы правка РЕАЛЬНО починила падавшую "
                         "проверку (fixed непустой), а не только 'не сломала'; engine=pipeline+baseline-diff")
    rp.add_argument("--max-steps", type=int, default=40,
                    help="потолок шагов tool-loop (по умолчанию 40; reasoning-моделям нужен "
                         "запас на цикл понять->починить->проверить->done); engine=pipeline")
    rp.add_argument("--discard", action="store_true",
                    help="перезаписать worktree/ветку прошлого прогона того же --feature, даже "
                         "если там есть несохранённые коммиты (по умолчанию — остановка, чтобы "
                         "не потерять работу); engine=pipeline+isolate")
    rp.add_argument("--sandbox", action="store_true",
                    help="containment (v2.81): shell модели — только по allowlist dev-инструментов "
                         "(произвольный shell выключен), сетевые бинарники и git push из петли "
                         "запрещены; доставка PR — только движком. Полная FS/сеть/ресурс-изоляция — "
                         "контейнерный runtime; engine=pipeline")
    rp.add_argument("--review", action="store_true",
                    help="full RunPlan (v2.83): постадийный НЕЗАВИСИМЫЙ ревью ai-review гейтов "
                         "(code_review/ux_review/...) — отдельный вызов модели под read-only "
                         "политикой выносит структурный вердикт (writer ≠ judge). Артефакт-гейты "
                         "(requirements/spec/plan) и human-approval ревьюер НЕ закрывает; "
                         "engine=pipeline, нужна живая модель (не mock)")
    rp.add_argument("--author", action="store_true",
                    help="product authoring (v2.86): движок производит артефакты requirements/plan "
                         "(отдельный вызов модели) и подтверждает их ФОРМУ детерминированно -> "
                         "закрывает артефакт-гейты requirements/plan_readiness. Качество судит "
                         "ревьюер (--review)/человек. specification (OpenSpec) не входит; нужна "
                         "живая модель (не mock)")
    rp.add_argument("--json", action="store_true")
    # v2.99: resume — продолжить WorkItem по последнему RunHandoff (не начинать заново)
    # v2.109 Real Resume: с --execute РЕАЛЬНО продолжает tool-loop поверх ветки/worktree прошлого
    # прогона (не рестарт); без --execute — только preflight (что продолжим, нужна ли ревалидация).
    rs = sub.add_parser("resume")
    rs.add_argument("child_root"); rs.add_argument("feature")
    rs.add_argument("--base", default="main"); rs.add_argument("--json", action="store_true")
    rs.add_argument("--task", help="задача-продолжение (по умолчанию — next_action из RunHandoff)")
    rs.add_argument("--signals", default="{}")
    rs.add_argument("--execute", action="store_true",
                    help="РЕАЛЬНО продолжить прогон (tool-loop поверх ветки прошлого прогона); "
                         "без флага — только preflight")
    rs.add_argument("--force", action="store_true",
                    help="продолжить, даже если нужна ревалидация (база/состояние изменились) — "
                         "осознанное решение человека")
    rs.add_argument("--provider", default="mock")
    rs.add_argument("--model", help="ID модели для провайдера (напр. deepseek-chat)")
    a = ap.parse_args(argv)
    if a.cmd == "resume":
        import run_handoff
        pf = run_handoff.resume_preflight(a.child_root, a.feature, base=a.base)
        if not a.execute:
            if a.json:
                print(json.dumps(pf, ensure_ascii=False, indent=2))
            else:
                print(f"ai-ops resume {a.feature}: can_resume={pf['can_resume']} · "
                      f"revalidation_needed={pf.get('revalidation_needed')}")
                for r_ in pf["reasons"]:
                    print(f"  · {r_}")
                if pf.get("next_action"):
                    print(f"  следующий шаг: {pf['next_action']}")
                if pf["can_resume"]:
                    reval = pf.get("revalidation_needed")
                    print(f"  продолжить: ai-ops resume {a.child_root} {a.feature} --execute"
                          f"{' --force' if reval else ''}   (worktree/ветка переиспользуются; "
                          f"{'нужна ревалидация -> --force' if reval else 'база актуальна'})")
            return 0 if pf["can_resume"] else 1
        # РЕАЛЬНОЕ продолжение (v2.109)
        task = a.task or (pf.get("next_action") if pf.get("can_resume") else None) or "продолжить работу"
        report = run(task, json.loads(a.signals), Path(a.child_root),
                     provider_name=a.provider, model=a.model, engine="pipeline",
                     execute=True, feature=a.feature, resume=True, force_resume=a.force, base=a.base)
        rinfo = report.get("resume") or {}
        if a.json:
            print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        else:
            print(f"ai-ops resume {a.feature}: status={report.get('status') or report.get('overall_status')} · "
                  f"resumed={rinfo.get('resumed')} · reused_branch={rinfo.get('reused_branch')}")
            if report.get("error"):
                print(f"  · {report['error']}")
            if report.get("ready_for_pr") is not None:
                print(f"  ready_for_pr={report.get('ready_for_pr')}")
        if report.get("status") in ("error", "blocked"):
            return 2 if report.get("status") == "error" else 1
        return 0 if report.get("ready_for_pr") else 1
    if a.cmd == "run":
        report = run(a.task, json.loads(a.signals), Path(a.child_root), a.features_dir,
                     a.runtime, a.provider, a.session, a.execute, feature=a.feature,
                     engine=a.engine, open_pr=a.open_pr, model=a.model,
                     baseline_diff=a.baseline_diff, require_fix=a.require_fix, max_steps=a.max_steps,
                     discard_previous=a.discard, sandbox=a.sandbox, review=a.review, author=a.author)
        if a.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print_human(report)
        # finding аудита (P0.1): CLI отдаёт ненулевой код при ошибке/не-готовности —
        # чтобы CI/скрипты видели провал, а не считали любой прогон успешным.
        return exit_code(report)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
