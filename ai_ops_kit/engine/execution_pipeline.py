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
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from ai_ops_kit.shared import _bootstrap  # noqa: E402
from ai_ops_kit.shared import project_detector      # noqa: E402
from ai_ops_kit.engine import tool_loop             # noqa: E402
from ai_ops_kit.engine import tool_broker           # noqa: E402
from ai_ops_kit.engine import run_plan              # noqa: E402
from ai_ops_kit.gates import gate_executor         # noqa: E402
from ai_ops_kit.gates import gate_policy           # noqa: E402  (v3.1.8 калиброванное UI-enforcement)


# ---------------------------------------------------------------------------
# Submodule imports — functions extracted into focused modules for maintainability.
# All names are re-exported so that `execution_pipeline.XXX` continues to work.
# ---------------------------------------------------------------------------
from ai_ops_kit.engine.pipeline_helpers import (  # noqa: E402,F401
    _profile_summary, _intake_evidence, NO_SELF_REVIEW, _reviewable_gates,
    _gate_checklist, _parse_yaml_block, _openspec_validate, _authoring_specs,
    acceptance_blocks_ready,
)
from ai_ops_kit.engine.pipeline_git import (  # noqa: E402,F401
    _git, _has_changes, _head_advanced, _tree_clean, _TOOL_CACHE_RE, _tree_clean_after_checks,
    _untracked, _committed_changed_files, _commit_on_branch, _resolve_base,
    _verify_remote_base, _change_context, _change_context_range,
    delivery_preflight as _delivery_preflight,
    managed_drift_preflight as _managed_drift_preflight,
)
from ai_ops_kit.engine.pipeline_failure import (  # noqa: E402,F401
    _ENV_SYMPTOMS, _check_has_env_symptom, _env_proven_ok, _env_unqualified,
    _baseline_failure_summary, _failure_signal, _FAILURE_ID_PATTERNS,
    _VOLATILE_RE, _normalize_failure_id, _failure_ids, _diff_checks,
    _evidence_ref_errors, _security_verdict_errors,
)
from ai_ops_kit.engine.pipeline_evidence import (  # noqa: E402,F401
    _install_dependencies, _author_with_retry, _run_spec_authoring,
    _run_authoring, _authored_context, _reevaluate_artifact_evidence,
    _run_reviews, _review_security, _human_approval_domains_uncovered,
    contour_consistency_evidence,          # v3.35: исполнение гейта connectivity контуров
)
# v3.38 (K6): readiness/security-оценка вынесена в pipeline_readiness — реэкспорт,
# чтобы execution_pipeline._assess_readiness/_evaluate_security/_build_not_yet_list
# продолжали резолвиться (внутренние вызовы + тесты через execution_pipeline.X).
from ai_ops_kit.engine.pipeline_readiness import (  # noqa: E402,F401
    _assess_readiness, _build_not_yet_list, _evaluate_security,
)
# v3.38+ (deep-cut): кластер изоляции/окружения/сборки evidence вынесен в pipeline_setup —
# реэкспорт, чтобы execution_pipeline._setup_isolation/_prepare_environment/_commit_work/
# _assemble_evidence/_seam_scan_advisory продолжали резолвиться (внутренние вызовы run_pipeline +
# тесты через execution_pipeline.X). run_pipeline остаётся здесь.
from ai_ops_kit.engine.pipeline_setup import (  # noqa: E402,F401
    _setup_isolation, _prepare_environment, _commit_work, _assemble_evidence,
    _seam_scan_advisory,
)


def _build_loop_section(loop, applied):
    """Секция loop в отчёте. v3.38 (K6): вынесено из run_pipeline."""
    return {"stopped": loop["stopped"], "steps": loop["steps"],
            "applied_writes": len(applied), "denied": len(loop["denied"]),
            "denied_reasons": [d.get("reason") for d in loop["denied"]][:10],
            "transcript": [{k: t.get(k) for k in ("step", "op", "allowed", "ok", "done", "reason")
                            if k in t} for t in (loop.get("transcript") or [])][:40]}


def _build_commit_section(work_branch, committed_sha, evidence_revision, revision_matches,
                          changed_for_verification, work_produced_by, tree_clean_before, tree_clean_after):
    """Секция commit в отчёте. v3.38 (K6): вынесено из run_pipeline."""
    return {"branch": work_branch, "sha": committed_sha,
            "evidence_revision": evidence_revision,
            "evidence_on_exact_sha": revision_matches,
            "changed_files": list(changed_for_verification or []),
            "produced_by": work_produced_by,
            "tree_clean_before_checks": tree_clean_before,
            "tree_clean_after_checks": tree_clean_after}


def _build_containment(sandbox, pol, loop):
    """Секция containment в отчёте. v3.38 (K6): вынесено из run_pipeline."""
    return {"sandbox": sandbox, "shell_mode": pol.shell_mode,
            "block_push": pol.block_push, "allow_network": pol.allow_network,
            "shell_path_guard": getattr(pol, "shell_path_guard", False),
            "shell_scope_guard": getattr(pol, "shell_scope_guard", False),
            "shell_path_violations": sum(
                len(((e.get("fs_guard") or {}).get("violations")) or [])
                for e in (loop.get("evidence") or [])),
            "note": "enforceable-подмножество на уровне брокера: пути закрыты на обоих "
                    "каналах (write — до, shell — пост-фактум с откатом); запись вне "
                    "корня репозитория, сеть и не-git деревья — по-прежнему нет; полная "
                    "FS/сеть/ресурс-изоляция — контейнерный runtime"}


def _plan_delivery(open_pr, ready, committed_sha, work_branch, base_binding, base_ref, base_sha,
                   work_root, wid, task, delivery_pf):
    """Планирование доставки. v3.38 (K6): вынесено из run_pipeline.
    -> (delivery, delivery_plan, can_deliver)."""
    delivery_plan = None
    can_deliver = bool(open_pr and ready and committed_sha and work_branch)
    if can_deliver:
        delivery = {"requested": True, "base_binding": base_binding, "status": "planned",
                    "reason": "доставку выполняет ТОЛЬКО транзакционный контроллер после durable-фиксации "
                              "lifecycle (run_pipeline не открывает PR)"}
        delivery_plan = {"ready_for_delivery": True, "work_root": str(work_root), "work_branch": work_branch,
                         "base_ref": base_ref, "base_sha": base_sha, "committed_sha": committed_sha,
                         "wid": wid, "task": task, "base_binding": base_binding}
    else:
        delivery = {"requested": bool(open_pr), "base_binding": base_binding,
                    "preflight": delivery_pf,
                    "status": ("not-requested" if not open_pr
                               else ("not-attempted" if not ready else None))}
    return delivery, delivery_plan, can_deliver


