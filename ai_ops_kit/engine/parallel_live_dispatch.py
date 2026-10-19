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

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

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
                      review_fix_attempts=0, budget=None, work_graph=None, task_map=None, admission=None):
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
    if work_graph is not None:
        if admission is None or not isinstance(task_map, dict) or work_graph.get("feature") != wid:
            return {"proceed": False, "stage": "preflight", "parallel": True, "reason": "saved graph requires frozen automatic admission"}
        wg = work_graph
    else:
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
        if admission is None:
            budget.ensure_execution_supported()
        elif budget.max_cost is not None or budget.max_duration is not None:
            raise budget_mod.BudgetExceeded('automatic durable budget supports logical calls only')
    except (ValueError, budget_mod.BudgetExceeded) as exc:
        return {"proceed": False, "stage": "preflight", "parallel": True,
                "reason": f"parallel budget unsupported: {exc}"}
    reason = _policy_refusal(signals, wg, child_root, wid, provider, model, max_steps)
    if reason:
        return {"proceed": False, "stage": "preflight", "parallel": True, "reason": reason}
    if open_pr and admission is not None:
        try:
            _load_package_resume(child_root, wid, admission, wg, task, binding)
        except (ValueError, OSError, RuntimeError, TypeError, KeyError) as exc:
            return {'proceed': False, 'stage': 'preflight', 'parallel': True, 'reason': str(exc)}
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
    from ai_ops_kit.lifecycle import active_work
    claim_path, rec, reused = None, None, {}
    if admission is not None:
        admission = dict(admission, attempt_id=uuid4().hex)
        try:
            import yaml
            active_work.validate_admission(child_root, admission)
            saved_graph = yaml.safe_load((child_root / admission["graph_path"]).read_text())
            if saved_graph != wg or binding["base_sha"] != admission["base_sha"]:
                raise active_work.ActiveWorkCorrupt("automatic saved graph/base changed")
            claim_path = active_work.shared_registry_path(child_root)
            areas = [scope for p in wg["packages"] for scope in p["write_scope"]]
            prior = _load_package_resume(child_root, wid, admission, wg, task, binding)
            if prior is not None:
                from ai_ops_kit.lifecycle import work_claims
                saved, reused, check = prior
                admission = work_claims.retry_package_claim(child_root, wid, admission,
                                                            saved['automatic_attempt'], check)
            elif active_work.register(claim_path, wid, f"ai-ops/{wid}", areas, admission["identity"],
                                      child_root=child_root, admission=admission):
                return {"proceed": False, "stage": "preflight", "parallel": True, "reason": "automatic active claim refused"}
        except (active_work.ActiveWorkCorrupt, KeyError, OSError, ValueError, TypeError, RuntimeError) as exc:
            return {"proceed": False, "stage": "preflight", "parallel": True, "reason": str(exc)}
    package_run = run_fn
    if admission is not None:
        def package_run(*args, **options):
            # После ожидания слота: новая generation/дрейф входов запрещают новый run.
            with active_work.claimed_attempt(child_root, wid, admission):
                active_work.validate_admission(child_root, admission)
            # Сеть/уже допущенный callback не держат canonical lock.
            return run_fn(*args, **options)
    try:
        if admission is not None:
            with active_work.claimed_attempt(child_root, wid, admission):
                pass  # граница допуска; общую блокировку не держим во время пакетов/сети
        if admission is not None:
            from ai_ops_kit.lifecycle import work_claims
            work_claims.bind_attempt_budget(child_root, wid, admission, budget,
                lambda: _retry_guard(child_root, wid, admission))
            if len(reused) != len(task_map):
                budget.ensure_execution_supported()
        rec = dispatch(wg, str(child_root), base_sha, task_map, signals, package_run,
                       repo_slug=repo_slug, contract_shas=contract_shas, integration_branch=f"ai-ops/{wid}",
                       run_options={"provider_name": provider, "model": model, "base": binding["base_ref"],
                                    "max_steps": max_steps, "author": author, "review": review,
                                    "sandbox": sandbox, "baseline_diff": baseline_diff,
                                    "install_deps": install_deps, "require_fix": require_fix,
                                    "review_fix_attempts": review_fix_attempts, "budget": budget, "reused_packages": reused})
        if admission is not None:
            with active_work.claimed_attempt(child_root, wid, admission):
                pass
            try:
                active_work.validate_admission(child_root, admission)
            except active_work.ActiveWorkCorrupt as exc:
                rec.update(proceed=False, stage="preflight", reason=str(exc))
        if isinstance(rec, dict):
            rec["task"] = task
            rec["parallel"] = True
            rec["budget"] = budget.to_dict()
            rec["base_binding"] = binding
            rec["delivery_requested"] = bool(open_pr)
            rec["reconciliation"] = reconciled
            rec["integration_source"] = rec.get("delivery_plan")
            if admission is not None:
                rec["automatic_attempt"] = {"id": admission["attempt_id"], "identity": admission["identity"]}
                rec['package_resume'] = {'reused_packages': sorted(reused),
                    'executed_packages': sorted(set(task_map) - set(reused))}
            if open_pr:
                _deliver_parallel(rec, child_root, wid, task, binding, admission=admission)
            else:
                rec["delivery"] = {"requested": False, "status": "not-requested"}
            from ai_ops_kit.shared import lifecycle_store
            with active_work.claimed_attempt(child_root, wid, admission) if admission is not None else nullcontext():
                saved = lifecycle_store.durable_write_json(child_root / "features" / wid / "parallel-report.json", rec)
            if not saved.get("ok"):
                rec["proceed"] = False
                rec["stage"] = "lifecycle"
                rec["reason"] = "parallel report не сохранён durable; integration source сохранён в результате"
        return rec
    except (active_work.ActiveWorkCorrupt, OSError, ValueError, budget_mod.BudgetExceeded) as exc:
        rec = rec if isinstance(rec, dict) else {}
        rec.update(proceed=False, stage="preflight", parallel=True, reason=str(exc))
        return rec
    finally:
        if claim_path is not None and rec is not None:
            _finish_automatic_claim(child_root, wid, claim_path, admission, rec)


