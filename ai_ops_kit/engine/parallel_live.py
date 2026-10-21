#!/usr/bin/env python3
"""parallel_live.py (v3.8.3-rc2) — LIVE MULTI-PACKAGE execution с governed fan-in. Два пути:
  - run_live (СЕРИЙНО, один репо): execution_concurrency=serial, parallel_safe=true, fan_in=live;
  - run_live_concurrent (НАСТОЯЩАЯ конкурентность): отдельный disposable-клон+ветка+прогон на пакет,
    integration-клон -> fetch package-ветки -> merge -> stack-aware aggregate на НОВОМ integration-SHA.

Инварианты (из parallel_planner/executor, не ослабляются):
  - package-SHA НЕ доказывают всю работу -> после fan-in новый integration-SHA + повтор проверок;
  - доставка открывается ТОЛЬКО при зелёном aggregate на integration-SHA;
  - пакеты parallel-SAFE по непересекающимся write_scope.

v3.8.3-rc2 Parallel Trust Wiring (concurrent path):
  #1 package-specific signals (write_scope/affected_areas/shared_contracts/capability/budget), не одинаковые;
  #2 post-commit changed_files ⊆ write_scope -> нарушитель НЕ проходит в fan-in;
  #3 contract_shas прокидывается в executor (shared-contract-first, не хардкод None);
  #5 parallel_live НЕ владеет доставкой -> возвращает DeliveryPlan для канонического Intent/Receipt controller;
  #5b DeliveryPlan несёт РЕАЛЬНЫЙ github_remote (клон интеграции имеет origin = локальный путь);
  #7 fail-closed на clone/checkout/fetch/merge (ошибка блокирует, не «тихо зелёный»);
  #8 run-scoped уникальный каталог клонов + гарантированная очистка.
Аггрегатный strict security (#4/#4b) и provider fallback (#6) — в ai_ops_run/workpackage_executor (rc2b).

Только stdlib + существующие модули кита. CLI: parallel_live.py --selftest
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from ai_ops_kit.shared import _bootstrap  # noqa: E402
from ai_ops_kit.shared import gitio, usage_ledger, lifecycle_store       # noqa: E402
from ai_ops_kit.engine import parallel_executor as pe   # noqa: E402


def _git(root, *args, check=True):
    # RAW-обёртка (а не gitio.git): вызыватели читают CompletedProcess — .stdout/.stderr/.returncode —
    # и полагаются на порядок mutating-команд (checkout/reset/merge/push). timeout= обязателен по
    # тому же инварианту, что держит gitio: зависший git не вешает fan-in. Таймаут -> синтетический
    # rc=124, и check=True превратит его в RuntimeError, как любой другой сбой git.
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                           timeout=gitio.GIT_TIMEOUT_DEFAULT)
    except subprocess.TimeoutExpired:
        r = subprocess.CompletedProcess(["git", "-C", str(root), *args], 124, "",
                                        f"git timeout {gitio.GIT_TIMEOUT_DEFAULT}s")
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()[:200]}")
    return r


def _ensure_identity(root):
    """Гарантировать git-идентичность в СОЗДАННОМ НАМИ клоне. -> True, если поставили fallback.

    `git clone` не наследует локальный user.name/email источника. В окружении без ГЛОБАЛЬНОЙ
    идентичности (CI-раннер, чистый контейнер) любой коммит в таком клоне падает — и fan-in
    считал бы это КОНФЛИКТОМ пакетов, хотя ветки сливаются чисто. Это ложный негатив, а по
    инварианту кита статус обязан быть честным: конфликт — это конфликт, а не отсутствие
    настроек. Fallback ставится ТОЛЬКО когда идентичность не разрешается — реальные окружения
    (у пользователя/агента она есть) сохраняют свою и авторство коммитов не подменяется.
    """
    # Единый вход к git с таймаутом (см. shared/gitio): читаем только rc.
    if gitio.git(root, "var", "GIT_COMMITTER_IDENT")[0] == 0:
        return False
    _git(root, "config", "user.email", "ai-ops@local", check=False)
    _git(root, "config", "user.name", "AI Ops", check=False)
    return True


# --- v3.8.3-rc2 Parallel Trust Wiring helpers ---
_INFRA_PREFIXES = (".ai/", "openspec/", "features/")


def _glob_match(path, pat):
    """write_scope-глоб. 'api/**' и 'src/' (каталог) -> префикс; 'aa.py' -> точное; иначе fnmatch."""
    if pat.endswith("/**"):
        base = pat[:-3]
        return path == base or path.startswith(base + "/")
    if pat.endswith("**"):
        return path.startswith(pat[:-2])
    if fnmatch.fnmatch(path, pat) or path == pat:
        return True
    # Запись-каталог без wildcard (голый сегмент 'quality' или trailing-slash 'src/') -> prefix-семантика,
    # согласовано с parallel_planner._prefix/_overlap. Иначе легитимный 'quality/foo.py' не матчил бы
    # scope='quality' и пакет ложно помечался fail (переблок хорошей работы). Точный файл ('calc.py')
    # уже пойман ветками выше, так что prefix-fallback его не портит.
    if not any(ch in pat for ch in "*?["):
        base = pat.rstrip("/")
        return bool(base) and (path == base or path.startswith(base + "/"))
    return False


def _changed_files(root, base_sha, head="HEAD"):
    """Файлы, изменённые между base_sha и head (для post-commit scope-проверки). head по умолчанию HEAD,
    но concurrent-путь ОБЯЗАН передавать РЕАЛЬНЫЙ package-SHA: ai_ops_run коммитит в ВЛОЖЕННЫЙ
    worktree-branch внутри клона, а HEAD самого клона остаётся на base -> diff base...HEAD был бы пуст
    (scope-проверка no-op). Диффим base...<package_sha>."""
    r = _git(root, "diff", "--name-only", f"{base_sha}...{head}", check=False)
    if r.returncode != 0:
        r = _git(root, "diff", "--name-only", base_sha, head, check=False)
    return [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]


def _is_build_artifact(f):
    """Инкрементальные build-артефакты (не код модели): setuptools egg-info, кэши, dist/build, lock-файлы,
    node_modules. Создаются install/сборкой, не писателем -> НЕ считаются нарушением write_scope."""
    return (".egg-info/" in f or "__pycache__/" in f or f.endswith((".pyc", ".pyo"))
            or f.startswith(("dist/", "build/", "node_modules/", ".pytest_cache/", ".mypy_cache/", ".ruff_cache/"))
            or "/dist/" in f or "/build/" in f or "/node_modules/" in f
            or f.endswith((".lock",)) or f == "package-lock.json" or f.endswith("/package-lock.json"))


def _scope_ok(changed, write_scope):
    """#2 post-commit: changed_files ⊆ write_scope. Инфра-пути (.ai/openspec/features) и инкрементальные
    build-артефакты (egg-info/кэши/lock/node_modules) разрешены. write_scope пуст -> не форсим здесь
    (границу объявляет план). -> (ok, outside_files)."""
    if not write_scope:
        return True, []
    outside = [f for f in changed
               if not f.startswith(_INFRA_PREFIXES) and not _is_build_artifact(f)
               and not any(_glob_match(f, p) for p in write_scope)]
    return (not outside), outside


def _github_remote(child_root):
    """#5b: реальный GitHub-remote (origin) исходного child_root — чтобы доставка шла на GitHub,
    а НЕ в локальный клон (клон интеграции имеет origin = локальный путь). None если origin не GitHub."""
    r = _git(child_root, "remote", "get-url", "origin", check=False)
    url = (r.stdout or "").strip()
    return url if (r.returncode == 0 and ("github.com" in url or url.endswith(".git"))) else None


from ai_ops_kit.shared import work_areas as _work_areas   # noqa: E402 — #138: одна формула зон


def _pkg_signals(base_signals, pkg):
    """#1: package-specific view сигналов — write_scope/affected_areas/shared_contracts/capability/budget
    из объявления пакета WorkGraph. НЕ шлём одинаковые signals всем пакетам."""
    sig = dict(base_signals or {})
    saved = sig.pop("_auto_package_signals", {})
    sig.update(saved.get(pkg["id"], {}))
    ws = pkg.get("write_scope")
    if ws:
        sig["write_scope"] = ws
        # #138: формула вывода зон теперь ОДНА на оба пути (`work_areas`). Прежняя копия жила здесь и
        # брала первый сегмент пути, теряя записи без слэша (`quality`) — и расходилась бы с
        # одиночным путём, где вывода не было вовсе.
        sig["affected_areas"] = pkg.get("affected_areas") or _work_areas.from_write_scope(ws)
    elif pkg.get("affected_areas"):
        sig["affected_areas"] = pkg["affected_areas"]
    for k in ("shared_contracts", "capability", "budget"):
        if pkg.get(k):
            sig[k if k != "budget" else "budget_contract"] = pkg[k]
    return sig


def package_result_from_rep(rep):
    """rep (ai_ops_run) -> package-result для integration_gate. ЧИСТАЯ функция (тестируема)."""
    if not isinstance(rep, dict):
        return {"status": "error", "sha": None, "gate_report": {"all_pass": False}, "error": "rep не dict"}
    sha = (rep.get("commit") or {}).get("sha")
    ok = bool(rep.get("ready_for_pr"))
    return {"status": "pass" if ok else "fail", "sha": sha,
            "gate_report": {"all_pass": ok, "tested_revision": sha},
            "model_resolution": rep.get("model_resolution"), "package_capacity": rep.get("package_capacity")}


def make_package_runner(child_root, base_sha, task_map, signals, run_fn, features_dir=None):
    """package_runner(pkg): прогнать ai_ops_run для задачи пакета в СВОЕЙ ветке (feature=pkg.id).
    run_fn — ai_ops_run.run (инъекция для тестов). Возвращает package-result."""
    def runner(pkg):
        pid = pkg["id"]
        task = task_map[pid]
        # каждый пакет от общей базы, своя фича/ветка
        _git(child_root, "checkout", "-q", "main", check=False)
        _git(child_root, "reset", "--hard", "-q", base_sha)
        _git(child_root, "clean", "-fdq", "-e", ".ai", check=False)
        rep = run_fn(task, dict(signals), Path(child_root), engine="pipeline",
                     provider_name="openai-compatible", feature=pid, execute=True,
                     author=True, review=True, features_dir=features_dir, verification_intent="draft")
        return package_result_from_rep(rep)
    return runner


def make_integration_runner(child_root, base_sha, integration_branch="ai-ops/integration"):
    """integration_runner(results): создать integration-ветку от base, слить ветки пакетов (git fan-in),
    ПОВТОРИТЬ aggregate (pytest) на НОВОМ integration-SHA. -> (integration_sha, aggregate, conflicts, base_moved)."""
    def runner(results):
        _git(child_root, "checkout", "-q", "main", check=False)
        _git(child_root, "branch", "-D", integration_branch, check=False)
        _git(child_root, "checkout", "-q", "-B", integration_branch, base_sha)
        conflicts = 0
        for pid in results:
            br = f"ai-ops/{pid}"
            m = _git(child_root, "merge", "--no-edit", "--no-ff", br, check=False)
            if m.returncode != 0:
                conflicts += 1
                _git(child_root, "merge", "--abort", check=False)
        integration_sha = _git(child_root, "rev-parse", "HEAD").stdout.strip()
        # v3.8.2 STACK-AWARE aggregate на integration-SHA: детект стека (project_detector) + повтор
        # evidence_collector (backend pytest/lint/typecheck; frontend build/lint/test; ...) — НЕ хардкод
        # pytest. Как у sequential-executor'а (_aggregate_verify). Fail-closed при сбое коллектора.
        tested_revision, postcheck_revision, revision_ok, tree_clean = None, None, False, False
        try:
            from ai_ops_kit.shared import project_detector as _pd
            from ai_ops_kit.gates import evidence_collector as _ec
            from ai_ops_kit.engine import tool_broker as _tb
            from ai_ops_kit.engine.pipeline_git import _tree_clean_after_checks
            _pol = _tb.sandbox_policy(child_root=str(child_root))
            _coll = _ec.collect(_pd.detect(child_root), child_root, _pol, broker=_tb, lifecycle_intent="merge_candidate")
            _iv = (_coll.get("gate_evidence") or {}).get("implementation_verification") or {}
            tested_revision = _coll.get("revision")
            postcheck_revision = _git(child_root, "rev-parse", "HEAD").stdout.strip()
            revision_ok = tested_revision == integration_sha == postcheck_revision
            tree_clean = _tree_clean_after_checks(child_root)
            stack_ok = _iv.get("status") == "pass" and revision_ok and tree_clean
            stack_checks = {k: (v.get("status") if isinstance(v, dict) else v) for k, v in (_coll.get("checks") or {}).items()}
        except Exception as _e:  # noqa: BLE001 — сбой коллектора -> fail-closed
            stack_ok = False
            stack_checks = {"error": f"{type(_e).__name__}: {_e}"[:160]}
        all_pass = conflicts == 0 and stack_ok
        aggregate = {"all_pass": all_pass, "tested_revision": tested_revision, "conflicts": conflicts,
                     "postcheck_revision": postcheck_revision, "revision_ok": revision_ok, "tree_clean": tree_clean,
                     "stack_aware": True, "stack_checks": stack_checks}
        return integration_sha, aggregate, conflicts, False
    return runner


def _porcelain_path(ln):
    """Путь из строки `git status --porcelain` (`XY <path>`; переименование — `XY <old> -> <new>`).
    Строка кончается ИМЕНЕМ файла, а не статусом, поэтому фильтровать `.ai/`-churn надо по пути."""
    p = ln[3:] if len(ln) > 3 else ln.strip()
    if " -> " in p:
        p = p.split(" -> ", 1)[1]
    return p.strip().strip('"')


def preflight_disposable(child_root):
    """v3.7.1 (#2): runner делает reset --hard/clean -fd -> ЗАПРЕЩЕН в обычном рабочем checkout с
    незакоммиченными файлами (уничтожил бы их). Требует чистый/disposable checkout. -> (ok, reason).
    Послабление для `.ai/`-churn: строки porcelain кончаются ПУТЁМ (` M .ai/state.json` -> '.json'),
    поэтому раньше `endswith('.ai')` не исключал ничего (no-op) — сверяем начало РЕАЛЬНОГО пути."""
    def _is_ai_churn(ln):
        p = _porcelain_path(ln)
        return p == ".ai" or p.startswith(".ai/")

    st = _git(child_root, "status", "--porcelain", check=False)
    dirty = [ln for ln in (st.stdout or "").splitlines() if ln.strip() and not _is_ai_churn(ln)]
    if dirty:
        return False, ("грязный checkout: runner делает reset --hard/clean -fd и уничтожит "
                       f"незакоммиченные файлы ({len(dirty)}). Нужен disposable-clone/чистый checkout.")
    return True, "clean"


def run_live(wg, child_root, base_sha, task_map, signals, run_fn, open_pr=False,
             repo_slug=None, features_dir=None, integration_branch="ai-ops/integration"):
    """Live MULTI-PACKAGE execution с governed fan-in (НЕ настоящий concurrency — см. поля ниже): пакеты
    -> fan-in -> (опц.) ОДИН draft PR. Пакеты СЕРИЙНО (max_parallel=1, против гонок git-worktree в одном
    репо); parallel-SAFE по write_scope; настоящая конкурентность = отдельные клоны на пакет.
    ТРЕБУЕТ disposable/чистый checkout (runner делает reset --hard/clean)."""
    ok, reason = preflight_disposable(child_root)
    if not ok:
        return {"proceed": False, "stage": "preflight", "reason": reason,
                "execution_concurrency": "serial", "parallel_safe": True, "fan_in": "live",
                "delivery": {"intents": 0, "open_pr": False}, "pr": None}
    pr = make_package_runner(child_root, base_sha, task_map, signals, run_fn, features_dir)
    ir = make_integration_runner(child_root, base_sha, integration_branch)
    rec = pe.execute_parallel(wg, pr, ir, contract_shas=None, max_parallel=1)
    # честные поля (не выдаём serial за parallel): governance/fan-in — живые, concurrency — серийный
    rec["execution_concurrency"] = "serial"
    rec["parallel_safe"] = True
    rec["fan_in"] = "live"
    rec["concurrency_note"] = "серийно (max_parallel=1); настоящая конкурентность требует отдельных клонов на пакет"
    rec["pr"] = None
    if open_pr and rec.get("delivery", {}).get("open_pr") and repo_slug:
        # --force-with-lease (осознанно, как delivery/pr_open.py #401): безопаснее сырого -f — падёт,
        # если в ветку дописали извне, вместо тихой затирки. Результат ПРОВЕРЯЕТСЯ: при сбое push
        # возвращаем явную ошибку, а не глотаем rc и не идём в gh pr create с запутанной ошибкой.
        push = _git(child_root, "push", "--force-with-lease", "-q", "origin", integration_branch, check=False)
        if push.returncode != 0:
            rec["pr"] = None
            rec["push_error"] = (f"push --force-with-lease integration-ветки не удался "
                                 f"(rc={push.returncode}): {(push.stderr or '').strip()[:200]}")
            return rec
        title = f"[parallel-2] {wg.get('id')} fan-in @ {rec['integration_sha'][:12]}"
        body = (f"Автоматический parallel-2 fan-in (integration-SHA {rec['integration_sha'][:12]}).\n"
                f"Пакеты: {', '.join(task_map)}. aggregate повторён на integration-SHA.\n\n"
                "🤖 Generated with [Claude Code](https://claude.com/claude-code)")
        p = subprocess.run(["gh", "pr", "create", "--repo", repo_slug, "--draft",
                            "--head", integration_branch, "--base", "main",
                            "--title", title, "--body", body], cwd=str(child_root),
                           capture_output=True, text=True)
        rec["pr"] = (p.stdout.strip() or p.stderr.strip())[:300]
    return rec


def make_isolated_package_runner(child_root, base_sha, task_map, signals, run_fn, clones_dir, clones,
                                 run_options=None):
    """v3.8.3 TRUE CONCURRENT: каждый пакет — в СВОЁМ disposable-клоне (git clone) на base_sha -> безопасно
    конкурентно (нет гонок git-worktree одного репо). Заполняет clones[pid]={path,branch}.
    v3.8.3-rc2: (#1) package-specific signals; (#7) fail-closed clone/checkout; (#2) post-commit
    changed_files ⊆ write_scope (нарушение -> пакет fail, не проходит в fan-in)."""
    def runner(pkg):
        pid = pkg["id"]
        cpath = Path(clones_dir) / pid
        # git clone — форма не под `-C`: единый вход с таймаутом через gitio.run (см. shared/gitio).
        cl_rc, _, cl_err = gitio.run(["clone", "-q", str(child_root), str(cpath)])
        if cl_rc != 0:  # #7 fail-closed
            clones[pid] = {"path": str(cpath), "branch": f"ai-ops/{pid}", "error": "clone-failed"}
            return {"status": "error", "sha": None, "gate_report": {"all_pass": False},
                    "error": f"clone: {cl_err[:160]}", "clone": str(cpath)}
        _ensure_identity(cpath)  # прогон пакета коммитит в этом клоне — идентичность не унаследована
        co = _git(cpath, "checkout", "-q", base_sha, check=False)
        if co.returncode != 0:  # #7 fail-closed
            clones[pid] = {"path": str(cpath), "branch": f"ai-ops/{pid}", "error": "checkout-failed"}
            return {"status": "error", "sha": None, "gate_report": {"all_pass": False},
                    "error": f"checkout {base_sha[:12]}: {co.stderr.strip()[:160]}", "clone": str(cpath)}
        options = dict(run_options or {})
        if options.get("base"):
            _git(cpath, "checkout", "-q", "-B", options["base"], base_sha)
        options.setdefault("provider_name", "openai-compatible")
        options.setdefault("author", True)
        options.setdefault("review", True)
        options.update(engine="pipeline", feature=pid, execute=True, open_pr=False,
                       write_scope=pkg.get("write_scope"), verification_intent="draft")
        pkg_signals = _pkg_signals(signals, pkg)
        pkg_signals.update(work_package_id=pid, _sequence_plan_ids=list(task_map))
        clones[pid] = {"path": str(cpath), "branch": f"ai-ops/{pid}"}
        clones[pid]["usage_baseline"] = usage_ledger.snapshot_ledgers(cpath)
        baseline_path = Path(clones_dir) / "_package-baselines" / (hashlib.sha256(pid.encode()).hexdigest() + ".json")
        saved = lifecycle_store.durable_write_json(baseline_path, {"package_id": pid, "base_sha": base_sha,
                                                   "streams": clones[pid]["usage_baseline"]})
        if not saved.get("ok"):
            raise ValueError("package usage baseline не зафиксирована до вызовов")
        reused = options.pop('reused_packages', {}).get(pid)
        if reused:
            return _restore_package_checkpoint(child_root, cpath, pid, reused)
        rep = run_fn(task_map[pid], pkg_signals, Path(cpath), **options)
        res = package_result_from_rep(rep)
        res["clone"] = str(cpath)
        # #2 post-commit: заявленный write_scope принуждается на РЕАЛЬНОМ диффе (клон изолирует физически,
        # но не запрещает модели тронуть лишний файл — принуждаем декларацию плана исполнением).
        if res.get("sha") and pkg.get("write_scope"):
            changed = _changed_files(cpath, base_sha, res["sha"])   # #2-fix: диффим РЕАЛЬНЫЙ package-SHA,
            sok, outside = _scope_ok(changed, pkg["write_scope"])   # не HEAD клона (ai_ops_run — вложенный worktree)
            res["scope_check"] = {"write_scope": pkg["write_scope"], "changed": len(changed),
                                  "outside": outside[:20], "ok": sok}
            if not sok:
                res["status"] = "fail"
                res.setdefault("gate_report", {})["all_pass"] = False
                res["scope_violation"] = outside[:20]
        return res
    return runner


def make_isolated_integration_runner(child_root, base_sha, clones, integration_branch="ai-ops/integration"):
    """v3.8.3: integration-КЛОН от base; fetch веток пакетов ИЗ их клонов (по пути) + merge; stack-aware
    aggregate (project_detector+evidence_collector) на НОВОМ integration-SHA. fail-closed при сбое."""
    def runner(results):
        iroot = (clones.get("_integration") or {}).get("path")
        if not iroot:  # #7 fail-closed: нет integration-клона -> блок (не «тихо зелёный»)
            return None, {"all_pass": False, "conflicts": len(results), "stack_aware": True,
                          "stack_checks": {"error": "integration-клон отсутствует"},
                          "isolation": "per-package-clone"}, len(results) or 1, False
        co = _git(iroot, "checkout", "-q", "-B", integration_branch, base_sha, check=False)
        if co.returncode != 0:  # #7 fail-closed
            return None, {"all_pass": False, "conflicts": len(results), "stack_aware": True,
                          "stack_checks": {"error": f"integration checkout: {co.stderr.strip()[:120]}"},
                          "isolation": "per-package-clone"}, len(results) or 1, False
        conflicts = 0
        for pid in results:
            c = clones.get(pid)
            if not c or c.get("error"):  # #7: битый/отсутствующий пакетный клон -> конфликт (блокирует)
                conflicts += 1; continue
            f = _git(iroot, "fetch", "-q", c["path"], f"{c['branch']}:{c['branch']}", check=False)
            if f.returncode != 0:  # #7 fail-closed: не смогли забрать ветку пакета
                conflicts += 1; continue
            m = _git(iroot, "merge", "--no-edit", "--no-ff", c["branch"], check=False)
            if m.returncode != 0:
                conflicts += 1; _git(iroot, "merge", "--abort", check=False)
        integration_sha = _git(iroot, "rev-parse", "HEAD").stdout.strip()
        tested_revision, postcheck_revision, revision_ok, tree_clean = None, None, False, False
        try:
            from ai_ops_kit.shared import project_detector as _pd
            from ai_ops_kit.gates import evidence_collector as _ec
            from ai_ops_kit.engine import tool_broker as _tb
            from ai_ops_kit.engine.pipeline_git import _tree_clean_after_checks
            _coll = _ec.collect(_pd.detect(iroot), iroot, _tb.sandbox_policy(child_root=str(iroot)), broker=_tb,
                                lifecycle_intent="merge_candidate")
            _iv = (_coll.get("gate_evidence") or {}).get("implementation_verification") or {}
            tested_revision = _coll.get("revision")
            postcheck_revision = _git(iroot, "rev-parse", "HEAD").stdout.strip()
            revision_ok = tested_revision == integration_sha == postcheck_revision
            tree_clean = _tree_clean_after_checks(iroot)
            stack_ok = _iv.get("status") == "pass" and revision_ok and tree_clean
            stack_checks = {k: (v.get("status") if isinstance(v, dict) else v) for k, v in (_coll.get("checks") or {}).items()}
        except Exception as _e:  # noqa: BLE001
            stack_ok = False; stack_checks = {"error": f"{type(_e).__name__}: {_e}"[:160]}
        all_pass = conflicts == 0 and stack_ok
        return integration_sha, {"all_pass": all_pass, "tested_revision": tested_revision, "conflicts": conflicts,
                                 "postcheck_revision": postcheck_revision, "revision_ok": revision_ok, "tree_clean": tree_clean,
                                 "stack_aware": True, "stack_checks": stack_checks,
                                 "isolation": "per-package-clone"}, conflicts, False
    return runner


def _artifact_sha(value):
    return value if isinstance(value, str) and len(value) == 40 and all(c in "0123456789abcdef" for c in value) else None


class _CheckpointFailure(ValueError):
    """Только фиксированный stage code; Git stderr/модельные данные не уходят в receipt."""


def _checkpoint_git(root, stage, *args, **options):
    try:
        return _git(root, *args, **options)
    except (RuntimeError, OSError) as exc:
        raise _CheckpointFailure(stage) from exc


def _require_direct_checkpoint_ref(root, ref):
    kind = _checkpoint_git(root, "ref-type", "symbolic-ref", "--quiet", ref, check=False)
    if kind.returncode == 0:
        raise _CheckpointFailure("ref-symbolic")
    if kind.returncode != 1:
        raise _CheckpointFailure("ref-type")


def _retain_package_commit(child_root, source, sha, run_id, pid):
    """Git objects+CAS ref до удаления source; local checkpoint, не доставка/ready."""
    version = _checkpoint_git(child_root, "version", "--version").stdout
    parsed = re.search(r"\b(\d+)\.(\d+)", version)
    if not parsed or tuple(map(int, parsed.groups())) < (2, 36):
        raise _CheckpointFailure("unsupported-git")
    ref = f"refs/ai-ops/parallel/{run_id}/{hashlib.sha256(pid.encode()).hexdigest()}"
    _require_direct_checkpoint_ref(child_root, ref)
    old = _checkpoint_git(child_root, "ref-read", "rev-parse", "--verify", "--quiet", ref, check=False)
    if old.returncode not in (0, 1) or (old.returncode == 0 and old.stdout.strip() != sha):
        raise _CheckpointFailure("ref-conflict")
    harden = ("-c", "core.fsync=objects,reference", "-c", "core.fsyncMethod=fsync")
    if old.returncode == 1:
        _checkpoint_git(child_root, "fetch", *harden, "fetch", "--no-tags", "--no-write-fetch-head",
             "--no-recurse-submodules", "--no-auto-maintenance", "--no-write-commit-graph",
                        "--no-prune", "--no-prune-tags", str(source.resolve()), sha)
    # Same SHA retry тоже проходит CAS/hardened write, но никогда не перезаписывает другую generation.
    _checkpoint_git(child_root, "ref-write", *harden, "update-ref", "--no-deref", ref, sha, sha if old.returncode == 0 else "0" * 40)
    _require_direct_checkpoint_ref(child_root, ref)
    if _checkpoint_git(child_root, "ref-readback", "rev-parse", "--verify", ref).stdout.strip() != sha:
        raise _CheckpointFailure("ref-readback")
    _checkpoint_git(child_root, "objects", "cat-file", "-e", f"{sha}^{{commit}}")
    _checkpoint_git(child_root, "objects", "cat-file", "-e", f"{sha}^{{tree}}")
    return ref


def _preserve_package_artifacts(child_root, base_sha, clones, run_dir, results):
    """Whitelist evidence + call streams до удаления последней package source копии."""
    run_root = Path(run_dir).resolve()
    run_id = hashlib.sha256(str(run_root).encode()).hexdigest()
    sources, identities, baselines, packages = [], {}, {}, []
    for pid, clone in sorted(clones.items()):
        if pid == "_integration":
            continue
        source = Path(clone["path"])
        result = results.get(pid) or {}
        status = result.get("status")
        item = {"package_id": pid, "status": status if status in ("pass", "fail", "error", "blocked-dependency") else "error",
                "reported_package_sha": _artifact_sha(result.get("sha")), "package_sha": None,
                "base_sha": base_sha, "source_head": None, "usage_streams": {}}
        if not source.is_dir() or not (source / ".git").exists():
            raise ValueError("package source/git отсутствует; cleanup запрещён")
        if source.is_dir():
            item["source_head"] = _git(source, "rev-parse", "HEAD").stdout.strip()
            sha = item["reported_package_sha"]
            if sha and _git(source, "cat-file", "-e", f"{sha}^{{commit}}", check=False).returncode == 0:
                item["package_sha"] = sha
                item["retained_ref"] = _retain_package_commit(child_root, source, sha, run_id, pid)
            item["usage_streams"] = usage_ledger.snapshot_ledgers(source)
            identity = f"{run_id}/{pid}"
            item["source_id"] = identity
            sources.append(source)
            identities[str(source)] = identity
            baseline_path = run_root / "_package-baselines" / (hashlib.sha256(pid.encode()).hexdigest() + ".json")
            usage_ledger._no_symlink(run_root, baseline_path)
            if not baseline_path.is_file():
                raise ValueError("package durable baseline отсутствует; cleanup запрещён")
            saved = json.loads(baseline_path.read_text(encoding="utf-8"))
            if (not isinstance(saved, dict) or saved.get("package_id") != pid or saved.get("base_sha") != base_sha
                    or not isinstance(saved.get("streams"), dict)
                    or clone.get("usage_baseline", saved["streams"]) != saved["streams"]):
                raise ValueError("package usage baseline identity mismatch")
            baselines[str(source)] = saved["streams"]
        gate = result.get("gate_report") if isinstance(result.get("gate_report"), dict) else {}
        item["gate_report"] = {"all_pass": gate.get("all_pass") is True,
                               "tested_revision": _artifact_sha(gate.get("tested_revision"))}
        item['package_capacity'] = result.get('package_capacity')
        item["usage_status"] = "available" if item["usage_streams"] else "unavailable"
        packages.append(item)
    count = usage_ledger.merge_ledgers(child_root, sources, source_ids=identities, source_baselines=baselines)
    path = Path(child_root).resolve() / ".ai/usage/parallel" / run_id / "package-receipt.json"
    usage_ledger._no_symlink(Path(child_root).resolve(), path)
    receipt = {"kind": "ParallelPackageReceipt", "run_id": run_id, "base_sha": base_sha,
               "packages": packages, "usage_identity": "source/run + stream + byte offset"}
    written = lifecycle_store.durable_write_json(path, receipt)
    if not written.get("ok") or json.loads(path.read_text(encoding="utf-8")) != receipt:
        raise ValueError("package receipt durable write/readback не подтверждён")
    if any(usage_ledger.snapshot_ledgers(source) != item["usage_streams"]
           for source, item in zip(sources, [p for p in packages if p.get("source_id")])):
        raise ValueError("package usage source изменилась до cleanup")
    return {"status": "preserved", "receipt": str(path), "new_product_calls": count}


def _cleanup_owned_package_sources(clones_dir, retain_integration):
    try:
        paths = [p for p in Path(clones_dir).iterdir() if p.name != "_integration"] if retain_integration else [Path(clones_dir)]
    except OSError:
        return {"status": "partial", "retained_paths": [str(clones_dir)], "integration_retained": retain_integration}
    retained = []
    for path in paths:
        try:
            if path.is_symlink() or not path.is_dir():
                path.unlink()
            else:
                shutil.rmtree(path)
        except FileNotFoundError:
            continue
        except OSError:
            retained.append(str(path))
    return {"status": "partial" if retained else "complete", "retained_paths": retained,
            "integration_retained": retain_integration}


def run_live_concurrent(wg, child_root, base_sha, task_map, signals, run_fn, clones_dir=None,
                        repo_slug=None, integration_branch="ai-ops/integration", max_parallel=None,
                        contract_shas=None, run_options=None):
    """v3.8.3 НАСТОЯЩИЙ concurrent parallel-2: отдельный disposable-клон+ветка+прогон на пакет, КОНКУРЕНТНО;
    integration-клон -> fetch package-ветки -> merge -> stack-aware aggregate. Честные поля:
    execution_concurrency=concurrent, isolation=per-package-clone. Основной checkout НЕ трогается.

    v3.8.3-rc2 Parallel Trust Wiring:
      (#3) contract_shas прокидывается в executor (shared-contract-first, не хардкод None);
      (#5) parallel_live НЕ владеет доставкой — возвращает rec["delivery_plan"] для канонического
           controller'а (DeliveryIntent -> push -> DeliveryReceipt); прямого push/gh pr create тут НЕТ;
      (#5b) delivery_plan несёт РЕАЛЬНЫЙ github_remote исходного репо (клон интеграции имеет origin =
            локальный путь — доставка в него не попала бы на GitHub);
      (#7) fail-closed при сбое клона интеграции;
      (#8) run-scoped каталог в git common dir: неготовый удаляется, готовая integration
           сохраняется для канонической доставки/повтора; package clones очищаются."""
    _self_clones = clones_dir is None
    retain_integration = False
    cleanup_safe = False
    rec = None
    if _self_clones:
        common = _git(child_root, "rev-parse", "--git-common-dir").stdout.strip()
        store = (Path(child_root) / common).resolve() / "ai-ops-parallel"
        store.mkdir(parents=True, exist_ok=True)
        clones_dir = tempfile.mkdtemp(prefix="run-", dir=store)
    try:
        clones = {}
        iroot = Path(clones_dir) / "_integration"
        # git clone — форма не под `-C`: единый вход с таймаутом через gitio.run (см. shared/gitio).
        cl_rc, _, cl_err = gitio.run(["clone", "-q", str(child_root), str(iroot)])
        if cl_rc != 0:  # #7 fail-closed
            cleanup_safe = True  # пакетные вызовы ещё не запускались
            return {"proceed": False, "stage": "isolation", "execution_concurrency": "concurrent",
                    "isolation": "per-package-clone", "reason": f"integration clone: {cl_err[:160]}",
                    "delivery": {"open_pr": False}, "delivery_plan": None, "pr": None}
        _ensure_identity(iroot)  # merge fan-in — это КОММИТ; клон не унаследовал идентичность
        clones["_integration"] = {"path": str(iroot)}
        pr = make_isolated_package_runner(child_root, base_sha, task_map, signals, run_fn,
                                          clones_dir, clones, run_options)
        ir = make_isolated_integration_runner(child_root, base_sha, clones, integration_branch)
        n = max_parallel or min(len(wg.get("packages", []) or [1]), getattr(pe.pp, "MAX_PARALLEL", 2))
        rec = pe.execute_parallel(wg, pr, ir, contract_shas=contract_shas, max_parallel=max(2, n))
        for row in rec.get('trace', []):
            if (rec.get('package_results', {}).get(row['pkg']) or {}).get('reused_from'):
                row['mode'] = 'reused-checkpoint'
        rec["execution_concurrency"] = "concurrent"
        rec["isolation"] = "per-package-clone"
        rec["parallel_safe"] = True
        rec["fan_in"] = "live"
        rec["pr"] = None
        # #5/#5b DeliveryPlan (не доставляем сами): канонический controller зафиксирует Intent, запушит на
        # РЕАЛЬНЫЙ github_remote, откроет PR, зафиксирует Receipt. Готово к доставке только при зелёном aggregate.
        try:
            rec["package_artifacts"] = _preserve_package_artifacts(
                child_root, base_sha, clones, clones_dir, rec.get("package_results") or {})
            cleanup_safe = True
        except Exception as exc:  # noqa: BLE001 — потерю usage нельзя выдать за доставленный результат
            rec["package_artifacts"] = {"status": "blocked", "reason": type(exc).__name__,
                                        "retained_source": str(clones_dir)}
            if isinstance(exc, _CheckpointFailure):
                rec["package_artifacts"]["checkpoint_failure"] = str(exc)
            rec.update(proceed=False, stage="artifact-preservation")
            rec["delivery"] = {"intents": 0, "open_pr": False}
        _ready = bool(rec.get("delivery", {}).get("open_pr") and rec.get("integration_sha"))
        rec["delivery_plan"] = {
            "kind": "DeliveryPlan", "ready": _ready,
            "integration_sha": rec.get("integration_sha"),
            "integration_branch": integration_branch,
            "base_sha": base_sha,
            "integration_clone": str(iroot),
            "github_remote": _github_remote(child_root),   # #5b: реальный GitHub, не локальный клон
            "repo_slug": repo_slug,
            "packages": list(task_map),
            "note": "доставка через канонический DeliveryIntent/Receipt controller; parallel_live не пушит сам",
        }
        retain_integration = _ready
        if _self_clones and _ready:
            rec["delivery_plan"]["owned_clones_dir"] = str(clones_dir)
        return rec
    finally:
        if _self_clones and cleanup_safe:
            cleanup = _cleanup_owned_package_sources(clones_dir, retain_integration)
            if rec is not None:
                rec["cleanup"] = cleanup
        elif rec is not None:
            rec["cleanup"] = {"status": "retained" if _self_clones else "caller-managed",
                              "retained_paths": [str(clones_dir)]}


def main(argv):
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))


def _restore_package_checkpoint(root, clone, pid, checkpoint):
    """Fresh owned clone, exact retained SHA; never invokes package/provider callback."""
    result = json.loads(json.dumps(checkpoint['result']))
    sha, ref = result['sha'], checkpoint['ref']
    _require_direct_checkpoint_ref(root, ref)
    if _git(root, 'rev-parse', '--verify', ref).stdout.strip() != sha:
        raise _CheckpointFailure('resume-ref-changed')
    _checkpoint_git(clone, 'resume-fetch', '-c', 'core.fsync=objects,reference', 'fetch',
        '--no-tags', '--no-write-fetch-head', '--no-recurse-submodules', '--no-auto-maintenance',
        '--no-write-commit-graph', str(Path(root).resolve()), sha)
    _checkpoint_git(clone, 'resume-checkout', 'checkout', '-q', '-B', f'ai-ops/{pid}', sha)
    if _git(clone, 'rev-parse', 'HEAD').stdout.strip() != sha:
        raise _CheckpointFailure('resume-head')
    result.update(clone=str(clone), reused_from=checkpoint['receipt'])
    return result
