#!/usr/bin/env python3
"""parallel_live.py (v3.7.17/3.7.1) — LIVE MULTI-PACKAGE execution с governed fan-in (НЕ настоящий
concurrency): реальные package-runner (ai_ops_run на пакет в своей ветке) + integration-runner (git
fan-in -> НОВЫЙ integration-SHA -> ПОВТОР aggregate). WorkGraph -> пакеты (СЕРИЙНО) -> fan-in -> ОДИН PR.
Честно: execution_concurrency=serial, parallel_safe=true (по write_scope), fan_in=live. Настоящий
concurrency = отдельные клоны на пакет (не в одном репо). Требует disposable/чистый checkout.

Инварианты (из parallel_planner/executor, не ослабляются):
  - package-SHA НЕ доказывают всю работу -> после fan-in новый integration-SHA + повтор проверок;
  - PR открывается ТОЛЬКО при зелёном aggregate на integration-SHA;
  - пакеты parallel-SAFE по непересекающимся write_scope; в этом адаптере исполняются СЕРИЙНО
    (max_parallel=1) — чтобы избежать гонок git-worktree в одном репо (честная инфра-граница; настоящий
    concurrency потребует отдельных клонов на пакет).

Только stdlib + существующие модули кита. CLI: parallel_live.py --selftest
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import parallel_executor as pe   # noqa: E402


def _git(root, *args, check=True):
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()[:200]}")
    return r


def package_result_from_rep(rep):
    """rep (ai_ops_run) -> package-result для integration_gate. ЧИСТАЯ функция (тестируема)."""
    if not isinstance(rep, dict):
        return {"status": "error", "sha": None, "gate_report": {"all_pass": False}, "error": "rep не dict"}
    sha = (rep.get("commit") or {}).get("sha")
    ok = bool(rep.get("ready_for_pr"))
    return {"status": "pass" if ok else "fail", "sha": sha,
            "gate_report": {"all_pass": ok, "tested_revision": sha},
            "model_resolution": rep.get("model_resolution")}


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
                     author=True, review=True, features_dir=features_dir)
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
        try:
            import project_detector as _pd, evidence_collector as _ec, tool_broker as _tb
            _pol = _tb.sandbox_policy(child_root=str(child_root))
            _coll = _ec.collect(_pd.detect(child_root), child_root, _pol)
            _iv = (_coll.get("gate_evidence") or {}).get("implementation_verification") or {}
            stack_ok = _iv.get("status") == "pass"
            stack_checks = {k: (v.get("status") if isinstance(v, dict) else v) for k, v in (_coll.get("checks") or {}).items()}
        except Exception as _e:  # noqa: BLE001 — сбой коллектора -> fail-closed
            stack_ok = False
            stack_checks = {"error": f"{type(_e).__name__}: {_e}"[:160]}
        all_pass = conflicts == 0 and stack_ok
        aggregate = {"all_pass": all_pass, "tested_revision": integration_sha, "conflicts": conflicts,
                     "stack_aware": True, "stack_checks": stack_checks}
        return integration_sha, aggregate, conflicts, False
    return runner


def preflight_disposable(child_root):
    """v3.7.1 (#2): runner делает reset --hard/clean -fd -> ЗАПРЕЩЕН в обычном рабочем checkout с
    незакоммиченными файлами (уничтожил бы их). Требует чистый/disposable checkout. -> (ok, reason)."""
    st = _git(child_root, "status", "--porcelain", check=False)
    dirty = [ln for ln in (st.stdout or "").splitlines() if ln.strip() and not ln.strip().endswith(".ai")]
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
        _git(child_root, "push", "-f", "-q", "origin", integration_branch, check=False)
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


def make_isolated_package_runner(child_root, base_sha, task_map, signals, run_fn, clones_dir, clones):
    """v3.8.3 TRUE CONCURRENT: каждый пакет — в СВОЁМ disposable-клоне (git clone) на base_sha -> безопасно
    конкурентно (нет гонок git-worktree одного репо). Заполняет clones[pid]={path,branch}."""
    def runner(pkg):
        pid = pkg["id"]
        cpath = Path(clones_dir) / pid
        subprocess.run(["git", "clone", "-q", str(child_root), str(cpath)], capture_output=True, text=True)
        _git(cpath, "checkout", "-q", base_sha, check=False)
        rep = run_fn(task_map[pid], dict(signals), Path(cpath), engine="pipeline",
                     provider_name="openai-compatible", feature=pid, execute=True, author=True, review=True)
        clones[pid] = {"path": str(cpath), "branch": f"ai-ops/{pid}"}
        res = package_result_from_rep(rep)
        res["clone"] = str(cpath)
        return res
    return runner


def make_isolated_integration_runner(child_root, base_sha, clones, integration_branch="ai-ops/integration"):
    """v3.8.3: integration-КЛОН от base; fetch веток пакетов ИЗ их клонов (по пути) + merge; stack-aware
    aggregate (project_detector+evidence_collector) на НОВОМ integration-SHA. fail-closed при сбое."""
    def runner(results):
        iroot = (clones.get("_integration") or {}).get("path")
        _git(iroot, "checkout", "-q", "-B", integration_branch, base_sha, check=False)
        conflicts = 0
        for pid in results:
            c = clones.get(pid)
            if not c:
                conflicts += 1; continue
            _git(iroot, "fetch", "-q", c["path"], f"{c['branch']}:{c['branch']}", check=False)
            m = _git(iroot, "merge", "--no-edit", "--no-ff", c["branch"], check=False)
            if m.returncode != 0:
                conflicts += 1; _git(iroot, "merge", "--abort", check=False)
        integration_sha = _git(iroot, "rev-parse", "HEAD").stdout.strip()
        try:
            import project_detector as _pd, evidence_collector as _ec, tool_broker as _tb
            _coll = _ec.collect(_pd.detect(iroot), iroot, _tb.sandbox_policy(child_root=str(iroot)))
            _iv = (_coll.get("gate_evidence") or {}).get("implementation_verification") or {}
            stack_ok = _iv.get("status") == "pass"
            stack_checks = {k: (v.get("status") if isinstance(v, dict) else v) for k, v in (_coll.get("checks") or {}).items()}
        except Exception as _e:  # noqa: BLE001
            stack_ok = False; stack_checks = {"error": f"{type(_e).__name__}: {_e}"[:160]}
        all_pass = conflicts == 0 and stack_ok
        return integration_sha, {"all_pass": all_pass, "tested_revision": integration_sha, "conflicts": conflicts,
                                 "stack_aware": True, "stack_checks": stack_checks,
                                 "isolation": "per-package-clone"}, conflicts, False
    return runner


def run_live_concurrent(wg, child_root, base_sha, task_map, signals, run_fn, clones_dir,
                        open_pr=False, repo_slug=None, integration_branch="ai-ops/integration", max_parallel=None):
    """v3.8.3 НАСТОЯЩИЙ concurrent parallel-2: отдельный disposable-клон+ветка+прогон на пакет, КОНКУРЕНТНО;
    integration-клон -> fetch package-ветки -> merge -> stack-aware aggregate -> ОДИН PR. Честные поля:
    execution_concurrency=concurrent, isolation=per-package-clone. Основной checkout НЕ трогается."""
    clones = {}
    iroot = Path(clones_dir) / "_integration"
    subprocess.run(["git", "clone", "-q", str(child_root), str(iroot)], capture_output=True, text=True)
    clones["_integration"] = {"path": str(iroot)}
    pr = make_isolated_package_runner(child_root, base_sha, task_map, signals, run_fn, clones_dir, clones)
    ir = make_isolated_integration_runner(child_root, base_sha, clones, integration_branch)
    n = max_parallel or min(len(wg.get("packages", []) or [1]), getattr(pe.pp, "MAX_PARALLEL", 2))
    rec = pe.execute_parallel(wg, pr, ir, contract_shas=None, max_parallel=max(2, n))
    rec["execution_concurrency"] = "concurrent"
    rec["isolation"] = "per-package-clone"
    rec["parallel_safe"] = True
    rec["fan_in"] = "live"
    rec["pr"] = None
    if open_pr and rec.get("delivery", {}).get("open_pr") and repo_slug:
        _git(iroot, "push", "-f", "-q", "origin", integration_branch, check=False)
        title = f"[parallel-2 concurrent] {wg.get('id')} fan-in @ {rec['integration_sha'][:12]}"
        body = (f"Concurrent parallel-2 (per-package clones) fan-in @ {rec['integration_sha'][:12]}.\n"
                f"Пакеты: {', '.join(task_map)}. stack-aware aggregate на integration-SHA.\n\n"
                "🤖 Generated with [Claude Code](https://claude.com/claude-code)")
        p = subprocess.run(["gh", "pr", "create", "--repo", repo_slug, "--draft", "--head", integration_branch,
                            "--base", "main", "--title", title, "--body", body], cwd=str(iroot), capture_output=True, text=True)
        rec["pr"] = (p.stdout.strip() or p.stderr.strip())[:300]
    return rec


def selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    # package_result_from_rep — чистое отображение
    expect("rep ready -> pass + sha", package_result_from_rep(
        {"ready_for_pr": True, "commit": {"sha": "a" * 40}})["status"] == "pass")
    expect("rep not-ready -> fail", package_result_from_rep(
        {"ready_for_pr": False, "commit": {"sha": "b" * 40}})["status"] == "fail")
    expect("rep не dict -> error", package_result_from_rep(None)["status"] == "error")

    # оркестрация с МОК-раннерами (без git/LLM): 2 parallel-safe пакета -> fan-in -> open_pr
    wg = {"schema_version": 1, "kind": "WorkGraph", "id": "WG-T", "feature": "f", "execution_mode": "hybrid",
          "packages": [{"id": "api", "depends_on": [], "write_scope": ["a/**"]},
                       {"id": "ui", "depends_on": [], "write_scope": ["b/**"]}]}
    good = {"api": None, "ui": None}

    def fake_run(task, sig, root, **kw):
        return {"ready_for_pr": True, "commit": {"sha": kw["feature"].ljust(40, "0")}}

    # инъекция мок-integration_runner через прямой execute_parallel
    def pr_runner(pkg):
        return package_result_from_rep(fake_run(None, None, None, feature=pkg["id"]))

    def ir_runner(results):
        return ("c" * 40, {"all_pass": True, "tested_revision": "c" * 40}, 0, False)

    rec = pe.execute_parallel(wg, pr_runner, ir_runner, contract_shas=None, max_parallel=1)
    expect("2 parallel-safe пакета зелены -> fan-in proceed + open_pr",
           rec["proceed"] and rec["delivery"]["open_pr"] and rec["integration_sha"] == "c" * 40)

    def ir_conflict(results):
        return ("d" * 40, {"all_pass": False, "tested_revision": "d" * 40}, 1, False)
    rec2 = pe.execute_parallel(wg, pr_runner, ir_conflict, contract_shas=None, max_parallel=1)
    expect("конфликт при fan-in -> НЕ open_pr (integration не зелёный)", rec2["delivery"]["open_pr"] is False)

    def pr_fail(pkg):
        return {"status": "fail", "sha": None, "gate_report": {"all_pass": False}}
    rec3 = pe.execute_parallel(wg, pr_fail, ir_runner, contract_shas=None, max_parallel=1)
    expect("пакет не pass -> fan-in НЕ начинается (pre-fan-in блок)",
           rec3["delivery"]["open_pr"] is False and rec3["stage"] == "pre-fan-in")

    # v3.7.1 (#2) preflight disposable: грязный checkout -> отказ (runner уничтожил бы правки)
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        _git(td, "init", "-q", check=False)
        _git(td, "config", "user.email", "t@t"); _git(td, "config", "user.name", "t")
        (Path(td) / "a.py").write_text("x=1\n", encoding="utf-8")
        _git(td, "add", "-A"); _git(td, "commit", "-qm", "init", check=False)
        okp, _ = preflight_disposable(td)
        expect("preflight: чистый checkout -> ok", okp is True)
        (Path(td) / "dirty.py").write_text("y=2\n", encoding="utf-8")
        okp2, rsn = preflight_disposable(td)
        expect("preflight: грязный checkout -> ОТКАЗ (защита незакоммиченных)", okp2 is False and "грязный" in rsn)

    # v3.8.2 STACK-AWARE integration runner: aggregate детектит стек и гоняет evidence_collector,
    # а НЕ хардкодит pytest. На python-репо -> stack_checks несёт 'test'; зелёный тест -> all_pass.
    # ГАРД (урок: CI-quality имеет ТОЛЬКО pyyaml, без pytest): all_pass-часть только при наличии pytest;
    # структурная часть (stack_aware, stack_checks) проверяется всегда.
    import importlib.util as _ilu
    _has_pytest = _ilu.find_spec("pytest") is not None
    with tempfile.TemporaryDirectory() as td2:
        _git(td2, "init", "-q", check=False)
        _git(td2, "config", "user.email", "t@t"); _git(td2, "config", "user.name", "t")
        (Path(td2) / "pyproject.toml").write_text(
            "[project]\nname='t'\nversion='0.1.0'\n[tool.pytest.ini_options]\npythonpath=['.']\n", encoding="utf-8")
        Path(td2, "tests").mkdir()
        (Path(td2) / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
        _git(td2, "add", "-A"); _git(td2, "commit", "-qm", "seed", check=False)
        base2 = _git(td2, "rev-parse", "HEAD").stdout.strip()
        # пакет p1: добавляет файл на своей ветке
        _git(td2, "checkout", "-q", "-b", "ai-ops/p1", check=False)
        (Path(td2) / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
        _git(td2, "add", "-A"); _git(td2, "commit", "-qm", "p1", check=False)
        _git(td2, "checkout", "-q", base2, check=False)
        ir = make_integration_runner(td2, base2, integration_branch="ai-ops/it-test")
        _isha, _agg, _conf, _bm = ir({"p1": {"status": "pass"}})
        expect("v3.8.2: aggregate STACK-AWARE (не хардкод pytest)", _agg.get("stack_aware") is True)
        expect("v3.8.2: stack_checks несёт проверку 'test' детектированного стека", "test" in (_agg.get("stack_checks") or {}))
        if _has_pytest:
            expect("v3.8.2: зелёный python-стек на integration-SHA -> all_pass", _agg.get("all_pass") is True and _conf == 0)
        else:
            expect("v3.8.2: без pytest в env — структура stack-aware цела (all_pass не проверяем)", _conf == 0)

    # v3.8.3 TRUE CONCURRENT: отдельный клон+ветка на пакет (конкурентно) -> integration-клон fetch+merge.
    with tempfile.TemporaryDirectory() as td3, tempfile.TemporaryDirectory() as cdir:
        _git(td3, "init", "-q", check=False)
        _git(td3, "config", "user.email", "t@t"); _git(td3, "config", "user.name", "t")
        (Path(td3) / "pyproject.toml").write_text(
            "[project]\nname='t'\nversion='0.1.0'\n[tool.pytest.ini_options]\npythonpath=['.']\n", encoding="utf-8")
        Path(td3, "tests").mkdir()
        (Path(td3) / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
        _git(td3, "add", "-A"); _git(td3, "commit", "-qm", "seed", check=False)
        base3 = _git(td3, "rev-parse", "HEAD").stdout.strip()

        def commit_run(task, sig, root, **kw):  # мок вместо LLM: пишет файл + коммитит в СВОЙ клон
            pid = kw["feature"]
            _git(root, "checkout", "-q", "-B", f"ai-ops/{pid}", check=False)
            (Path(root) / f"{pid}.py").write_text(f"def {pid}():\n    return 1\n", encoding="utf-8")
            _git(root, "add", "-A"); _git(root, "commit", "-qm", f"pkg {pid}", check=False)
            return {"ready_for_pr": True, "commit": {"sha": _git(root, "rev-parse", "HEAD").stdout.strip()}}

        wg3 = {"schema_version": 1, "kind": "WorkGraph", "id": "WG-C", "feature": "f", "execution_mode": "hybrid",
               "packages": [{"id": "aa", "depends_on": [], "write_scope": ["aa.py"]},
                            {"id": "bb", "depends_on": [], "write_scope": ["bb.py"]}]}
        rec_c = run_live_concurrent(wg3, td3, base3, {"aa": "t", "bb": "t"}, {"task_type": "QUICK"},
                                    commit_run, cdir, open_pr=False)
        expect("v3.8.3: execution_concurrency=concurrent + isolation=per-package-clone",
               rec_c.get("execution_concurrency") == "concurrent" and rec_c.get("isolation") == "per-package-clone")
        expect("v3.8.3: отдельные клоны на пакет созданы (aa, bb, _integration)",
               all((Path(cdir) / p).is_dir() for p in ("aa", "bb", "_integration")))
        agg_c = rec_c.get("aggregate") or {}
        expect("v3.8.3: fan-in слил обе ветки без конфликта (disjoint scope)", agg_c.get("conflicts") == 0)
        if _has_pytest:
            expect("v3.8.3: concurrent fan-in зелёный -> proceed + open_pr",
                   rec_c.get("proceed") is True and rec_c.get("delivery", {}).get("open_pr") is True)
        else:
            expect("v3.8.3: без pytest — структура concurrent fan-in цела", agg_c.get("stack_aware") is True)

    print("parallel_live selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