def _compute_overall_status(ready, can_deliver, open_pr):
    """Определить итоговый статус прогона. v3.38 (K6): вынесено из run_pipeline."""
    if not ready:
        return "error"
    if can_deliver:
        return "ready-undelivered"
    if not open_pr:
        return "delivered"
    return "delivery-failed"


def _deliver_pr(work_root, work_branch, base_ref, base_sha, base_binding, committed_sha, wid, task,
                delivery_id=None):
    """v3.0.15/v3.0.16 (finding аудита P0/#1): доверенная доставка draft PR — единственная точка открытия
    PR. Fail-closed по remote base (verified-equal -> PR; unverifiable/moved -> НЕ открываем). Вызывается
    ИСКЛЮЧИТЕЛЬНО транзакционным контроллером (ai_ops_run) ПОСЛЕ durable-фиксации RunHandoff+final report+
    journal+DeliveryIntent. run_pipeline НИКОГДА не вызывает эту функцию (только возвращает DeliveryPlan) —
    так прямой вызов pipeline не может обойти lifecycle-барьер. Идемпотентно (pr_open находит существующий
    PR ветки и возвращает 'updated', не создавая дубль). -> delivery dict."""
    delivery = {"requested": True, "base_binding": base_binding}
    if not base_binding.get("resolved") or not base_sha:
        delivery.update(status="unavailable",
                        reason=f"base '{base_ref}' не разрешилась в ветку: {base_binding.get('reason')} "
                               "— PR к произвольному HEAD не открываем")
        return delivery
    _rv = _verify_remote_base(work_root, base_ref, base_sha)
    if _rv.get("verdict") == "unverifiable":
        delivery.update(status="unavailable",
                        reason=f"remote-base-unverified: {_rv.get('reason')} — доставка невозможна fail-closed")
        return delivery
    if _rv.get("verdict") == "verified-moved":
        delivery.update(status="not-attempted",
                        reason=f"remote base сдвинулась (validated {base_sha[:12]} != remote "
                               f"{(_rv.get('remote_sha') or '?')[:12]}) — нужна ревалидация; PR не открыт")
        return delivery
    from ai_ops_kit.delivery import pr_open
    from ai_ops_kit.engine import living_status as _living_status
    # #404: тело PR называет судьбу статус-доков — обновлены или почему нет; read-only, не бросает.
    status_docs = _living_status.describe(work_root)
    pr = pr_open.open_draft_pr(work_root, work_branch, title=f"ai-ops: {task[:60]}", base=base_ref,
                               body=pr_open.pr_body(wid, base_ref, base_sha, committed_sha, status_docs),
                               delivery_id=delivery_id)
    delivery.update(status=(pr or {}).get("status"), pr=pr, status_docs=status_docs)
    return delivery


def _security_pack_for_report(security_pack_result):
    """Вердикт security-пака -> в отчёт через ПРОЕКЦИЮ пака (белый список полей), а не срезом на месте.
    Срез на месте и был дефектом: четыре поля выбирались здесь, и находки терялись по дороге."""
    from ai_ops_kit.security import security_pack as _sp_report
    return _sp_report.for_report(security_pack_result)


def _pipeline_check_spec_drift(task, signals, child_root, feature, write_scope, *,
                               max_steps, commit, baseline_diff, require_fix, sandbox,
                               review, author):
    """Фаза K0-проводки: параметры прогона обязаны оставаться подмножеством объявленного
    контракта ядра (kernel/ports.ExecutionSpec). Это НЕ проверка реализации портов (реализации
    им ещё не соответствуют — долг Phase B, записан в installer.UNWIRED_MODULES), а страж
    дрейфа КОНТРАКТА: переименование поля в ports.py или новый параметр без записи в контракт
    краснеет на каждом прогоне, в том числе в дочке."""
    from ai_ops_kit.kernel import ports as _kports
    _spec: _kports.ExecutionSpec = {
        "task": task, "signals": dict(signals or {}), "child_root": str(child_root),
        "feature": feature or "", "write_scope": list(write_scope or []),
        "max_steps": max_steps, "commit": bool(commit), "baseline_diff": bool(baseline_diff),
        "require_fix": bool(require_fix), "sandbox": bool(sandbox),
        "review": bool(review), "author": bool(author)}
    _spec_drift = set(_spec) - set(_kports.ExecutionSpec.__annotations__)
    if _spec_drift:
        raise SystemExit(f"контракт ядра разошёлся с конвейером: полей {sorted(_spec_drift)} "
                         f"нет в kernel/ports.ExecutionSpec — обновите контракт или вызов")


def _pipeline_resolve_policy(policy, sandbox, work_root, write_scope):
    """Фаза 3: политика по умолчанию execution, границы — по work_root.
    v2.81 Containment: даже базовая политика запрещает модели push-ить (block_push=True) —
    доставка (PR) идёт ТОЛЬКО через доверенный delivery-слой, не через tool-loop.
    sandbox=True дополнительно включает allowlist на shell (произвольный shell выключен)
    и denylist на сетевые бинарники — см. tool_broker.sandbox_policy()."""
    if policy is not None:
        return policy
    if sandbox:
        return tool_broker.sandbox_policy(child_root=str(work_root), write_scope=write_scope)
    return tool_broker.Policy(level="execution", child_root=str(work_root), block_push=True,
                              write_scope=write_scope)


