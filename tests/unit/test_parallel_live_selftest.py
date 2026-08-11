"""Селфтест parallel_live, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from parallel_live import (  # noqa: F401 — имена, которые использует тело
    Path,
    _ensure_identity,
    _git,
    _glob_match,
    _pkg_signals,
    _scope_ok,
    make_integration_runner,
    make_isolated_package_runner,
    package_result_from_rep,
    pe,
    preflight_disposable,
    run_live_concurrent,
    subprocess,
)


@pytest.mark.slow
def test_parallel_live_selftest():
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
            # git clone НЕ копирует локальный user.name/email -> в CI (без глобальной идентичности)
            # коммит бы молча падал. Реальный путь (ai_ops_run) настраивает идентичность сам; мок — тоже.
            _git(root, "config", "user.email", "t@t"); _git(root, "config", "user.name", "t")
            _git(root, "checkout", "-q", "-B", f"ai-ops/{pid}", check=False)
            (Path(root) / f"{pid}.py").write_text(f"def {pid}():\n    return 1\n", encoding="utf-8")
            _git(root, "add", "-A"); _git(root, "commit", "-qm", f"pkg {pid}", check=False)
            return {"ready_for_pr": True, "commit": {"sha": _git(root, "rev-parse", "HEAD").stdout.strip()}}

        wg3 = {"schema_version": 1, "kind": "WorkGraph", "id": "WG-C", "feature": "f", "execution_mode": "hybrid",
               "packages": [{"id": "aa", "depends_on": [], "write_scope": ["aa.py"]},
                            {"id": "bb", "depends_on": [], "write_scope": ["bb.py"]}]}
        rec_c = run_live_concurrent(wg3, td3, base3, {"aa": "t", "bb": "t"}, {"task_type": "QUICK"},
                                    commit_run, cdir)
        expect("v3.8.3: execution_concurrency=concurrent + isolation=per-package-clone",
               rec_c.get("execution_concurrency") == "concurrent" and rec_c.get("isolation") == "per-package-clone")
        expect("v3.8.3: отдельные клоны на пакет созданы (aa, bb, _integration)",
               all((Path(cdir) / p).is_dir() for p in ("aa", "bb", "_integration")))
        agg_c = rec_c.get("aggregate") or {}
        expect("v3.8.3: fan-in слил обе ветки без конфликта (disjoint scope)", agg_c.get("conflicts") == 0)
        # v3.8.3-rc2 #5/#5b: parallel_live НЕ пушит сам -> DeliveryPlan для controller'а; несёт github_remote
        dp = rec_c.get("delivery_plan") or {}
        expect("rc2 #5: возвращён DeliveryPlan (parallel_live не владеет доставкой, нет прямого push)",
               dp.get("kind") == "DeliveryPlan" and "github_remote" in dp and rec_c.get("pr") is None)
        if _has_pytest:
            expect("v3.8.3: concurrent fan-in зелёный -> proceed + open_pr",
                   rec_c.get("proceed") is True and rec_c.get("delivery", {}).get("open_pr") is True)
            expect("rc2 #5: зелёный aggregate -> DeliveryPlan.ready=True с integration_sha",
                   dp.get("ready") is True and bool(dp.get("integration_sha")))
        else:
            expect("v3.8.3: без pytest — структура concurrent fan-in цела", agg_c.get("stack_aware") is True)

        # v3.8.3-rc2 #2 POST-COMMIT SCOPE: пакет пишет ФАЙЛ ВНЕ своего write_scope -> пакет FAIL (не в fan-in).
        def rogue_run(task, sig, root, **kw):  # мок ai_ops_run: коммит в ВЛОЖЕННУЮ ветку, HEAD клона -> base
            pid = kw["feature"]
            _git(root, "config", "user.email", "t@t"); _git(root, "config", "user.name", "t")
            _git(root, "checkout", "-q", "-B", f"ai-ops/{pid}", check=False)
            (Path(root) / "OUTSIDE_scope.py").write_text("x=1\n", encoding="utf-8")  # не совпадает с cc.py
            _git(root, "add", "-A"); _git(root, "commit", "-qm", f"rogue {pid}", check=False)
            _sha = _git(root, "rev-parse", "HEAD").stdout.strip()
            _git(root, "checkout", "-q", base3, check=False)   # клон HEAD обратно на base (как оставляет ai_ops_run)
            return {"ready_for_pr": True, "commit": {"sha": _sha}}   # #2-fix guard: чек ОБЯЗАН читать этот sha, не HEAD
        with tempfile.TemporaryDirectory() as cdir2:
            _rrunner = make_isolated_package_runner(td3, base3, {"cc": "t"}, {"task_type": "QUICK"},
                                                    rogue_run, cdir2, {})
            _rres = _rrunner({"id": "cc", "write_scope": ["cc.py"]})
            expect("rc2 #2: запись вне write_scope -> пакет FAIL (scope-violation)",
                   _rres.get("status") == "fail" and "OUTSIDE_scope.py" in (_rres.get("scope_violation") or []))
        with tempfile.TemporaryDirectory() as cdir3:
            _grunner = make_isolated_package_runner(td3, base3, {"cc": "t"}, {"task_type": "QUICK"},
                                                    commit_run, cdir3, {})
            _gres = _grunner({"id": "cc", "write_scope": ["cc.py"]})
            expect("rc2 #2: запись В пределах write_scope -> пакет проходит scope-check",
                   (_gres.get("scope_check") or {}).get("ok") is True)

    # v3.8.3-rc2c: КЛОН НЕ НАСЛЕДУЕТ ИДЕНТИЧНОСТЬ. Окружение без ГЛОБАЛЬНОЙ идентичности (CI-раннер,
    # чистый контейнер) роняло merge-коммит fan-in, и он считался КОНФЛИКТОМ пакетов — ложный негатив.
    # Проверяем оба края: нет идентичности -> fallback + коммит проходит; своя есть -> НЕ подменяем.
    import os as _os
    with tempfile.TemporaryDirectory() as tdi:
        src = Path(tdi) / "src"; src.mkdir()
        _git(src, "init", "-q", check=False)
        _git(src, "config", "user.email", "own@t"); _git(src, "config", "user.name", "own")
        (src / "f.py").write_text("x=1\n", encoding="utf-8")
        _git(src, "add", "-A"); _git(src, "commit", "-qm", "seed", check=False)
        cl = Path(tdi) / "clone"
        subprocess.run(["git", "clone", "-q", str(src), str(cl)], capture_output=True, text=True)
        _saved = {k: _os.environ.get(k) for k in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM")}
        try:  # имитируем окружение БЕЗ глобальной идентичности (как CI-раннер)
            _os.environ["GIT_CONFIG_GLOBAL"] = _os.devnull
            _os.environ["GIT_CONFIG_SYSTEM"] = _os.devnull
            # Кросс-платформенно: на Linux-раннере без идентичности `git var GIT_COMMITTER_IDENT` падает ->
            # ставится fallback; на macOS git СИНТЕЗИРУЕТ identity из OS (user@host) -> fallback не нужен.
            # Инвариант _ensure_identity на ОБОИХ: fallback ровно тогда, когда identity неразрешима, и после
            # вызова коммит в клоне проходит (это и снимает ложный конфликт fan-in).
            _resolvable = subprocess.run(["git", "-C", str(cl), "var", "GIT_COMMITTER_IDENT"],
                                         capture_output=True, text=True).returncode == 0
            expect("rc2c: fallback ставится РОВНО когда идентичность неразрешима (кросс-платформенно)",
                   _ensure_identity(cl) is (not _resolvable))
            (cl / "g.py").write_text("y=2\n", encoding="utf-8")
            _git(cl, "add", "-A")
            expect("rc2c: после _ensure_identity коммит в клоне проходит (не ложный конфликт fan-in)",
                   _git(cl, "commit", "-qm", "c", check=False).returncode == 0)
            expect("rc2c: своя идентичность НЕ подменяется", _ensure_identity(src) is False
                   and _git(src, "config", "user.email").stdout.strip() == "own@t")
        finally:
            for _k, _v in _saved.items():
                _os.environ.pop(_k, None) if _v is None else _os.environ.__setitem__(_k, _v)

    # v3.8.3-rc2 unit: helpers (#1 pkg signals, glob/scope, #8 self-clean каталог)
    expect("rc2 #1: _pkg_signals прокидывает write_scope+выводит affected_areas",
           _pkg_signals({"task_type": "X"}, {"id": "p", "write_scope": ["api/**", "db/x.py"]}).get("affected_areas") == ["api", "db"])
    expect("rc2: _glob_match 'api/**' ловит вложенный путь", _glob_match("api/routes/x.py", "api/**") and not _glob_match("ui/x.py", "api/**"))
    expect("rc2 #2: _scope_ok пропускает инфра-пути (.ai/…), ловит чужие",
           _scope_ok([".ai/plan.yaml", "api/x.py", "ui/y.py"], ["api/**"]) == (False, ["ui/y.py"]))
    expect("rc3: _scope_ok освобождает build-артефакты (egg-info/кэш/lock), не считает нарушением",
           _scope_ok(["calc.py", "tasks.egg-info/PKG-INFO", "__pycache__/x.pyc", "package-lock.json"],
                     ["calc.py"]) == (True, [])
           and _scope_ok(["calc.py", "tasks.egg-info/PKG-INFO", "rogue.py"], ["calc.py"]) == (False, ["rogue.py"]))
    with tempfile.TemporaryDirectory() as td4:  # #8: self-created clones_dir очищается (нет утечки)
        _git(td4, "init", "-q", check=False); _git(td4, "config", "user.email", "t@t"); _git(td4, "config", "user.name", "t")
        (Path(td4) / "s.py").write_text("x=1\n", encoding="utf-8"); _git(td4, "add", "-A"); _git(td4, "commit", "-qm", "s", check=False)
        _b4 = _git(td4, "rev-parse", "HEAD").stdout.strip()
        _pre = set(Path(tempfile.gettempdir()).glob("ai-ops-parallel-*"))
        run_live_concurrent({"schema_version": 1, "kind": "WorkGraph", "id": "WG-X", "feature": "f",
                             "execution_mode": "hybrid", "packages": [{"id": "z", "depends_on": [], "write_scope": ["z.py"]}]},
                            td4, _b4, {"z": "t"}, {"task_type": "QUICK"}, commit_run)  # clones_dir=None -> self-created
        _post = set(Path(tempfile.gettempdir()).glob("ai-ops-parallel-*"))
        expect("rc2 #8: self-created каталог клонов очищен (нет утечки временных клонов)", _post == _pre)

    assert ok, "перенесённый селфтест parallel_live: см. строки FAIL в выводе"