def _finish_automatic_claim(root, wid, path, admission, rec):
    """Поздний finally не завершает новую generation, включая ту же session identity."""
    from ai_ops_kit.lifecycle import active_work
    try:
        refused = active_work.finish_cmd(path, wid, status="done" if exit_code(rec) == 0 else "blocked",
                                         child_root=root, expected_admission=admission)
        reason = "automatic active claim completion refused"
    except (active_work.ActiveWorkCorrupt, OSError) as exc:
        refused, reason = True, str(exc)
    if refused:
        rec.update(proceed=False, stage="preflight", reason=rec.get("reason") or reason)


def _policy_refusal(signals, wg, root, wid, provider, model, max_steps):
    """ДО клонов/моделей: не теряем неподдерживаемую политику и чужие approvals."""
    import re
    from ai_ops_kit.gates import approvals
    from ai_ops_kit.providers import orchestrator
    if not provider:
        return "--parallel требует явно разрешённый provider; скрытого fallback нет"
    try:
        orchestrator.make_provider(provider, model)  # создаёт adapter, НЕ вызывает модель
        if provider in ("claude-cli", "claude-code-local"):
            from ai_ops_kit.providers import orchestrator_providers
            if not orchestrator_providers.claude_binary():
                return "parallel provider unavailable: claude-cli executable missing/non-executable (0 model calls)"
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


def _deliver_parallel(rec, child_root, wid, task, binding, admission=None):
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
    if admission is not None:
        ctx.delivery_guard = lambda: _retry_guard(child_root, wid, admission)
    with ctx.delivery_guard() if admission is not None else nullcontext():
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
        return 0 if (dv.get("status") in ("opened", "updated", "reconciled") and dv.get("sha_verified") is True
                     and dv.get("receipt")) else (2 if _blocked(rec) else 1)
    agg = rec.get("aggregate") or {}
    return 0 if (rec.get("proceed") and agg.get("all_pass")
                 and agg.get("tested_revision") == rec.get("integration_sha")) else 1