def _pipeline_run_gates(plan, gate_ev, committed_sha, signals, not_applicable, exempt_reason, *,
                        reevaluate_only, worktree_rel, child_root, wid):
    """Фаза 7: гейты RunPlan (base + треки) + печать закрытия человеку + персист пройденного
    gate-evidence билда.

    v2.125 (finding живого прогона): security-релевантная НАХОДКА в диффе (новая зависимость/секрет →
    gate_ev.security=fail) обязана блокировать НЕЗАВИСИМО от workflow. QUICK не содержит security-гейта,
    поэтому новая зависимость в QUICK-задаче проскакивала. Форсируем security в оценку, если он упал."""
    _gate_ids = list(plan["gates"])
    if (gate_ev.get("security") or {}).get("status") == "fail" and "security" not in _gate_ids:
        _gate_ids.append("security")
    gates = gate_executor.evaluate(plan["base_workflow"], gate_ev,
                                   gate_ids=_gate_ids, tested_revision=committed_sha,
                                   signals=signals, not_applicable=not_applicable,
                                   exempt_reason=exempt_reason)
    # КТО ЗАКРЫЛ — ЧЕЛОВЕКУ, А НЕ ТОЛЬКО В JSON. Замер 19.08.2026: 19 гейтов из 35 не имеют
    # исполняемого валидатора, и в выводе прогона это ничем не отличалось от проверенного машиной.
    # Строка печатается всегда: молчать о ней там, где мнения нет, значило бы приучать к тому, что
    # её отсутствие ничего не значит.
    _cl = gates.get("closure") or {}
    _cnt = _cl.get("counts") or {}
    _opinion = _cl.get("judged_or_human") or []
    print(f"  гейты: проверено машиной {_cnt.get('validator', 0)} из {len(_gate_ids)}"
          + (f"; остальное — мнение: {', '.join(_opinion)}" if _opinion else "; мнением не закрыт ни один"))

    # v3.8.3: персистим ПРОЙДЕННОЕ gate-evidence билда (кроме security) по committed_sha в worktree/.ai —
    # чтобы последующий reevaluate (после человеко-approval) переиспользовал model-вердикт code_review и
    # артефакт-гейты БЕЗ ре-ревью (недетерминизм) и без зависимости от клоббер-подверженного run-report.
    # Только non-reevaluate билд с коммитом (reevaluate не перетирает источник).
    if committed_sha and not reevaluate_only and worktree_rel is not None:
        try:
            import json as _json
            _passed = {gid: ev for gid, ev in gate_ev.items()
                       if gid != "security" and isinstance(ev, dict) and ev.get("status") == "pass"}
            # пишем в child_root/.ai (репо-корень), ВНЕ worktree-дерева -> не грязним committed_sha
            (Path(child_root) / ".ai").mkdir(parents=True, exist_ok=True)
            (Path(child_root) / ".ai" / f"reevaluate-evidence-{wid}.json").write_text(
                _json.dumps({"sha": committed_sha, "gate_ev": _passed}, ensure_ascii=False), encoding="utf-8")
        # ЗАПИСЬ того же кеша — симметрично чтению: не записали, значит следующий прогон
        # пересчитает. Вердикт не зависит от наличия файла (ревизия 2026-08-11).
        except Exception:  # noqa: BLE001,S110 — потеря кеша не меняет вердикт, пересчитаем
            pass
    return gates


