#!/usr/bin/env python3
"""parallel_live_dispatch.py — проводка НАСТОЯЩЕГО конкурентного мультипакетного прогона в живой
run-путь через ЯВНЫЙ opt-in `ai-ops run --parallel`.

ЗАЧЕМ. `engine/parallel_live.run_live_concurrent` (disposable-клон+ветка+прогон на пакет,
governed fan-in на СВЕЖЕМ integration-SHA) был построен и протестирован, но не имел ни одного
рабочего вызывателя — жил дормантным инвентарём («построено, но не проведено в контур»). Этот
модуль — тонкий диспетч: он декомпозирует задачу (`atomic_planner`) и, если план мультипакетный,
проводит его через `run_live_concurrent`. Так у concurrent-пути появляется настоящий вызыватель.

ГРАНИЦЫ (осознанно узкие, чтобы не дестабилизировать дефолт):
  - Дефолтное поведение `run` НЕ меняется: диспетч зовётся ТОЛЬКО при явном `--parallel`.
  - Основной checkout НЕ трогается: `run_live_concurrent` работает на одноразовых клонах.
  - Задача атомарна (или один пакет) -> диспетч возвращает None: вызыватель делает обычный прогон.
  - Диспетч НЕ владеет доставкой: `run_live_concurrent` возвращает DeliveryPlan для канонического
    controller'а; прямого push/gh здесь нет.

Только stdlib + существующие модули кита.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from ai_ops_kit.shared import gitio                       # noqa: E402
from ai_ops_kit.engine import atomic_planner              # noqa: E402
from ai_ops_kit.engine import parallel_live               # noqa: E402


def _package_task(task: str, pkg: dict) -> str:
    """Инструкция пакета: общий текст задачи + подзадача пакета (title). Пакет исполняется своим
    прогоном в своём клоне, поэтому получает СВОЙ, а не одинаковый со всеми, текст."""
    title = pkg.get("title") or pkg["id"]
    return f"{task}\n\nПодзадача пакета {pkg['id']}: {title}".strip()


def build_work_graph(signals, wid, child_root):
    """decompose -> (WorkGraph, task_map). (None, None), если задача атомарна или пакет один.

    Чистая (кроме чтения плана через atomic_planner): удобно проверять маршрутизацию на данных.
    """
    wp = atomic_planner.decompose(signals, wid=wid, child_root=Path(child_root))
    pkgs = wp.get("work_packages") or []
    if not (wp.get("should_decompose") and len(pkgs) >= 2):
        return None, None
    wg = {"schema_version": 1, "kind": "WorkGraph", "id": wid, "feature": wid,
          "execution_mode": "hybrid", "packages": pkgs}
    task_text = signals.get("task_text") or ""
    task_map = {p["id"]: _package_task(task_text, p) for p in pkgs}
    return wg, task_map


def run_parallel_live(task, signals, child_root, *, feature=None, provider=None, model=None,
                      base=None, open_pr=False, max_steps=40, repo_slug=None,
                      contract_shas=None, run_fn=None, runner=None, author=True, review=True,
                      sandbox=False, baseline_diff=False, install_deps=True, require_fix=False,
                      review_fix_attempts=0, budget=None):
    """ЯВНЫЙ opt-in `--parallel`: декомпозировать задачу и провести мультипакетный план через
    `parallel_live.run_live_concurrent` (настоящая конкурентность, disposable-клон на пакет).

    -> rec (dict), обогащённый `rec["parallel"]=True`, при мультипакетном плане;
       None, если задача атомарна — тогда вызыватель делает обычный (single-path) прогон.

    `run_fn`/`runner` — точки инъекции для тестов (по умолчанию `ai_ops_run.run` и
    `run_live_concurrent`), чтобы проверять маршрутизацию без запуска реальных клонов/провайдера.
    """
    child_root = Path(child_root)
    signals = dict(signals or {})
    signals.setdefault("task_text", task)
    wid = feature or signals.get("feature") or "WG"
    wg, task_map = build_work_graph(signals, wid, child_root)
    if wg is None:
        return None  # атомарна/один пакет -> обычный прогон (дефолт не меняется)
    binding = gitio.resolve_base(child_root, base)
    if not binding.get("resolved"):
        return {"proceed": False, "stage": "preflight", "parallel": True,
                "reason": f"base-preflight: {binding.get('reason')}"}
    from ai_ops_kit.shared import budget as budget_mod
    try:
        budget = budget_mod.resolve_budget(budget, signals.get("execution_budget"))
        budget.ensure_execution_supported()
    except (ValueError, budget_mod.BudgetExceeded) as exc:
        return {"proceed": False, "stage": "preflight", "parallel": True,
                "reason": f"parallel budget unsupported: {exc}"}
    reason = _policy_refusal(signals, wg, child_root, wid, provider, model, max_steps)
    if reason:
        return {"proceed": False, "stage": "preflight", "parallel": True, "reason": reason}
    reconciled = None
    if open_pr:
        from ai_ops_kit.engine.ai_ops_run import _reconcile_pending_delivery, _unresolved_intents
        try:
            reconciled = _reconcile_pending_delivery(child_root / "features", wid, child_root)
            unresolved = _unresolved_intents(child_root / "features", wid, branch=f"ai-ops/{wid}")
        except Exception as exc:  # noqa: BLE001 — неизвестный исход не разрешает новую трату/доставку
            return {"proceed": False, "stage": "preflight", "parallel": True,
                    "reason": f"parallel delivery reconciliation unavailable: {exc}"}
        if unresolved:
            return {"proceed": False, "stage": "preflight", "parallel": True,
                    "reason": "parallel pending DeliveryIntent не сверён; новые модели не запущены",
                    "reconciliation": reconciled}
    base_sha = binding["base_sha"]
    if run_fn is None:
        from ai_ops_kit.engine import ai_ops_run
        run_fn = ai_ops_run.run
    dispatch = runner or parallel_live.run_live_concurrent
    rec = dispatch(wg, str(child_root), base_sha, task_map, signals, run_fn,
                   repo_slug=repo_slug, contract_shas=contract_shas, integration_branch=f"ai-ops/{wid}",
                   run_options={"provider_name": provider, "model": model, "base": binding["base_ref"],
                                "max_steps": max_steps, "author": author, "review": review,
                                "sandbox": sandbox, "baseline_diff": baseline_diff,
                                "install_deps": install_deps, "require_fix": require_fix,
                                "review_fix_attempts": review_fix_attempts, "budget": budget})
    if isinstance(rec, dict):
        rec["parallel"] = True
        rec["budget"] = budget.to_dict()
        rec["base_binding"] = binding
        rec["delivery_requested"] = bool(open_pr)
        rec["reconciliation"] = reconciled
        rec["integration_source"] = rec.get("delivery_plan")
        if open_pr:
            _deliver_parallel(rec, child_root, wid, task, binding)
        else:
            rec["delivery"] = {"requested": False, "status": "not-requested"}
        from ai_ops_kit.shared import lifecycle_store
        saved = lifecycle_store.durable_write_json(child_root / "features" / wid / "parallel-report.json", rec)
        if not saved.get("ok"):
            rec["proceed"] = False
            rec["stage"] = "lifecycle"
            rec["reason"] = "parallel report не сохранён durable; integration source сохранён в результате"
    return rec


def _policy_refusal(signals, wg, root, wid, provider, model, max_steps):
    """ДО клонов/моделей: не теряем неподдерживаемую политику и чужие approvals."""
    import re
    from ai_ops_kit.gates import approvals
    from ai_ops_kit.providers import orchestrator
    if not provider:
        return "--parallel требует явно разрешённый provider; скрытого fallback нет"
    try:
        orchestrator.make_provider(provider, model)  # создаёт adapter, НЕ вызывает модель
    except (SystemExit, ValueError) as exc:
        return f"parallel provider unsupported: {exc}"
    if not isinstance(max_steps, int) or isinstance(max_steps, bool) or max_steps < 1:
        return "parallel max_steps должен быть положительным целым"
    for identity in [wid, *[p.get("id") for p in wg["packages"]]]:
        if not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", identity):
            return "parallel feature/package id должен быть одним безопасным сегментом пути"
    budgets = [signals.get(k) for k in ("budget_contract", "budget")]
    budgets += [p.get("budget") for p in wg["packages"]]
    if any(b is not None and (not isinstance(b, dict) or any(v is not None for v in b.values()))
           for b in budgets):
        return ("parallel budget unsupported: общий/пакетный лимит нельзя гарантировать "
                "независимыми run; параллельный прогон не начат (0 model calls)")
    for identity, sig in [(wid, signals), *[(p["id"], parallel_live._pkg_signals(signals, p))
                                          for p in wg["packages"]]]:
        if sig.get("destructive") or not approvals.check(sig, root, identity)["ok"]:
            return f"parallel approval-preflight: {identity} требует применимый ApprovalRecord"
    return None


def _deliver_parallel(rec, child_root, wid, task, binding):
    """Готовая интеграция -> существующий durable lifecycle/Intent/Receipt controller."""
    from ai_ops_kit.engine import ai_ops_run_lifecycle_stages as stages
    dp, agg = rec.get("delivery_plan") or {}, rec.get("aggregate") or {}
    sha = rec.get("integration_sha")
    rec["delivery"] = {"requested": True, "status": "not-attempted"}
    if not (rec.get("proceed") and dp.get("ready") and agg.get("all_pass")
            and agg.get("tested_revision") == sha and sha):
        return
    work_root = Path(dp["integration_clone"])
    rc, actual, _ = gitio.git(work_root, "rev-parse", "HEAD")
    dirty_rc, dirty, _ = gitio.git(work_root, "status", "--porcelain")
    if rc or actual != sha or dirty_rc or dirty:
        rec["delivery"].update(status="unavailable", reason="integration source изменился/недоступен")
        return
    remote = dp.get("github_remote")
    if not remote or gitio.git(work_root, "remote", "set-url", "origin", remote)[0]:
        rec["delivery"].update(status="unavailable", reason="исходный delivery remote недоступен")
        return
    plan = {"work_root": str(work_root), "work_branch": dp["integration_branch"],
            "committed_sha": sha, "base_ref": binding["base_ref"], "base_sha": binding["base_sha"],
            "base_binding": binding, "wid": wid, "task": task}
    rec.update(workitem_id=wid, ready_for_pr=True, commit={"sha": sha,
               "branch": dp["integration_branch"], "evidence_on_exact_sha": True}, delivery_plan=plan)
    ctx = SimpleNamespace(child_root=child_root, features_dir=child_root / "features")
    jname, handoff_ok, report_ok, saved_plan = stages._commit_barrier(
        rec, work_root, ctx.features_dir, wid, [])
    stages._deliver(ctx, rec, plan=saved_plan, handoff_ok=handoff_ok, report_ok=report_ok,
                    jname=jname, fid=wid)
    # Source остаётся доступен и после Receipt: повтор/reconciliation может читать тот же commit.
    # Вызывающий видит путь в durable report; автоматическая очистка готовой работы запрещена.


def _blocked(rec) -> bool:
    return rec.get("stage") in ("plan", "preflight", "contract-first", "isolation", "lifecycle")


def print_parallel(rec) -> None:
    """Человекочитаемая сводка результата --parallel."""
    if _blocked(rec) and not rec.get("proceed"):
        print(f"PARALLEL ОТКАЗ ({rec.get('stage')}): {rec.get('reason') or rec.get('errors') or '—'}")
        return
    agg = rec.get("aggregate") or {}
    print(f"PARALLEL {rec.get('id') or ''}: proceed={rec.get('proceed')} · "
          f"concurrency={rec.get('execution_concurrency')} · isolation={rec.get('isolation')} · "
          f"integration_sha={(rec.get('integration_sha') or '')[:12] or '—'} · "
          f"conflicts={agg.get('conflicts')} · доставка={(rec.get('delivery') or {}).get('status')} · "
          f"source={(rec.get('integration_source') or {}).get('integration_clone') or '—'}")
    for pid, res in (rec.get("package_results") or {}).items():
        sha = (res.get("sha") or "")[:12] or "—"
        print(f"  [{pid}] {res.get('status')} · sha={sha}")


def exit_code(rec) -> int:
    """0 — зелёный aggregate и доставка открыта; 2 — блок/ошибка; 1 — исполнено, но не готово."""
    if _blocked(rec) and not rec.get("proceed"):
        return 2
    if rec.get("delivery_requested"):
        dv = rec.get("delivery") or {}
        return 0 if (dv.get("status") in ("opened", "updated") and dv.get("sha_verified") is True
                     and dv.get("receipt")) else (2 if _blocked(rec) else 1)
    agg = rec.get("aggregate") or {}
    return 0 if (rec.get("proceed") and agg.get("all_pass")
                 and agg.get("tested_revision") == rec.get("integration_sha")) else 1