def _safe_retry_path(root, path):
    path = Path(path)
    if (not path.is_absolute() or not path.resolve().is_relative_to(root)
            or any(p.is_symlink() for p in (path, *path.parents) if p.is_relative_to(root))):
        raise ValueError('parallel delivery unsafe artifact/source path')
    return path


def _retry_source(root, wid, rec, base):
    from ai_ops_kit.lifecycle import work_claims
    from ai_ops_kit.gates import concurrency_preflight
    binding, dp, agg = rec.get('base_binding') or {}, rec.get('integration_source') or {}, rec.get('aggregate') or {}
    if not all(isinstance(item, dict) for item in (binding, dp, agg, rec.get('package_artifacts'))):
        raise ValueError('parallel delivery malformed saved evidence')
    sha = parallel_live._artifact_sha(rec.get('integration_sha'))
    if not (rec.get('parallel') is True and rec.get('proceed') is True and sha
            and dp.get('ready') is True and dp.get('integration_sha') == sha
            and agg.get('all_pass') is True and agg.get('tested_revision') == sha
            and agg.get('postcheck_revision') == sha and agg.get('revision_ok') is True
            and agg.get('tree_clean') is True and rec.get('package_artifacts', {}).get('status') == 'preserved'
            and dp.get('integration_branch') == f'ai-ops/{wid}' and dp.get('base_sha') == binding.get('base_sha')):
        raise ValueError('parallel delivery requires preserved exact-tested ready integration')
    current = gitio.resolve_base(root, base or binding.get('base_ref'))
    if not (current.get('resolved') and current['base_sha'] == binding.get('base_sha')
            and current['base_ref'] == binding.get('base_ref')):
        raise ValueError('parallel delivery stale base binding')
    owned = work_claims._git_common_dir(root) / 'ai-ops-parallel'
    source = _safe_retry_path(owned, dp.get('integration_clone', ''))
    if source.name != '_integration' or source.parent.parent != owned or not source.parent.name.startswith('run-'):
        raise ValueError('parallel delivery source is not an owned run clone')
    if (not (source / '.git').is_dir() or (source / '.git').is_symlink()
            or gitio.git(source, 'rev-parse', '--show-toplevel')[1] != str(source)
            or gitio.git(source, 'rev-parse', 'HEAD')[1] != sha
            or gitio.git(source, 'symbolic-ref', '--short', 'HEAD')[1] != dp['integration_branch']
            or gitio.git(source, 'status', '--porcelain')[:2] != (0, '')
            or gitio.git(source, 'merge-base', '--is-ancestor', binding['base_sha'], sha)[0]):
        raise ValueError('parallel delivery source changed/missing/dirty')
    remote = parallel_live._github_remote(root)
    repo = concurrency_preflight._parse_owner_repo(remote or '')
    if not repo or dp.get('github_remote') != remote:
        raise ValueError('parallel delivery remote changed/unavailable')
    from ai_ops_kit.engine.run_exec_context import product_task_for_resume
    task = rec.get('task') or product_task_for_resume(root, wid).get('task')
    if not isinstance(task, str) or not task.strip():
        raise ValueError('parallel delivery original task missing')
    return binding, dp, task, '/'.join(repo)


def _retry_outbox(root, wid):
    from ai_ops_kit.shared import lifecycle_store
    outbox = _safe_retry_path(root, root / 'features' / wid / 'delivery-outbox')
    for suffix, kind in (('intent', 'DeliveryIntent'), ('receipt', 'DeliveryReceipt')):
        for path in sorted(outbox.glob(f'*.{suffix}.yaml')):
            _safe_retry_path(root, path)
            loaded = lifecycle_store.load_guarded(path, kind=kind,
                required_keys=('delivery_id', 'workitem_id', 'repository', 'branch', 'commit_sha', 'base_ref', 'status'))
            if (loaded['state'] != 'ok' or loaded['data']['workitem_id'] != wid
                    or loaded['data'].get('schema_version') != 1
                    or loaded['data'].get('branch') != f'ai-ops/{wid}'
                    or not parallel_live._artifact_sha(loaded['data'].get('commit_sha'))
                    or path.name != f"{loaded['data']['delivery_id']}.{suffix}.yaml"):
                raise ValueError('parallel delivery corrupt outbox artifact')
    return outbox