def _pipeline_assess_readiness(gates, coll, signals, plan, child_root, wid, work_root, *,
                               baseline_diff, baseline_checks, committed_sha, base_sha,
                               reviewer_proposer, budget, loop, require_fix,
                               tree_clean_before_checks, tree_clean_after_checks, prepare_ok,
                               commit, effective_approval_signals, security_pack_result, gate_ev):
    """Фаза 8-вердикт: собирает готовность прогона к PR — evidence-ревизия, spec-depth, baseline-diff,
    квалификация окружения, перепроверка одобрений после диффа, связность контуров и итоговый ready.
    Возвращает dict полей, которые далее проецируются в отчёт и в список not_yet."""
    # честность evidence: ревизия сбора совпадает с зафиксированным SHA (если коммитили)
    evidence_revision = coll.get("revision")
    revision_matches = (committed_sha is not None and evidence_revision == committed_sha)

    # v2.106 ready-критерии уровня спеки: spec-depth enforcement + Real Spec-First + сверка критериев
    #    приёмки (B2-14) + context-budget overflow -> _assess_readiness (K6).
    _rd = _assess_readiness(gates, coll, signals, plan, child_root, wid, work_root,
                            baseline_diff=baseline_diff, baseline_checks=baseline_checks,
                            committed_sha=committed_sha, base_sha=base_sha,
                            reviewer_proposer=reviewer_proposer, budget=budget)
    spec_depth_missing = _rd["spec_depth_missing"]
    spec_depth_ok = _rd["spec_depth_ok"]
    spec_incomplete = _rd["spec_incomplete"]
    spec_bad_status = _rd["spec_bad_status"]
    spec_complete_ok = _rd["spec_complete_ok"]
    _level = _rd["level"]
    acceptance_criteria = _rd["acceptance_criteria"]
    context_overflow = _rd["context_overflow"]

    # baseline-diff (finding живого прогона): что правка сломала/починила против базы
    regressions, fixed = _diff_checks(baseline_checks, coll["checks"]) if baseline_diff else ([], [])
    no_regressions = (len(regressions) == 0) if baseline_diff else None
    # P0.1 (аудит v2.79): baseline-режим делает baseline-осведомлённым ТОЛЬКО
    # implementation_verification (красная база не должна блокировать). ВСЕ ОСТАЛЬНЫЕ блокирующие
    # гейты (requirements/specification/plan/code_review/security/треки) остаются обязательными —
    # иначе baseline-diff обходит их и выдаёт ложный ready. unmet_gates уже только блокирующие.
    other_blocking_unmet = [g for g in gates["unmet_gates"] if g != "implementation_verification"]

    # finding аудита (P0.5): ready_for_pr ТРЕБУЕТ реального коммита (committed_sha),
    # evidence на точном SHA и чистого дерева до/после проверок. dry-run (commit=False) НИКОГДА
    # не бывает ready — нет ревизии, к которой привязать draft PR.
    tree_ok = bool(tree_clean_before_checks) and (tree_clean_after_checks is not False)
    # P0.6 + v2.118/v2.121 (P1.4): окружение квалифицировано, если install прошёл ЛИБО хотя бы одна
    # проверка реально отработала (нет симптомов неподготовленного окружения). Нет проверок вовсе
    # ИЛИ все падения — env-симптомы -> НЕ квалифицировано.
    env_qualified = prepare_ok or _env_proven_ok(coll["checks"])

    # v2.121 (P1.2, п.4): ПОСЛЕ диффа перепроверяем, что человеко-одобрение покрывает РЕАЛЬНО
    # изменённые пути. Preflight проверил наличие одобрения ДО правок; здесь — что scope одобрения
    # накрыл то, что модель реально тронула. scope не покрывает изменения -> одобрено не то -> НЕ ready.
    approval_recheck = {"ok": True, "uncovered": []}
    contour_consistency = None
    if commit and committed_sha:
        try:
            from ai_ops_kit.gates import approvals as _appr
            _changed = _committed_changed_files(work_root, committed_sha)
            # v3.35 Product Operating Model: гейт `contour_consistency` ИСПОЛНЯЕТСЯ здесь — на том
            # же diff коммита, что и recheck одобрений. Advisory: несогласованность даёт warn.
            contour_consistency = contour_consistency_evidence(child_root, wid, _changed)
            gate_ev["contour_consistency"] = {
                "status": contour_consistency["status"],
                "provided": contour_consistency["provided"],
                "evidence": contour_consistency["evidence"]}
            # v3.0-rc2 (P0.5): recheck по ЭФФЕКТИВНЫМ сигналам (намерение + findings-derived), а не только
            # входным — иначе scope одобрения для НАЙДЕННОЙ зависимости/секрета не перепроверяется на дифф.
            approval_recheck = _appr.recheck_after_diff(child_root, wid, _changed, signals=effective_approval_signals)
            # v3.0-rc5 (P1.2): SEMANTIC dependency approval — каждая НОВАЯ зависимость из диффа должна
            # покрываться ApprovalRecord с covers_packages для ИМЕННО этого пакета (не только путём файла).
            _dep_findings = [f for r in ((security_pack_result or {}).get("results") or [])
                             for f in (r.get("findings") or []) if f.get("type") == "new_dependency"]
            if _dep_findings:
                _dep_rc = _appr.recheck_dependencies(child_root, wid, _dep_findings)
                if not _dep_rc.get("ok"):
                    approval_recheck = {"ok": False,
                                        "uncovered": (approval_recheck.get("uncovered") or []) + _dep_rc["uncovered"],
                                        "dependency_uncovered": _dep_rc["uncovered"]}
        except Exception as _e:  # noqa: BLE001 — v2.123 (P0.2b): approval FAIL-CLOSED. Сбой recheck НЕ
            # трактуется как «покрыто»: для одобрения безопаснее заблокировать, чем пропустить непроверенное.
            approval_recheck = {"ok": False, "uncovered": [{"domain": "*", "reason": f"recheck упал: {_e}"}],
                                "error": str(_e)}
    approvals_cover_ok = bool(approval_recheck.get("ok"))

    # v3.8.4 (finding живой квалификации): reevaluate-only — легитимно завершённый прогон (0 шагов,
    # переоценка существующего committed HEAD после человеко-одобрения). Остальные условия base_ok
    # (committed_sha/revision/tree/env/approvals) по-прежнему строги.
    base_ok = (loop["stopped"] in ("done", "reevaluate-only")) and (committed_sha is not None) \
        and revision_matches and tree_ok and env_qualified and approvals_cover_ok
    # ПРИЁМКА КАК УСЛОВИЕ READY: B2-30 (сверка состоялась, критерий не выполнен) И
    # green-means-checked (судья поднят и отработал, но сверка не установлена — 0 reads / рубер-штамп,
    # прежде давало READY_FOR_PR на QUICK). Разбор и граница #176 — в предикате.
    acceptance_block, acceptance_block_reason = acceptance_blocks_ready(acceptance_criteria)
    if baseline_diff:
        # критерий «no-regressions»: implementation_verification baseline-осведомлён (красная база
        # не блокирует), НО все ОСТАЛЬНЫЕ блокирующие гейты обязательны (P0.1). require_fix (для
        # fix-задач): дополнительно требуем, чтобы правка РЕАЛЬНО починила падавшую проверку.
        ready = base_ok and not acceptance_block and no_regressions and (not other_blocking_unmet) \
            and (not require_fix or len(fixed) > 0) and spec_depth_ok and (not context_overflow) \
            and spec_complete_ok
        ready_criterion = "no-regressions+require-fix" if require_fix else "no-regressions"
    else:
        ready = base_ok and not acceptance_block and (not gates["blocked"]) and spec_depth_ok \
            and (not context_overflow) and spec_complete_ok
        ready_criterion = "all-green"
    return {
        "evidence_revision": evidence_revision, "revision_matches": revision_matches,
        "spec_depth_missing": spec_depth_missing, "spec_depth_ok": spec_depth_ok,
        "spec_incomplete": spec_incomplete, "spec_bad_status": spec_bad_status,
        "spec_complete_ok": spec_complete_ok, "level": _level,
        "acceptance_criteria": acceptance_criteria, "context_overflow": context_overflow,
        "regressions": regressions, "fixed": fixed, "no_regressions": no_regressions,
        "other_blocking_unmet": other_blocking_unmet, "env_qualified": env_qualified,
        "approval_recheck": approval_recheck, "approvals_cover_ok": approvals_cover_ok,
        "contour_consistency": contour_consistency, "ready": ready, "ready_criterion": ready_criterion,
        "acceptance_block": acceptance_block, "acceptance_block_reason": acceptance_block_reason,
        "baseline_diff": baseline_diff, "baseline_checks": baseline_checks}


