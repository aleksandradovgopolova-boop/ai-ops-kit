#!/usr/bin/env python3
"""Sequential WorkPackage Executor (v3.1) — исполнить план по пакетам, а не одним блобом.

Аудит: Atomic Planner создаёт КОНКРЕТНЫЕ WorkPackages (v2.111), но их никто не ИСПОЛНЯЛ — задача
всё равно шла одним общим tool loop. Здесь — последовательный исполнитель:

  Пакет 1 -> commit -> evidence -> gates -> handoff -> Пакет 2 -> ... -> итог

Инварианты:
  * пакеты идут в порядке order; зависимый пакет НЕ стартует, пока все его depends_on не подтверждены;
  * каждый пакет — свой прогон движка на общей ветке ai-ops/<wid> (resume поверх предыдущего): свой
    коммит/SHA, своё evidence, свои гейты, свой RunHandoff -> своя точка resume;
  * блок пакета (preflight/гейты/нет коммита) ОСТАНАВЛИВАЕТ последовательность — следующие не стартуют
    (честно: не притворяемся, что доделали);
  * исполнение последовательное (не параллельное): состояние передаётся через RunHandoff.

Использование (программно):
  execute_sequence(task, signals, child_root, packages, proposer_for, feature=wid, ...) -> отчёт.
CLI: workpackage_executor.py --selftest
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG / "tools"))


def _git(root, *a):
    r = subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def _changed_files(root, sha):
    """Файлы, изменённые коммитом sha относительно его родителя (для пост-дифф проверки write_scope)."""
    rc, out, _ = _git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", sha)
    return [ln for ln in out.splitlines() if ln] if rc == 0 else []


def _ordered(packages):
    return sorted(packages, key=lambda p: (p.get("order", 0), p.get("id", "")))


def _hard_stop(rep):
    """v2.120 (P0.3): причина ОСТАНОВИТЬ цепочку (нельзя строить зависимый пакет поверх), либо None.

    Стоп — на настоящем блокере: нет коммита, preflight-блок, регрессия базы, security FAIL,
    отрицательный вердикт ревьюера, нарушение package scope (попытка выйти за write-scope). НЕ стоп —
    «awaiting evidence» (нет author/review -> пакет исполнен, но не ready): его можно оставить как
    незавершённую работу, цепочка продолжается."""
    if rep.get("status") == "blocked":
        return "preflight-blocked"
    if not (rep.get("commit") or {}).get("sha"):
        return "no-commit"
    if (rep.get("baseline") or {}).get("regressions"):
        return "regression"
    if (rep.get("security_scan") or {}).get("overall") == "fail":
        return "security-fail"
    if any((rv or {}).get("status") == "fail" for rv in (rep.get("reviews") or [])):
        return "reviewer-fail"
    # нарушение package scope: модель пыталась ПИСАТЬ вне write_scope пакета -> брокер отклонил.
    # Матчим именно scope-отказ (не любой denied — напр. блокировка git push НЕ является scope-violation).
    for reason in ((rep.get("loop") or {}).get("denied_reasons") or []):
        if "вне write_scope" in (reason or ""):
            return "scope-violation"
    return None


def execute_sequence(task, signals, child_root, packages, proposer_for, feature,
                     features_dir=None, base="main", provider_name="mock", model=None,
                     author=False, author_proposer=None, review=False, reviewer_proposer=None,
                     baseline_diff=True, install_deps=False, signals_for=None,
                     sandbox=False, open_pr=False, max_steps=40, write_scope_for=None, resume_from=None):
    """Исполнить список WorkPackages последовательно. proposer_for(pkg)->proposer; signals_for(pkg)->
    доп. сигналы пакета (опц.); write_scope_for(pkg)->список путей write-scope пакета (опц.).
    v2.120: НАСЛЕДУЕТ sandbox/install_deps/max_steps/провайдера обычного пути (containment не теряется);
    open_pr применяется к финальному пакету (интегрированная ветка). -> {kind, workitem_id, packages,
    completed, stopped_at, executed_all, ready_all, final_sha, sequential_chain}."""
    import ai_ops_run
    child_root = Path(child_root)
    features_dir = Path(features_dir) if features_dir else child_root / "features"
    wid = feature
    ordered = _ordered(packages)
    results, completed, stopped_at, final_sha = [], set(), None, None
    prev_sha = None
    chain_ok = True

    # v2.124: IMMUTABLE parent SequencePlan — фиксируем порядок/зависимости пакетов ОДИН раз в начале.
    # Родительский план не должен перетираться локальным планом последнего пакета (P1 аудита).
    try:
        pdir = features_dir / wid
        pdir.mkdir(parents=True, exist_ok=True)
        _sp = pdir / "sequence-plan.yaml"
        if not _sp.exists():
            import yaml as _y
            _sp.write_text(_y.safe_dump(
                {"schema_version": 1, "kind": "SequencePlan", "workitem_id": wid, "total": len(ordered),
                 "packages": [{"id": p.get("id"), "order": p.get("order"),
                               "depends_on": p.get("depends_on") or [], "scope": p.get("scope"),
                               "write_scope": p.get("write_scope")} for p in ordered]},
                allow_unicode=True, sort_keys=False), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    # v2.124: снимок проверок БАЗЫ (до пакета 1) для АГРЕГАТНОЙ baseline-diff на финальном SHA.
    base_checks = None
    try:
        import project_detector as _pd, evidence_collector as _ec, tool_broker as _tb
        _bpol = (_tb.sandbox_policy(child_root=str(child_root)) if sandbox
                 else _tb.Policy(level="execution", child_root=str(child_root), block_push=True))
        base_checks = _ec.collect(_pd.detect(child_root), child_root, _bpol)["checks"]
    except Exception:  # noqa: BLE001 — недоступность инфры не должна ронять последовательность
        base_checks = None

    # v2.124: resume с КОНКРЕТНОГО пакета — пакеты до него считаются исполненными в прошлом прогоне
    # (их SHA/готовность восстанавливаются из снимков work-packages/<pid>/report.json).
    start_index = 0
    if resume_from:
        _ids = [p.get("id") for p in ordered]
        if resume_from in _ids:
            start_index = _ids.index(resume_from)

    for i, pkg in enumerate(ordered):
        pid = pkg.get("id", f"pkg-{i+1}")
        if i < start_index:
            prior = features_dir / wid / "work-packages" / pid / "report.json"
            prior_rep = {}
            if prior.is_file():
                try:
                    prior_rep = json.loads(prior.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    prior_rep = {}
            psha = (prior_rep.get("commit") or {}).get("sha")
            completed.add(pid)
            if psha:
                prev_sha = final_sha = psha
            results.append({"id": pid, "sha": psha, "ready": bool(prior_rep.get("ready_for_pr")),
                            "executed": bool(psha), "status": "resumed-skip", "resume_point": psha})
            continue
        unmet_deps = [d for d in (pkg.get("depends_on") or []) if d not in completed]
        if unmet_deps:
            results.append({"id": pid, "status": "blocked-dependency",
                            "unmet_deps": unmet_deps, "sha": None, "ready": False})
            stopped_at = pid
            break

        sig_pkg = dict(signals or {})
        sig_pkg["affected_areas"] = pkg.get("scope") or sig_pkg.get("affected_areas") or ["core"]
        sig_pkg["size"] = "small"
        # исполнитель = подтверждение декомпозиции: пакет атомарен, его id выбран, и передан
        # АВТОРИТЕТНЫЙ список id плана (preflight валидирует work_package_id против него — P0.4/P0.5).
        sig_pkg["work_package_id"] = pid
        sig_pkg["_sequence_plan_ids"] = [p.get("id") for p in ordered]
        if signals_for:
            sig_pkg.update(signals_for(pkg) or {})

        is_last = (i == len(ordered) - 1)
        pkg_task = f"{task} — пакет {pid}: {pkg.get('title', '')}".strip()
        rep = ai_ops_run.run(pkg_task, sig_pkg, child_root, features_dir=str(features_dir),
                             engine="pipeline", proposer=proposer_for(pkg), execute=True,
                             feature=wid, resume=(i > 0 or start_index > 0), base=base, provider_name=provider_name,
                             model=model, author=author, author_proposer=author_proposer,
                             review=review, reviewer_proposer=reviewer_proposer,
                             baseline_diff=baseline_diff, install_deps=install_deps,
                             # v2.124 (P0.4): пакеты НИКОГДА не открывают PR — доставка отдельным шагом
                             # ПОСЛЕ агрегатного вердикта (ready_all). Иначе готовый финальный пакет открыл
                             # бы PR, пока ранний пакет awaiting-evidence -> PR при ready_all=false.
                             sandbox=sandbox, max_steps=max_steps, open_pr=False,
                             write_scope=(write_scope_for(pkg) if write_scope_for else None))

        sha = (rep.get("commit") or {}).get("sha")
        # v2.120 (P0.3): ОСТАНОВ цепочки на НАСТОЯЩЕМ блокере — нельзя строить зависимый пакет поверх.
        # Отличаем «awaiting evidence» (нет author/review -> исполнен, но не ready, цепочка идёт) от
        # deterministic/security/reviewer FAIL и регрессии (обязаны остановить).
        stop_reason = _hard_stop(rep)
        # v2.123 (P0.3): ПОСТ-ДИФФ проверка write_scope — пакет не должен был изменить НИЧЕГО вне своего
        # каталога (belt-and-suspenders поверх брокера, который отклоняет out-of-scope записи в петле).
        # Escape = scope-violation -> останавливает последовательность (нельзя строить поверх «уехавшего»).
        pkg_scope = write_scope_for(pkg) if write_scope_for else None
        if stop_reason is None and sha and pkg_scope:
            import approvals as _appr
            wt = child_root / ".ai" / "worktrees" / wid
            changed = _changed_files(wt if wt.is_dir() else child_root, sha)
            outside = [f for f in changed
                       if not _appr.covers_paths({"scope": " ".join(pkg_scope)}, [f])]
            if outside:
                stop_reason = f"scope-violation: пакет изменил пути вне write_scope: {', '.join(outside[:5])}"
        hard_blocked = rep.get("status") == "blocked"
        executed = bool(sha) and stop_reason is None
        ready = bool(rep.get("ready_for_pr"))
        blocked = stop_reason is not None

        # сохранить per-package отчёт + СНИМОК lifecycle-артефактов (v2.124): родительские
        # features/<wid>/{run-plan,run-handoff,...} перетираются следующим пакетом -> у каждого пакета
        # свой неизменный lifecycle-каталог work-packages/<pid>/ (P1 аудита).
        pkg_dir = features_dir / wid / "work-packages" / pid
        try:
            pkg_dir.mkdir(parents=True, exist_ok=True)
            (pkg_dir / "report.json").write_text(
                json.dumps(rep, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            for _art in ("run-plan.yaml", "run-handoff.yaml", "context-bundle.yaml", "spec-coverage.yaml"):
                _src = features_dir / wid / _art
                if _src.is_file():
                    (pkg_dir / _art).write_text(_src.read_text(encoding="utf-8"), encoding="utf-8")
        except OSError:
            pass

        # последовательность: коммит пакета — потомок коммита предыдущего (строим поверх, не параллельно)
        if executed and prev_sha and sha:
            wt = child_root / ".ai" / "worktrees" / wid
            rc, _, _ = _git(wt if wt.is_dir() else child_root, "merge-base", "--is-ancestor", prev_sha, sha)
            if rc != 0:
                chain_ok = False

        status = (stop_reason if stop_reason else ("executed" if executed else "no-commit"))
        results.append({"id": pid, "sha": sha, "ready": ready, "executed": executed,
                        "blocked": blocked, "stop_reason": stop_reason,
                        "gates_unmet": (rep.get("gates") or {}).get("unmet"),
                        "resume_point": sha,   # точка resume пакета
                        "handoff": (rep.get("handoff") or {}).get("next_action"),
                        "status": status})

        if executed:
            completed.add(pid)
            prev_sha = sha
            final_sha = sha
        if not executed or blocked:
            stopped_at = pid
            break

    executed_all = len(completed) == len(ordered) and stopped_at is None
    ready_all = executed_all and all(r.get("ready") for r in results)

    # v2.124: AGGREGATE verification на ФИНАЛЬНОМ интегрированном SHA — перепроверяем результат ЦЕЛИКОМ
    # (не только конъюнкцию per-package вердиктов), чтобы поймать межпакетные взаимодействия (каждый
    # пакет зелен по отдельности, но интеграция сломана). Сравниваем финальные проверки с БАЗОЙ (до п.1).
    aggregate = {"verified": False}
    if executed_all and final_sha:
        try:
            import project_detector as _pd2, evidence_collector as _ec2, tool_broker as _tb2
            import execution_pipeline as _ep
            wt = child_root / ".ai" / "worktrees" / wid
            vroot = wt if wt.is_dir() else child_root
            _vpol = (_tb2.sandbox_policy(child_root=str(vroot)) if sandbox
                     else _tb2.Policy(level="execution", child_root=str(vroot), block_push=True))
            final_checks = _ec2.collect(_pd2.detect(vroot), vroot, _vpol)["checks"]
            agg_reg, _agg_fix = _ep._diff_checks(base_checks, final_checks) if base_checks else ([], [])
            aggregate = {"verified": True, "regressions": agg_reg, "no_regressions": not agg_reg,
                         "final_sha": final_sha,
                         "checks": {k: (v or {}).get("status") for k, v in (final_checks or {}).items()}}
        except Exception as e:  # noqa: BLE001
            aggregate = {"verified": False, "error": str(e)}
    # verified regression блокирует; недоступность инфры (verified=False) не над-блокирует
    # (инкрементальная per-package baseline-diff уже проверила цепочку).
    agg_ok = (not aggregate.get("verified")) or aggregate.get("no_regressions", True)
    # v2.124: агрегатный вердикт — вся последовательность готова, цепочка целостна И финальный SHA чист.
    aggregate_ready = ready_all and chain_ok and agg_ok

    # v2.124 (P0.4): доставка draft PR — ОТДЕЛЬНЫЙ шаг ПОСЛЕ агрегатного вердикта, на финальном
    # интегрированном SHA. PR открывается ТОЛЬКО при aggregate_ready — не по готовности отдельного пакета.
    pr, delivery = None, {"requested": bool(open_pr), "status": "not-requested" if not open_pr else None}
    if open_pr:
        if aggregate_ready and final_sha:
            try:
                import pr_open
                wt = child_root / ".ai" / "worktrees" / wid
                pr = pr_open.open_draft_pr(wt if wt.is_dir() else child_root, f"ai-ops/{wid}",
                                           title=f"ai-ops: {task[:60]}",
                                           body=(f"Sequential WorkPackages: {len(ordered)} пакет(ов). "
                                                 f"Финальный SHA {final_sha}. Агрегатный вердикт: ready_all."))
                delivery["status"] = (pr or {}).get("status") or "failed"
            except Exception as e:  # noqa: BLE001
                delivery["status"] = "failed"
                delivery["error"] = str(e)
        else:
            delivery["status"] = "not-attempted"   # последовательность не готова -> PR НЕ открываем

    seq = {"schema_version": 1, "kind": "WorkPackageSequence", "workitem_id": wid,
           "packages": results, "completed": sorted(completed), "stopped_at": stopped_at,
           "executed_all": executed_all, "ready_all": ready_all, "aggregate_ready": aggregate_ready,
           "final_sha": final_sha, "sequential_chain": chain_ok, "total": len(ordered),
           "aggregate": aggregate, "delivery": delivery, "draft_pr": pr,
           "resumed_from": resume_from}
    try:
        (features_dir / wid / "sequence-report.yaml").parent.mkdir(parents=True, exist_ok=True)
        import yaml
        (features_dir / wid / "sequence-report.yaml").write_text(
            yaml.safe_dump(seq, allow_unicode=True, sort_keys=False), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return seq


def selftest():
    import tempfile
    import io
    import contextlib
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    import atomic_planner

    def mkrepo(td):
        (Path(td) / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        for a in (("init", "-q"), ("config", "user.email", "t@t"), ("config", "user.name", "t"),
                  ("add", "-A"), ("commit", "-q", "-m", "i")):
            _git(td, *a)
        return _git(td, "rev-parse", "--abbrev-ref", "HEAD")[1]

    def author(prompt):
        if "requirements-artifact" in prompt:
            return ("schema_version: 1\nkind: requirements-artifact\nrequirements:\n"
                    "  - id: R1\n    statement: пакет реализован\n    acceptance:\n      - when готово then тест зелёный\n")
        if "spec-change" in prompt:
            return ("schema_version: 1\nkind: spec-change\ncapability: mod\nwhy: нужно\n"
                    "what_changes:\n  - изменение\ntasks:\n  - шаг\nrequirements:\n"
                    "  - name: R\n    text: The system SHALL work.\n    scenarios:\n"
                    "      - {name: T, when: x, then: y}\n")
        return ("schema_version: 1\nkind: plan-artifact\nwork_packages:\n"
                "  - id: WP1\n    summary: пакет\n    depends_on: []\nwrite_scope:\n  - .\n")
    reviewer = lambda p: '{"kind":"reviewer-result","status":"pass","checks":[{"id":"ok","status":"pass"}]}'

    # ENGINEERING по 3 подсистемам -> 3 пакета с цепочкой зависимостей
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        cur = mkrepo(td)
        sig = {"task_type": "ENGINEERING", "size": "large", "risk": "low",
               "affected_areas": ["catalog", "orders", "billing"]}
        wp = atomic_planner.decompose(sig, wid="seq", child_root=root)
        pkgs = wp["work_packages"]
        expect("executor: план дал 3 пакета by-subsystem с deps",
               len(pkgs) == 3 and pkgs[1]["depends_on"] == [pkgs[0]["id"]])

        # per-package proposer: каждый пакет пишет свой файл
        def prop_for(pkg):
            fname = f"src/{pkg['id']}.py"
            it = iter([{"op": "write", "path": fname, "content": f"# {pkg['id']}\nx=1\n"},
                       {"done": True}])
            return lambda c: next(it)

        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            seq = execute_sequence("большой рефактор", sig, root, pkgs, prop_for, feature="seq",
                                   base=cur, author=True, author_proposer=author,
                                   review=True, reviewer_proposer=reviewer)
        shas = [p.get("sha") for p in seq["packages"]]
        expect("executor: все 3 пакета исполнены (executed_all)", seq["executed_all"] is True)
        expect("executor: у каждого пакета свой уникальный SHA (свой коммит)",
               all(shas) and len(set(shas)) == 3)
        expect("executor: последовательная цепочка (пакет N поверх N-1)", seq["sequential_chain"] is True)
        expect("executor: per-package отчёты на диске",
               all((root / "features" / "seq" / "work-packages" / p["id"] / "report.json").is_file()
                   for p in seq["packages"]))
        expect("executor: sequence-report сохранён", (root / "features" / "seq" / "sequence-report.yaml").is_file())
        # каждый пакет имеет точку resume (SHA) и запись handoff
        expect("executor: у каждого пакета точка resume (SHA)",
               all(p.get("resume_point") for p in seq["packages"]))
        # v2.124: immutable parent SequencePlan + per-package lifecycle-снимок + агрегатный вердикт
        expect("v2.124: immutable sequence-plan.yaml записан",
               (root / "features" / "seq" / "sequence-plan.yaml").is_file())
        expect("v2.124: у каждого пакета снимок lifecycle (run-plan.yaml в своём каталоге)",
               all((root / "features" / "seq" / "work-packages" / p["id"] / "run-plan.yaml").is_file()
                   for p in seq["packages"]))
        expect("v2.124: агрегатный вердикт (aggregate_ready) в отчёте", "aggregate_ready" in seq)
        expect("v2.124: aggregate verify на финальном SHA выполнен (verified)",
               (seq.get("aggregate") or {}).get("verified") is True
               and (seq.get("aggregate") or {}).get("final_sha") == seq["final_sha"])

        # v2.124: RESUME с конкретного пакета — пакеты до него восстановлены из снимков (resumed-skip),
        # исполняется только целевой и последующие.
        buf2 = io.StringIO()
        with contextlib.redirect_stderr(buf2):
            seq_r = execute_sequence("большой рефактор", sig, root, pkgs, prop_for, feature="seq",
                                     base=cur, author=True, author_proposer=author,
                                     review=True, reviewer_proposer=reviewer,
                                     resume_from=pkgs[1]["id"])
        skipped = [p for p in seq_r["packages"] if p.get("status") == "resumed-skip"]
        expect("v2.124 resume: пакеты до resume_from помечены resumed-skip (восстановлены из снимков)",
               seq_r.get("resumed_from") == pkgs[1]["id"] and len(skipped) == 1
               and skipped[0]["id"] == pkgs[0]["id"] and skipped[0].get("sha"))
        # с author+review+openspec — пакеты доходят до ready (если openspec доступен)
        import shutil
        if shutil.which("openspec"):
            expect("executor: с author+review+openspec — вся последовательность ready", seq["ready_all"] is True)

        # v2.120 (P0.3): _hard_stop различает настоящий блокер и «awaiting evidence»
        expect("v2.120 _hard_stop: нет коммита -> stop",
               _hard_stop({"commit": {"sha": None}}) == "no-commit")
        expect("v2.120 _hard_stop: регрессия -> stop",
               _hard_stop({"commit": {"sha": "a"}, "baseline": {"regressions": ["test"]}}) == "regression")
        expect("v2.120 _hard_stop: security fail -> stop",
               _hard_stop({"commit": {"sha": "a"}, "security_scan": {"overall": "fail"}}) == "security-fail")
        expect("v2.120 _hard_stop: reviewer fail -> stop",
               _hard_stop({"commit": {"sha": "a"}, "reviews": [{"gate": "code_review", "status": "fail"}]}) == "reviewer-fail")
        expect("v2.120 _hard_stop: scope-violation (write вне scope) -> stop",
               _hard_stop({"commit": {"sha": "a"}, "loop": {"denied_reasons": ["'x' вне write_scope ['src']"]}}) == "scope-violation")
        expect("v2.120 _hard_stop: awaiting evidence (гейты unmet, но коммит есть, без fail) -> НЕ стоп",
               _hard_stop({"commit": {"sha": "a"}, "gates": {"blocked": True, "unmet": ["requirements"]}}) is None)
        expect("v2.120 _hard_stop: заблокированный push (не scope) -> НЕ scope-violation",
               _hard_stop({"commit": {"sha": "a"}, "loop": {"denied_reasons": ["git push запрещён политикой"]}}) is None)

    # v2.124 (P0.4): open_pr запрошен, но последовательность НЕ ready_all -> draft PR НЕ открывается
    # (доставка ПОСЛЕ агрегатного вердикта, не по готовности отдельного пакета).
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        cur = mkrepo(td)
        sig = {"task_type": "ENGINEERING", "size": "large", "risk": "low",
               "affected_areas": ["catalog", "orders"]}
        pkgs = atomic_planner.decompose(sig, wid="seqpr", child_root=root)["work_packages"]
        def prop_pr(pkg):
            it = iter([{"op": "write", "path": f"src/{pkg['id']}.py", "content": "x=1\n"}, {"done": True}])
            return lambda c: next(it)
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            # без author/review -> пакеты исполнены, но НЕ ready (артефакт-гейты unmet) -> ready_all=False
            seqpr = execute_sequence("рефактор", sig, root, pkgs, prop_pr, feature="seqpr",
                                     base=cur, open_pr=True)
        _dpr = seqpr.get("delivery") or {}
        expect("v2.124 (P0.4): не ready_all + open_pr -> PR НЕ открыт (delivery=not-attempted, draft_pr=None)",
               seqpr["ready_all"] is False and _dpr.get("status") == "not-attempted"
               and seqpr.get("draft_pr") is None and _dpr.get("requested") is True)

    # v2.120 (P0.3): reviewer FAIL на пакете 1 останавливает цепочку (пакет 2 не стартует)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        cur = mkrepo(td)
        sig = {"task_type": "ENGINEERING", "size": "large", "risk": "low",
               "affected_areas": ["catalog", "orders", "billing"]}
        pkgs = atomic_planner.decompose(sig, wid="seqr", child_root=root)["work_packages"]
        def prop_for(pkg):
            it = iter([{"op": "write", "path": f"src/{pkg['id']}.py", "content": "x=1\n"}, {"done": True}])
            return lambda c: next(it)
        fail_reviewer = lambda p: '{"kind":"reviewer-result","status":"fail","checks":[{"id":"c","status":"fail"}],"blockers":["плохо"]}'
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            seqr = execute_sequence("рефактор с fail-ревью", sig, root, pkgs, prop_for, feature="seqr",
                                    base=cur, author=True, author_proposer=author,
                                    review=True, reviewer_proposer=fail_reviewer)
        ids_seen = [p["id"] for p in seqr["packages"]]
        expect("v2.120 executor: reviewer FAIL на пакете 1 -> цепочка остановлена (stop_reason=reviewer-fail)",
               seqr["stopped_at"] == pkgs[0]["id"] and seqr["executed_all"] is False
               and seqr["packages"][0]["stop_reason"] == "reviewer-fail" and pkgs[2]["id"] not in ids_seen)

    # v2.120 (P0.2): sandbox наследуется в per-package прогон (containment не теряется)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        cur = mkrepo(td)
        sig = {"task_type": "QUICK", "size": "large", "risk": "low",
               "affected_areas": ["catalog", "orders", "billing"]}
        pkgs = atomic_planner.decompose(sig, wid="seqs", child_root=root)["work_packages"]
        def prop_for(pkg):
            it = iter([{"op": "write", "path": f"src/{pkg['id']}.py", "content": "x=1\n"}, {"done": True}])
            return lambda c: next(it)
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            execute_sequence("рефактор в sandbox", sig, root, pkgs, prop_for, feature="seqs",
                             base=cur, sandbox=True, baseline_diff=False)
        rep0 = json.loads((root / "features" / "seqs" / "work-packages" / pkgs[0]["id"] / "report.json").read_text())
        expect("v2.120 executor: sandbox=True наследуется -> containment.sandbox=True в прогоне пакета",
               (rep0.get("containment") or {}).get("sandbox") is True
               and (rep0.get("containment") or {}).get("shell_mode") == "allowlist")

    # блок пакета останавливает последовательность (пакет 2 с secret_boundary без approval -> preflight блок)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        cur = mkrepo(td)
        sig = {"task_type": "ENGINEERING", "size": "large", "risk": "low",
               "affected_areas": ["catalog", "orders", "billing"]}
        wp = atomic_planner.decompose(sig, wid="seqb", child_root=root)
        pkgs = wp["work_packages"]

        def prop_for(pkg):
            it = iter([{"op": "write", "path": f"src/{pkg['id']}.py", "content": "x=1\n"}, {"done": True}])
            return lambda c: next(it)

        def sig_for(pkg):
            return {"secret_boundary": True} if pkg["id"] == pkgs[1]["id"] else {}

        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            # v2.121: author=True снимает spec-first блок heavy для пакетов 1/3 -> изолируем ИМЕННО
            # блок пакета 2 по secret_boundary (approvals-гейт независим от author).
            seq2 = execute_sequence("рефактор с блоком", sig, root, pkgs, prop_for, feature="seqb",
                                    base=cur, signals_for=sig_for, author=True, author_proposer=author)
        # пакет 1 исполнен, пакет 2 заблокирован preflight (secret_boundary без ApprovalRecord),
        # пакет 3 НЕ стартовал
        ids_seen = [p["id"] for p in seq2["packages"]]
        expect("executor: блок пакета 2 останавливает последовательность (пакет 3 НЕ стартовал)",
               seq2["stopped_at"] == pkgs[1]["id"] and pkgs[0]["id"] in seq2["completed"]
               and pkgs[2]["id"] not in ids_seen and seq2["executed_all"] is False)

    print("workpackage_executor selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