def _retry_guard(root, wid, admission):
    from contextlib import contextmanager
    from ai_ops_kit.lifecycle import active_work
    @contextmanager
    def guard():
        with active_work.claimed_attempt(root, wid, admission):
            active_work.validate_admission(root, admission)
            yield
    return guard()


def _reuse_retry_receipt(root, wid, rec, repo, reconciled):
    import hashlib
    from ai_ops_kit.shared import lifecycle_store
    from ai_ops_kit.delivery import pr_open
    binding, sha = rec['base_binding'], rec['integration_sha']
    branch = f'ai-ops/{wid}'
    did = hashlib.sha256(f'{repo}:{wid}:{branch}:{sha}'.encode()).hexdigest()[:16]
    path = _retry_outbox(root, wid) / f'{did}.receipt.yaml'
    loaded = lifecycle_store.load_guarded(path, kind='DeliveryReceipt')
    if loaded['state'] == 'absent':
        return False
    if loaded['state'] != 'ok':
        raise ValueError('parallel delivery corrupt receipt')
    receipt = loaded['data']
    expected = dict(delivery_id=did, workitem_id=wid, repository=repo, branch=branch,
                    commit_sha=sha, base_ref=binding['base_ref'])
    if any(receipt.get(k) != v for k, v in expected.items()):
        raise ValueError('parallel delivery receipt identity mismatch')
    if receipt.get('sha_verified') is not True:
        if not any(r['delivery_id'] == did and r['status'] == 'reconciled-absent' for r in reconciled or []):
            raise ValueError('parallel delivery receipt remains unconfirmed')
        return False
    if receipt.get('remote_sha') != sha:
        raise ValueError('parallel delivery receipt SHA mismatch')
    if not any(r['delivery_id'] == did and r['status'] == 'reconciled' for r in reconciled or []):
        remote = pr_open.reconcile_delivery(root, branch)
        if (remote.get('status') != 'found' or remote.get('repository') != repo
                or remote.get('head_sha') != sha or remote.get('base_ref') != binding['base_ref']):
            raise ValueError('parallel delivery previous receipt not confirmed by current remote')
    rec['delivery'] = {'requested': True, 'status': 'reconciled', 'sha_verified': True,
        'remote_sha': sha, 'delivery_id': did, 'receipt': str(path.relative_to(root)),
        'reused_receipt': True, 'pr': {'url': receipt.get('pr_url'), 'number': receipt.get('pr_number')}}
    return True