def _pipeline_build_report(*, plan, child_root, profile, sandbox, pol, loop, applied,
                           worktree_rel, base_binding, resume_info, prepare, prepare_ok,
                           env_qualified, prepare_mutated_tree, work_branch, committed_sha,
                           work_produced_by, tree_clean_before_checks, author, author_proposer,
                           authored, spec_prestage_bad, ev, rd, gates, ready, delivery, delivery_plan,
                           overall_status, not_yet):
    """Фаза сборки отчёта прогона: чистая проекция состояния фаз в единый result-dict.
    Локальные имена совпадают с именами из фаз, чтобы тело отчёта осталось прозрачным
    (и швы-пробы, ссылающиеся на конкретные строки, оставались стабильны)."""
    from ai_ops_kit.gates import spec_levels as _sl   # для report.spec_first (_spec_path) ниже
    wid = plan["workitem_id"]
    _changed_for_verification = ev["changed_for_verification"]
    coll = ev["coll"]
    tree_clean_after_checks = ev["tree_clean_after_checks"]
    regression_proof = ev["regression_proof"]
    exempt = ev["exempt"]
    tests_warn = ev["tests_warn"]
    ui_evidence_bundle = ev["ui_evidence_bundle"]
    seam_advisory = ev["seam_advisory"]
    reviews = ev["reviews"]
    security_pack_result = ev["security_pack_result"]
    evidence_revision = rd["evidence_revision"]
    revision_matches = rd["revision_matches"]
    other_blocking_unmet = rd["other_blocking_unmet"]
    approval_recheck = rd["approval_recheck"]
    contour_consistency = rd["contour_consistency"]
    regressions, fixed = rd["regressions"], rd["fixed"]
    no_regressions = rd["no_regressions"]
    baseline_diff = rd["baseline_diff"]
    baseline_checks = rd["baseline_checks"]
    ready_criterion = rd["ready_criterion"]
    _level = rd["level"]
    spec_depth_missing = rd["spec_depth_missing"]
    spec_depth_ok = rd["spec_depth_ok"]
    spec_incomplete = rd["spec_incomplete"]
    spec_complete_ok = rd["spec_complete_ok"]
    context_overflow = rd["context_overflow"]
    acceptance_criteria = rd["acceptance_criteria"]
    report = {
        "schema_version": 1, "kind": "execution-pipeline",
        "workitem_id": plan["workitem_id"],
        "child_root": str(child_root),          # нужен вывода: уровень детализации берётся из репо
        "base_workflow": plan["base_workflow"],
        "profile": {"stacks": [s.get("language") for s in profile.get("stacks", [])],
                    "undetermined": profile.get("undetermined", [])},
        "containment": _build_containment(sandbox, pol, loop),
        "loop": _build_loop_section(loop, applied),
        "isolation": {"worktree": worktree_rel},   # каталог изоляции (None -> прогон в основном дереве)
        "base_binding": base_binding,              # v3.0.1 (P0): base_ref + base_sha, от которого форкнута ветка
        "resume": resume_info,                     # v2.109: продолжение поверх подтверждённой работы (None если resume не запрошен)
        "prepare": prepare,                        # установка зависимостей стека (npm ci/... ) в worktree; None вне изоляции
        "prepare_ok": prepare_ok,                  # install-команды стека прошли (для наблюдаемости)
        "env_qualified": env_qualified,            # v2.118: install прошёл ЛИБО проверки реально отработали
        "prepare_mutated_tree": prepare_mutated_tree,  # P0.6: подготовка меняла tracked -> откачено до модели
        "commit": _build_commit_section(work_branch, committed_sha, evidence_revision,
                                        revision_matches, _changed_for_verification,
                                        work_produced_by, tree_clean_before_checks,
                                        tree_clean_after_checks),
        # v3.30: доказательство исправления — в отчёте, а не только в вердикте гейта: постфактум
        # видно, ЧЕМ подтверждена правка (или почему не подтверждена).
        "regression": regression_proof,
        "checks": coll["checks"],
        "exemptions": sorted(exempt),          # флаги, освобождённые как неприменимые (видно, не тихо)
        "tests_warn": tests_warn,              # громкий сигнал об отсутствии тестов (если есть)
        "gates": {"evaluated": gates["evaluated_gates"], "unmet": gates["unmet_gates"],
                  "blocked": gates["blocked"],
                  "other_blocking_unmet": other_blocking_unmet,   # P0.1: блокирующие ≠ impl_verification
                  # КТО ЗАКРЫЛ: разбивка validator/judge/writer/human. Без неё отчёт утверждал
                  # «гейты пройдены» одинаково и там, где считала машина, и там, где высказался
                  # судья. 19 гейтов из 35 не имеют валидатора вовсе.
                  "closure": gates.get("closure"),
                  # evidence/аудит (аудит v2.79): полные per-gate результаты, не только сводка
                  "gate_results": gates.get("gate_results"),
                  "tested_revision": committed_sha},
        # v2.121 (P1.2 п.4): покрыло ли человеко-одобрение фактически изменённые пути (после диффа)
        "approval_recheck": approval_recheck,
        # v3.35.2: НАХОДКИ ГЕЙТА СВЯЗНОСТИ ДОХОДЯТ ДО ЧЕЛОВЕКА. Гейт исполнялся и писал evidence, но
        # вывод прогона о нём молчал: «описание продукта отстало от кода» существовало только внутри
        # yaml-артефакта. Гейт, чьи находки не видны, — это гейт, которого нет.
        "contour_consistency": contour_consistency,
        # v2.83 Full RunPlan: трейс независимых ревью (какие ai-review гейты судились, вердикт,
        # что читал судья, что отклонено). None -> ревью не запускалось (нет --review/reviewer).
        "reviews": reviews,
        # v3.1.9: UIEvidenceBundle, собранный на ТОЧНОМ committed_sha (qualification evidence). None,
        # если калибровка выкл / evidence инжектировано / нет коммита. commit_sha в bundle привязан.
        "ui_evidence": ui_evidence_bundle,
        # v3.7.4: seam-scan advisory (дефект шва по дифу base..committed). would_block=true -> шов без
        # доказанного перехода; пока advisory (не влияет на overall), станет gate после обкатки.
        "seam_scan": seam_advisory,
        # v2.95: детерминированный security-скан (секреты/новые зависимости/injection-флаги). None,
        # если гейта security нет в плане или не коммитили. Закрывает no_secrets/deps_approved (факты);
        # no_injection_surface — судье. Находка -> security блокирует.
        # ЗАЯВКА #139 (вторая половина): здесь стояли ровно четыре поля, и `domain_results` — где
        # лежат САМИ находки (path/line/класс) и `applies_because` — в отчёт не попадали вовсе.
        # Гейт отправляет человека в этот артефакт со словами «блокирующие домены (critical/high
        # находки)», поэтому отчёт без находок делает утверждение гейта непроверяемым. Проекция
        # `security_pack.for_report` — белый список полей: значения секретов и содержимое файлов в
        # отчёт не уезжают (он лежит в репозитории и попадает в PR).
        "security_scan": _security_pack_for_report(security_pack_result),
        # v2.86 Product Authoring: трейс произведённых артефактов (requirements/plan) — что
        # авторизовано, валидна ли форма, какие required_evidence закрыты. None -> без --author.
        "authored": authored,
        # baseline-diff: None вне режима; иначе — статусы проверок на базе + регрессии/починки
        "baseline": ({"checks": {k: (v or {}).get("status") for k, v in (baseline_checks or {}).items()},
                      "regressions": regressions, "fixed": fixed, "no_regressions": no_regressions}
                     if baseline_diff else None),
        "ready_criterion": ready_criterion,    # all-green | no-regressions
        # v2.106 enforcement: spec-depth (незакрытые разделы уровня, мапящиеся на unmet-гейты) и
        # context-budget overflow — блокируют ready наравне с гейтами.
        "spec_depth": {"level": _level, "missing": spec_depth_missing, "ok": spec_depth_ok},
        # v2.110 Real Spec-First: реальный spec.yaml существует, но неполон -> блокирует implementation
        "spec_first": {"artifact_present": bool(spec_incomplete) or _sl._spec_path(child_root, wid).is_file(),
                       "incomplete_sections": spec_incomplete, "ok": spec_complete_ok,
                       # v2.123 (P0.1): pre-authoring запущен ДО реализации; невалидная спека -> 0 кода
                       "prestage": {"ran": bool(author and author_proposer is not None),
                                    "invalid": [e.get("gate") for e in spec_prestage_bad],
                                    "implementation_skipped": bool(spec_prestage_bad)}},
        "context_overflow": context_overflow,
        "acceptance_criteria": acceptance_criteria,   # B2-14: сверялись ли критерии с результатом
        # honest: «готово к PR» = петля done + коммит + evidence на SHA + prepare_ok + spec-depth +
        # не-overflow + (all-green: гейты не блокируют | no-regressions: нет новых провалов И blocking-гейты пройдены)
        "ready_for_pr": ready,
        "delivery": delivery,                  # P0.4: статус доставки draft PR отдельно от ready
        "delivery_plan": delivery_plan,        # v3.0.15 (P0): план для контроллера при defer_delivery
        "overall_status": overall_status,      # error | delivery-failed | delivered | ready-undelivered
        "draft_pr": delivery.get("pr"),        # результат открытия PR (None если deferred/не открыт)
        "not_yet": not_yet,
    }
    return report