def resume_parallel_delivery(child_root, wid, *, session, base=None, execute=False, open_pr=False,
                             task=None, replan=False, takeover=False):
    """Existing deliver-only CLI; automatic terminal own integration only, no provider selection."""
    import hashlib
    from ai_ops_kit.shared import lifecycle_store
    from ai_ops_kit.lifecycle import active_work, work_claims
    root = Path(child_root).resolve()
    rec = {'parallel': True, 'proceed': False, 'stage': 'preflight',
           'resume': {'requested': True, 'can_resume': False, 'resumed': False, 'deliver_only': True}}
    admission = None
    try:
        if not isinstance(wid, str) or wid in ('', '.', '..') or '/' in wid or '\\' in wid:
            raise ValueError('parallel delivery invalid work item')
        report = _safe_retry_path(root, root / 'features' / wid / 'parallel-report.json')
        if not report.exists():
            return None
        if replan or takeover or (execute and not open_pr):
            raise ValueError('parallel delivery requires --open-pr; replan/takeover unsupported')
        raw = report.read_bytes()
        loaded = lifecycle_store.load_guarded(report)
        if loaded['state'] != 'ok':
            raise ValueError('parallel delivery corrupt saved report')
        saved = loaded['data']
        binding, dp, original_task, repo = _retry_source(root, wid, saved, base)
        if task and task != original_task:
            raise ValueError('parallel delivery cannot replace original task')
        origin = saved.get('automatic_attempt') or {}
        if not isinstance(origin, dict) or not isinstance(origin.get('id'), str) or origin.get('identity') != session:
            raise ValueError('parallel delivery identity does not own original attempt')
        def check():
            if hashlib.sha256(report.read_bytes()).digest() != hashlib.sha256(raw).digest():
                raise ValueError('parallel delivery saved report changed during admission')
            _retry_source(root, wid, saved, base)
            _retry_outbox(root, wid)
        admitted = work_claims.retry_delivery_claim(root, wid, session, origin.get('id'),
                                                   saved['integration_sha'], check, execute=execute)
        rec = dict(saved, delivery_plan=dp, delivery_requested=bool(execute),
            resume={'requested': True, 'can_resume': True, 'resumed': bool(execute), 'deliver_only': True})
        if not execute:
            return rec
        admission = admitted
        rec['delivery_retry'] = {'attempt_id': admission['attempt_id'], 'origin_attempt_id': origin['id'],
                                 'new_package_calls': 0, 'new_model_calls': 0}
        with _retry_guard(root, wid, admission):
            if not lifecycle_store.durable_write_json(report, rec).get('ok'):
                raise ValueError('parallel delivery retry checkpoint not durable')
        from ai_ops_kit.engine.ai_ops_run import _reconcile_pending_delivery
        rec['reconciliation'] = _reconcile_pending_delivery(root / 'features', wid, root,
            delivery_guard=lambda: _retry_guard(root, wid, admission))
        if any(r['status'] not in ('reconciled', 'reconciled-absent') for r in rec['reconciliation'] or []):
            raise ValueError('parallel delivery unresolved external outcome')
        if not _reuse_retry_receipt(root, wid, rec, repo, rec['reconciliation']):
            _deliver_parallel(rec, root, wid, original_task, binding, admission=admission)
        with _retry_guard(root, wid, admission):
            if not lifecycle_store.durable_write_json(report, rec).get('ok'):
                raise ValueError('parallel delivery final report not durable; source retained')
        return rec
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, active_work.ActiveWorkCorrupt) as exc:
        rec.update(proceed=False, stage='preflight', reason=str(exc))
        rec['resume'].update(can_resume=False, resumed=False)
        return rec
    finally:
        if admission is not None:
            _finish_automatic_claim(root, wid, active_work.shared_registry_path(root), admission, rec)