def _pipeline_check_invariants(report):
    """v3.38 (K7): инварианты pipeline — fail-closed, нарушение записывается в отчёт."""
    from ai_ops_kit.gates.invariants import check_invariant as _ci
    _pipe_breaches = []
    for _inv_id, _kw in [
        ("INV-PIPELINE-001", {"result": report}),
        ("INV-PIPELINE-002", {"ready_for_pr": report.get("ready_for_pr"),
                               "overall_status": report.get("overall_status")}),
        ("INV-PIPELINE-004", {"changed_files": report.get("commit", {}).get("changed_files", [])}),
    ]:
        try:
            if not _ci(_inv_id, **_kw):
                _pipe_breaches.append(_inv_id)
        except (KeyError, TypeError):
            pass
    if _pipe_breaches:
        report["invariant_breaches"] = _pipe_breaches


def run_pipeline(task, signals, child_root, proposer, policy=None, budget=None,
                 max_steps=40, feature=None, commit=False, allow_missing_tests=True,
                 isolate=False, open_pr=False, install_deps=True, baseline_diff=False,
                 require_fix=False, discard_previous=False, sandbox=False,
                 review=False, reviewer_proposer=None,
                 author=False, author_proposer=None, plan=None, context_prelude=None,
                 resume=False, resume_context=None, write_scope=None, base=None, defer_delivery=False,
                 calibrated_enforcement=False, ui_evidence=None,   # v3.1.8 калиброванное UI-enforcement
                 strict_judge_qualified=True,   # v3.7.1: есть ли QUALIFIED security/integration судья
                 security_reviewer_proposer=None,   # v3.7.3 (#5): ОТДЕЛЬНЫЙ security-судья (не общий reviewer)
                 reevaluate_only=False):   # v3.8.4: переоценить гейты существующего HEAD БЕЗ переавторинга
    """Один прогон движка: [worktree-изоляция] -> детект -> правки через tool-loop ->
    [commit на ветке] -> evidence (на зафиксированном SHA) -> гейты RunPlan.

    v2.108 (Operational Context): context_prelude — compiled payload из ContextBundle (реальное
    содержимое релевантных правил/решений/спек), который РЕАЛЬНО попадает в prompt модели (prepend к
    base_context tool loop) — не только статистика в отчёте.

    v2.109 (Real Resume): resume=True — ПРОДОЛЖИТЬ WorkItem поверх уже подтверждённой работы, а не
    начинать заново. Ветка ai-ops/<wid> и её коммиты НЕ удаляются (иначе потеряли бы результат);
    worktree переиспользуется (или пере-подключается к сохранившейся ветке). resume_context —
    состояние из RunHandoff (что сделано/решения/следующий шаг), реально подаётся модели в начало
    prompt, чтобы она продолжила, а не переделала подтверждённое.

    v2.94 (One Run Transaction): если plan передан контроллером — используем ЕГО (не строим второй),
    чтобы pipeline и lifecycle жили в одной транзакции с общим WorkItem/RunPlan."""
    # K0-проводка: сверка параметров прогона с контрактом ядра (страж дрейфа kernel/ports).
    _pipeline_check_spec_drift(task, signals, child_root, feature, write_scope,
                               max_steps=max_steps, commit=commit, baseline_diff=baseline_diff,
                               require_fix=require_fix, sandbox=sandbox, review=review, author=author)
    child_root = Path(child_root)
    signals = dict(signals or {})
    signals.setdefault("task_text", task)

    # 2. план (нужен workitem_id для имени ветки/worktree). v2.94: принимаем готовый план от
    #    контроллера; иначе строим сами (обратная совместимость: прямой вызов run_pipeline).
    if plan is None:
        plan = run_plan.build_plan(signals, workitem_id=feature)
    wid = plan["workitem_id"]

    # 1b. изоляция + base-binding + resume -> _setup_isolation (K6). Прогон в отдельном worktree на
    #     ветке ai-ops/<id>, основное дерево child не трогается; при отказе — ранний честный выход.
    _iso = _setup_isolation(child_root, wid, base, isolate=isolate, resume=resume,
                            reevaluate_only=reevaluate_only, discard_previous=discard_previous,
                            open_pr=open_pr)
    if _iso.get("error"):
        return _iso["error"]
    work_root, worktree_rel = _iso["work_root"], _iso["worktree_rel"]
    resume_info, base_binding = _iso["resume_info"], _iso["base_binding"]
    base_ref, base_sha, delivery_pf = _iso["base_ref"], _iso["base_sha"], _iso["delivery_pf"]

    # 1. детект стека (в рабочем дереве)
    profile = project_detector.detect(work_root)

    # 3. политика по умолчанию: execution, границы — по work_root (containment внутри помощника).
    pol = _pipeline_resolve_policy(policy, sandbox, work_root, write_scope)
    is_git = _git(work_root, "rev-parse", "--is-inside-work-tree")[0] == 0

    # 3b/3c. фаза install-deps (K6: _prepare_environment).
    prepare, prepare_ok, baseline_checks, prepare_mutated_tree = _prepare_environment(
        profile, work_root, pol, is_git, install_deps=install_deps, isolate=isolate,
        baseline_diff=baseline_diff)

    # 4/4a. фаза spec-gate: prompt-контекст (task+профиль+prelude/resume+провалы базы) + pre-authoring
    #       Spec-First (K6: _assemble_context_and_author).
    ctx, authored, authored_ev, spec_prestage_bad = _assemble_context_and_author(
        task, profile, plan, wid, work_root, budget,
        context_prelude=context_prelude, resume_context=resume_context,
        baseline_diff=baseline_diff, baseline_checks=baseline_checks,
        author=author, author_proposer=author_proposer, reevaluate_only=reevaluate_only)

    # 4b. фаза execute (tool-loop): реализация + распознавание факта правок (K6: _run_tool_loop).
    loop, applied, shell_changed, self_committed, head_sha = _run_tool_loop(
        proposer, work_root, pol, ctx, is_git, budget=budget, max_steps=max_steps,
        reevaluate_only=reevaluate_only, spec_prestage_bad=spec_prestage_bad)

    # 5. фаза commit: фиксация на ветке ai-ops/<wid> ДО evidence — evidence бьётся о ТОЧНЫЙ SHA
    #    (K6: _commit_work).
    committed_sha, work_branch, work_produced_by, tree_clean_before_checks = _commit_work(
        work_root, wid, task, is_git, applied, authored, shell_changed, self_committed, head_sha,
        commit=commit, reevaluate_only=reevaluate_only)

    # 6. evidence на зафиксированном SHA + наполнение gate_ev (collect/intake/regression/authored/
    #    reevaluate-seed/освобождения/UI-evidence/seam-scan/reviews/security) -> _assemble_evidence (K6).
    _ev = _assemble_evidence(
        profile, work_root, pol, child_root, wid, plan, signals, loop,
        commit=commit, is_git=is_git, committed_sha=committed_sha, base_sha=base_sha,
        authored_ev=authored_ev, allow_missing_tests=allow_missing_tests,
        calibrated_enforcement=calibrated_enforcement, ui_evidence=ui_evidence,
        review=review, reviewer_proposer=reviewer_proposer, budget=budget,
        strict_judge_qualified=strict_judge_qualified,
        security_reviewer_proposer=security_reviewer_proposer, reevaluate_only=reevaluate_only)
    # распаковываем только то, что нужно ФАЗАМ ниже (gates/readiness); поля, идущие лишь в отчёт,
    # проецируются прямо из _ev в _pipeline_build_report — не плодим неиспользуемые локали.
    coll = _ev["coll"]
    gate_ev = _ev["gate_ev"]
    tree_clean_after_checks = _ev["tree_clean_after_checks"]
    not_applicable = _ev["not_applicable"]
    exempt_reason = _ev["exempt_reason"]
    security_pack_result = _ev["security_pack_result"]
    effective_approval_signals = _ev["effective_approval_signals"]

    # 7. гейты RunPlan (base + треки) + печать закрытия человеку + персист gate-evidence билда.
    gates = _pipeline_run_gates(plan, gate_ev, committed_sha, signals, not_applicable, exempt_reason,
                                reevaluate_only=reevaluate_only, worktree_rel=worktree_rel,
                                child_root=child_root, wid=wid)

    # 8-вердикт: готовность к PR — evidence-ревизия, spec-depth, baseline-diff, окружение,
    #            перепроверка одобрений и связности контуров, итоговый ready (фазовый помощник).
    rd = _pipeline_assess_readiness(
        gates, coll, signals, plan, child_root, wid, work_root,
        baseline_diff=baseline_diff, baseline_checks=baseline_checks,
        committed_sha=committed_sha, base_sha=base_sha,
        reviewer_proposer=reviewer_proposer, budget=budget, loop=loop,
        require_fix=require_fix, tree_clean_before_checks=tree_clean_before_checks,
        tree_clean_after_checks=tree_clean_after_checks, prepare_ok=prepare_ok,
        commit=commit, effective_approval_signals=effective_approval_signals,
        security_pack_result=security_pack_result, gate_ev=gate_ev)
    ready = rd["ready"]
    env_qualified = rd["env_qualified"]
    approval_recheck = rd["approval_recheck"]
    approvals_cover_ok = rd["approvals_cover_ok"]
    acceptance_block = rd["acceptance_block"]
    acceptance_block_reason = rd["acceptance_block_reason"]
    spec_depth_missing = rd["spec_depth_missing"]
    spec_incomplete = rd["spec_incomplete"]
    spec_bad_status = rd["spec_bad_status"]
    context_overflow = rd["context_overflow"]

    # 8. доставка (P0.4 аудит v2.79): draft PR отделён от ready_for_pr. Если --open-pr запрошен,
    #    УСПЕХ прогона требует реально открытого PR; провал доставки не маскируется зелёным.
    # v3.0.16 Phase A (finding аудита #1): run_pipeline НИКОГДА не выполняет внешнюю доставку — только
    # возвращает DeliveryPlan. Единственный разрешённый вызывающий _deliver_pr — транзакционный контроллер
    # (ai_ops_run), который доставляет ТОЛЬКО после durable-фиксации RunHandoff+report+journal +
    # DeliveryIntent. Так прямой вызов run_pipeline(..., open_pr=True) больше НЕ может обойти lifecycle-
    # барьер (прежде defer_delivery=False давал inline-доставку). Параметр defer_delivery устарел и
    # игнорируется (внешнее действие из pipeline запрещено архитектурно).
    delivery, delivery_plan, can_deliver = _plan_delivery(
        open_pr, ready, committed_sha, work_branch, base_binding, base_ref, base_sha,
        work_root, wid, task, delivery_pf)
    # ready есть, доставка НЕ выполнена в pipeline: overall — «готово к доставке» (контроллер финализирует).
    overall_status = _compute_overall_status(ready, can_deliver, open_pr)

    not_yet = _build_not_yet_list(commit, env_qualified, open_pr, spec_prestage_bad,
                                  spec_depth_missing, spec_incomplete, spec_bad_status,
                                  context_overflow, approvals_cover_ok, approval_recheck,
                                  acceptance_block_reason=(acceptance_block_reason if acceptance_block else None), checks=coll["checks"])

    # сборка единого отчёта прогона (чистая проекция состояния фаз) + fail-closed инварианты (K7).
    report = _pipeline_build_report(
        plan=plan, child_root=child_root, profile=profile, sandbox=sandbox, pol=pol,
        loop=loop, applied=applied, worktree_rel=worktree_rel, base_binding=base_binding,
        resume_info=resume_info, prepare=prepare, prepare_ok=prepare_ok,
        env_qualified=env_qualified, prepare_mutated_tree=prepare_mutated_tree,
        work_branch=work_branch, committed_sha=committed_sha,
        work_produced_by=work_produced_by, tree_clean_before_checks=tree_clean_before_checks,
        author=author, author_proposer=author_proposer, authored=authored,
        spec_prestage_bad=spec_prestage_bad, ev=_ev, rd=rd, gates=gates, ready=ready,
        delivery=delivery, delivery_plan=delivery_plan, overall_status=overall_status,
        not_yet=not_yet)
    _pipeline_check_invariants(report)
    return report


def _assemble_context_and_author(task, profile, plan, wid, work_root, budget, *,
                                 context_prelude, resume_context, baseline_diff, baseline_checks,
                                 author, author_proposer, reevaluate_only):
    """Фаза spec-gate: собрать base_context tool-loop (task+профиль+prelude/resume+провалы базы) и
    pre-authoring по Spec-First (автор -> валидация формы -> реализация только при валидной спеке).
    v3.38 (K6): вынесено из run_pipeline. -> (ctx, authored, authored_ev, spec_prestage_bad)."""
    ctx = f"{task}\n\n{_profile_summary(profile)}"
    # v2.108: compiled payload из ContextBundle РЕАЛЬНО в prompt (не только отчёт).
    if context_prelude:
        ctx = context_prelude + "\n\n" + ctx
    # v2.109 Real Resume: состояние из RunHandoff в начало prompt — модель ПРОДОЛЖАЕТ, а не переделывает.
    if resume_context:
        ctx = resume_context + "\n\n" + ctx
    if baseline_diff:
        fails = _baseline_failure_summary(baseline_checks)
        if fails:
            ctx += ("\n\n=== ТЕКУЩИЕ ПРОВАЛЫ ПРОВЕРОК НА БАЗЕ (почини относящиеся к задаче; "
                    "не ломай остальное) ===\n" + fails)
    # 4a. v2.123 (P0.1) Spec-First: СНАЧАЛА автор (requirements/plan/spec), движок валидирует ФОРМУ.
    #     Невалидный артефакт -> tool loop НЕ запускается (0 impl-вызовов). Валидные -> в prompt.
    #     Качество судит независимый ревьюер (--review)/человек, не эта проверка формы.
    authored, authored_ev = None, {}
    spec_prestage_bad = []
    if author and author_proposer is not None and not reevaluate_only:
        authored_ev, authored, _wrote_art = _run_authoring(
            author_proposer, work_root, plan["gates"], {}, wid, task, budget)
        spec_prestage_bad = [e for e in (authored or []) if e.get("valid") is False]
        if not spec_prestage_bad:
            _spec_ctx = _authored_context(authored, work_root, wid)
            if _spec_ctx:
                ctx = _spec_ctx + "\n\n" + ctx
    return ctx, authored, authored_ev, spec_prestage_bad