def _load_package_resume(root, wid, admission, wg, task, binding):
    """Saved automatic independent roots only; unknown outcomes never become pass or fresh callbacks."""
    import hashlib
    import json
    from ai_ops_kit.shared import lifecycle_store
    root = root.resolve()
    report = _safe_retry_path(root, root / 'features' / wid / 'parallel-report.json')
    if not report.exists():
        return None
    raw = report.read_bytes()
    loaded = lifecycle_store.load_guarded(report)
    if loaded['state'] != 'ok':
        raise ValueError('package resume corrupt report')
    saved = loaded['data']
    origin, artifacts = saved.get('automatic_attempt'), saved.get('package_artifacts')
    results = saved.get('package_results')
    ids = {p['id'] for p in wg['packages']}
    if (saved.get('parallel') is not True or saved.get('proceed') is not False
            or saved.get('stage') not in ('pre-fan-in', 'fan-in') or saved.get('task') != task
            or saved.get('base_binding') != binding or not isinstance(origin, dict) or not origin.get('id')
            or not isinstance(results, dict) or set(results) != ids
            or not isinstance(artifacts, dict) or artifacts.get('status') != 'preserved'
            or any(p.get('depends_on') for p in wg['packages'])):
        raise ValueError('package resume requires terminal preserved automatic results; ready work uses deliver-only')
    # Any previous external transaction is handled by existing delivery reconciliation first.
    if any(_retry_outbox(root, wid).glob('*')):
        raise ValueError('package resume has delivery outbox; reconcile external outcome before package retry')
    receipt = _safe_retry_path(root, Path(artifacts.get('receipt', '')))
    directory = root / '.ai/usage/parallel'
    if receipt.name != 'package-receipt.json' or receipt.parent.parent != directory:
        raise ValueError('package resume receipt outside canonical store')
    receipt_raw = receipt.read_bytes()
    data = json.loads(receipt_raw)
    run_id = receipt.parent.name
    if (not isinstance(data, dict) or len(run_id) != 64 or any(c not in '0123456789abcdef' for c in run_id)
            or data.get('kind') != 'ParallelPackageReceipt' or data.get('run_id') != run_id
            or data.get('base_sha') != admission['base_sha'] or not isinstance(data.get('packages'), list)):
        raise ValueError('package resume receipt identity mismatch')
    entries = {p.get('package_id'): p for p in data['packages'] if isinstance(p, dict)}
    if set(entries) != ids or len(data['packages']) != len(ids):
        raise ValueError('package resume incomplete/duplicate package receipt')
    reused = {}
    for pkg in wg['packages']:
        pid, result, item = pkg['id'], results[pkg['id']], entries[pkg['id']]
        if not isinstance(result, dict) or result.get('status') not in ('pass', 'fail'):
            raise ValueError('package resume unknown package outcome; no blind retry')
        sha = parallel_live._artifact_sha(result.get('sha'))
        if result.get('sha') is not None and sha is None:
            raise ValueError('package resume invalid reported commit')
        if not isinstance(result.get('gate_report'), dict) or not isinstance(item.get('gate_report'), dict):
            raise ValueError('package resume malformed package gates')
        if (item.get('status') != result['status'] or item.get('base_sha') != admission['base_sha']
                or item.get('reported_package_sha') != sha or item.get('package_sha') != sha):
            raise ValueError('package resume result/receipt mismatch')
        if sha:
            ref = f"refs/ai-ops/parallel/{run_id}/{hashlib.sha256(pid.encode()).hexdigest()}"
            parallel_live._require_direct_checkpoint_ref(root, ref)
            if (item.get('retained_ref') != ref or gitio.git(root, 'rev-parse', '--verify', ref)[1] != sha
                    or gitio.git(root, 'cat-file', '-e', f'{sha}^{{tree}}')[0]
                    or gitio.git(root, 'merge-base', '--is-ancestor', admission['base_sha'], sha)[0]):
                raise ValueError('package resume retained commit missing/changed/unrelated')
            rc, changed, _ = gitio.git(root, 'diff', '--name-only', admission['base_sha'], sha)
            if rc or not parallel_live._scope_ok(changed.splitlines(), pkg['write_scope'])[0]:
                raise ValueError('package resume retained commit scope mismatch')
        if result['status'] == 'pass':
            expected = {'all_pass': True, 'tested_revision': sha}
            gate = result.get('gate_report')
            if not sha or not isinstance(gate, dict) or any(gate.get(k) != v for k, v in expected.items()) or item.get('gate_report') != expected:
                raise ValueError('package resume pass lacks exact-tested commit')
            reused[pid] = {'result': result, 'ref': item['retained_ref'], 'receipt': str(receipt)}
        elif (result.get('gate_report') or {}).get('all_pass') is not False or item.get('gate_report', {}).get('all_pass') is not False:
            raise ValueError('package resume failed outcome is ambiguous')
    def check():
        if report.read_bytes() != raw or receipt.read_bytes() != receipt_raw:
            raise ValueError('package resume evidence changed during admission')
        # Repeat ref/object/scope admission under the canonical claim lock before replacing owner.
        if _load_package_resume(root, wid, admission, wg, task, binding)[1] != reused:
            raise ValueError('package resume retained evidence changed')
    return saved, reused, check