def _run_tool_loop(proposer, work_root, pol, ctx, is_git, *, budget, max_steps,
                   reevaluate_only, spec_prestage_bad):
    """Фаза execute: снять HEAD до правок, прогнать реализацию через модель (или пропустить при
    reevaluate/невалидной pre-spec), распознать факт правок из git (broker/shell/model-commit).
    v3.38 (K6): вынесено из run_pipeline. -> (loop, applied, shell_changed, self_committed, head_sha)."""
    # HEAD НА СТАРТЕ — точка отсчёта «что произвёл ИМЕННО ЭТОТ прогон». С base_sha сравнивать нельзя:
    # при resume/reevaluate и на ушедшей вперёд ветке HEAD != база ДО работы -> кит увидел бы работу,
    # которой не делали.
    _rc_hb, _out_hb, _ = _git(work_root, "rev-parse", "HEAD") if is_git else (1, "", "")
    head_before = _out_hb.strip() if _rc_hb == 0 else None
    # 4b. tool-loop: реализация. Пропускается при невалидной pre-spec (Spec-First: нет спеки -> нет кода).
    if reevaluate_only:
        # v3.8.4: НЕ авторим и НЕ гоняем loop — переоцениваем существующий HEAD как есть (0 вызовов).
        loop = {"schema_version": 1, "kind": "tool-loop-report", "stopped": "reevaluate-only",
                "steps": 0, "model_calls": 0, "executed": [], "denied": [], "evidence": [], "transcript": []}
    elif spec_prestage_bad:
        loop = {"schema_version": 1, "kind": "tool-loop-report", "stopped": "spec-prestage-failed",
                "steps": 0, "model_calls": 0, "executed": [], "denied": [], "evidence": [], "transcript": []}
    else:
        loop = tool_loop.run_loop(proposer, work_root, pol, budget=budget,
                                  max_steps=max_steps, base_context=ctx)
    applied = [e for e in loop["executed"] if e.get("op") == "write" and e.get("ok")]
    # v2.93: факт правок из git (tracked-diff ИЛИ новые untracked), не только из счётчика write —
    # иначе правки через shell (sed/форматтер) не считались «применено» и коммит терялся.
    shell_changed = bool(applied) or (is_git and _has_changes(work_root))
    # НАХОДКА ИИ-СРЕДЫ: модель может закоммитить САМА — дерево чистое, applied пусто, _has_changes False,
    # хотя коммит уже на ветке. Третий факт: HEAD сдвинулся ЗА ЭТОТ прогон.
    self_committed, head_sha = (_head_advanced(work_root, head_before)
                                if is_git else (False, None))
    return loop, applied, shell_changed, self_committed, head_sha


def main(argv):
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
