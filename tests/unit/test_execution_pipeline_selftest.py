"""Селфтест execution_pipeline, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from execution_pipeline import (  # noqa: F401 — имена, которые использует тело
    Path,
    _baseline_failure_summary,
    _change_context,
    _change_context_range,
    _committed_changed_files,
    _diff_checks,
    _env_proven_ok,
    _env_unqualified,
    _failure_ids,
    _failure_signal,
    _git,
    _has_changes,
    _human_approval_domains_uncovered,
    _install_dependencies,
    _parse_yaml_block,
    _resolve_base,
    _reviewable_gates,
    _run_authoring,
    _security_verdict_errors,
    _tree_clean,
    _tree_clean_after_checks,
    _untracked,
    _verify_remote_base,
    os,
    run_pipeline,
    tool_broker,
)


@pytest.mark.slow
def test_execution_pipeline_selftest():
    import tempfile
    import subprocess
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        subprocess.run(["git", "-C", td, "init", "-q"])
        subprocess.run(["git", "-C", td, "config", "user.email", "t@t"])
        subprocess.run(["git", "-C", td, "config", "user.name", "t"])
        (root / "src").mkdir()
        # python-профиль БЕЗ тулчейна (нет ruff/mypy/pytest, нет tests/) -> все проверки
        # not_applicable детерминированно (не зависим от наличия pytest в среде selftest).
        (root / "pyproject.toml").write_text(
            "[tool.poetry]\nname='x'\n[tool.poetry.dependencies]\n", encoding="utf-8")
        (root / "f").write_text("x", encoding="utf-8")
        subprocess.run(["git", "-C", td, "add", "-A"]); subprocess.run(["git", "-C", td, "commit", "-q", "-m", "i"])

        # mock-предложитель: пишет файл в scope, читает его, done
        script = [
            {"op": "write", "path": "src/add.py", "content": "def add(a,b): return a+b\n"},
            {"op": "read", "path": "src/add.py"},
            {"done": True, "summary": "добавил add"},
        ]
        it = iter(script)
        pol = tool_broker.Policy(level="execution", write_scope=["src/"])
        sig = {"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]}
        rep = run_pipeline("добавить функцию add", sig, root, lambda c: next(it),
                           policy=pol, budget={"max_model_calls": 10}, feature="add-fn")

        expect("pipeline: петля дошла до done", rep["loop"]["stopped"] == "done")
        expect("pipeline: изменение применено (write)", rep["loop"]["applied_writes"] == 1
               and (root / "src" / "add.py").exists())
        expect("pipeline: профиль определил python", "python" in rep["profile"]["stacks"])
        expect("pipeline: evidence-проверки собраны", isinstance(rep["checks"], dict) and rep["checks"])
        expect("pipeline: гейты RunPlan оценены (есть вердикт blocked)",
               "blocked" in rep["gates"] and isinstance(rep["gates"]["evaluated"], list))
        expect("pipeline: intake_completeness закрыт evidence из сигналов (finding живого прогона)",
               "intake_completeness" not in rep["gates"]["unmet"])
        expect("pipeline: workitem привязан к именованной фиче", rep["workitem_id"] == "add-fn")
        expect("pipeline: честный not_yet (commit/PR/живой)", len(rep["not_yet"]) == 3)
        # P0.5: dry-run (commit=False) НИКОГДА не ready_for_pr — нет ревизии для draft PR
        expect("P0.5: commit=False -> ready_for_pr всегда False", rep["ready_for_pr"] is False)

        # v2.59 (finding аудита): commit=True -> изменения на рабочей ветке, evidence на ТОЧНОМ SHA
        _, orig_branch, _ = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
        it_c = iter([
            {"op": "write", "path": "src/mul.py", "content": "def mul(a,b): return a*b\n"},
            {"done": True, "summary": "mul"},
        ])
        rep_c = run_pipeline("добавить mul", sig, root, lambda c: next(it_c),
                             policy=pol, budget={"max_model_calls": 10}, feature="mul-fn", commit=True)
        expect("commit: создан коммит на рабочей ветке (не main)",
               rep_c["commit"]["sha"] and rep_c["commit"]["branch"] == "ai-ops/mul-fn")
        expect("commit: evidence собран на ТОЧНОМ зафиксированном SHA",
               rep_c["commit"]["evidence_on_exact_sha"] is True
               and rep_c["commit"]["evidence_revision"] == rep_c["commit"]["sha"])
        expect("commit: main не тронут (работа на ветке ai-ops/*)",
               _git(root, "rev-parse", "--abbrev-ref", "HEAD")[1] == "ai-ops/mul-fn")
        # P0.5: полный SHA (40 hex), не short; дерево чистое до/после проверок
        expect("P0.5: commit SHA полный (40 hex)",
               isinstance(rep_c["commit"]["sha"], str) and len(rep_c["commit"]["sha"]) == 40)
        expect("P0.5: дерево чистое до проверок (все правки в коммите)",
               rep_c["commit"]["tree_clean_before_checks"] is True)
        expect("P0.5: commit=True + чисто + SHA совпал -> ready_for_pr True",
               rep_c["ready_for_pr"] is True)
        # v2.121 (P1.2 п.4): recheck-after-diff присутствует в отчёте; для QUICK одобрений нет -> ok
        expect("v2.121: approval_recheck в отчёте, для QUICK пусто -> ok",
               isinstance(rep_c.get("approval_recheck"), dict) and rep_c["approval_recheck"]["ok"] is True)
        # helper: изменённые коммитом файлы извлекаются
        _chg = _committed_changed_files(root, rep_c["commit"]["sha"])
        expect("v2.121: _committed_changed_files -> src/mul.py в диффе коммита", "src/mul.py" in _chg)
        # интеграция: одобрение со scope, НЕ покрывающим изменённый путь -> recheck uncovered
        import approvals as _appr_t
        _appr_t.write_record(root, "mul-fn", "secrets", "u@x", "config/other.py", "ротация",
                             created_at="2026-07-05T00:00:00Z", binds_to="P",
                             expires_at="2027-01-01T00:00:00Z", risk="secret", source="user")
        _rc_bad = _appr_t.recheck_after_diff(root, "mul-fn", _chg, signals={"secret_boundary": True},
                                             now="2026-07-05T00:00:00Z", plan_hash="P")
        expect("v2.121: scope одобрения не покрывает изменённый путь -> uncovered",
               _rc_bad["ok"] is False and _rc_bad["uncovered"][0]["domain"] == "secrets")
        expect("умное ослабление: нет тестов -> освобождено + громкий tests_warn (allow_missing_tests)",
               "tests_passed" in rep_c["exemptions"] and rep_c["tests_warn"])
        expect("умное ослабление: implementation_verification не заблокирован из-за отсутствия тулчейна",
               "implementation_verification" not in rep_c["gates"]["unmet"])
        _git(root, "checkout", "-q", orig_branch)   # вернуться на исходную ветку

        # require_tests: allow_missing_tests=False -> отсутствие тестов БЛОКИРУЕТ (эскалация политикой)
        it_rt = iter([{"op":"write","path":"src/q.py","content":"x=1\n"}, {"done": True}])
        rep_rt = run_pipeline("нужны тесты", sig, root, lambda c: next(it_rt), policy=pol,
                              budget={"max_model_calls":5}, feature="need-tests", allow_missing_tests=False)
        expect("require_tests: отсутствие тестов блокирует implementation_verification",
               "implementation_verification" in rep_rt["gates"]["unmet"])
        _git(root, "checkout", "-q", orig_branch)

        # v2.62: isolate=True -> весь прогон в отдельном worktree, основное дерево не тронуто
        it_iso = iter([{"op":"write","path":"src/iso.py","content":"y=2\n"}, {"done": True}])
        rep_iso = run_pipeline("в изоляции", sig, root, lambda c: next(it_iso),
                               budget={"max_model_calls":5}, feature="iso-fn",
                               commit=True, isolate=True, install_deps=False)  # offline: не ставим deps
        wt_rel = rep_iso["isolation"]["worktree"]
        expect("isolate: прогон в отдельном worktree (.ai/worktrees/iso-fn)",
               wt_rel == ".ai/worktrees/iso-fn" and (root / wt_rel / "src" / "iso.py").exists())
        expect("isolate: основное дерево НЕ тронуто (нет src/iso.py в корне)",
               not (root / "src" / "iso.py").exists())
        expect("isolate: коммит на ветке ai-ops/iso-fn, evidence на точном SHA",
               rep_iso["commit"]["branch"] == "ai-ops/iso-fn"
               and rep_iso["commit"]["evidence_on_exact_sha"] is True)
        _git(root, "checkout", "-q", orig_branch)

        # P0.3 (аудит v2.79): повторный прогон того же feature с НЕсохранённым коммитом
        # прошлого прогона -> БЕЗ discard останавливается ошибкой (не теряем работу)
        it_iso2 = iter([{"op": "write", "path": "src/iso.py", "content": "y=3\n"}, {"done": True}])
        rep_iso_guard = run_pipeline("в изоляции повторно", sig, root, lambda c: next(it_iso2),
                                     budget={"max_model_calls": 5}, feature="iso-fn",
                                     commit=True, isolate=True, install_deps=False)
        # obs 2dbfc337 (поле 20.08.2026): сообщение обязано называть РЕАЛЬНУЮ команду продолжения
        # (интент `ai-ops resume`), а не внутренний `resume=True (--resume)`, которого у `ai-ops` нет.
        _err_iso = rep_iso_guard.get("error") or ""
        expect("P0.3: повторный прогон без discard -> honest error (работа не потеряна)",
               rep_iso_guard.get("status") == "error" and "ai-ops resume" in _err_iso
               and "(--resume)" not in _err_iso)
        _git(root, "checkout", "-q", orig_branch)

        # P0.3: с discard_previous=True повторный прогон перезаписывает и стартует чисто
        it_iso3 = iter([{"op": "write", "path": "src/iso.py", "content": "y=4\n"}, {"done": True}])
        rep_iso3 = run_pipeline("в изоляции c discard", sig, root, lambda c: next(it_iso3),
                                budget={"max_model_calls": 5}, feature="iso-fn",
                                commit=True, isolate=True, install_deps=False, discard_previous=True)
        expect("P0.3: discard=True -> свежий worktree, чистый старт",
               rep_iso3.get("status") != "error"
               and rep_iso3["isolation"]["worktree"] == ".ai/worktrees/iso-fn"
               and rep_iso3["commit"]["evidence_on_exact_sha"] is True)
        _git(root, "checkout", "-q", orig_branch)

        # v2.93 (finding аудита): целостность коммита — хелперы состояния файлов
        with tempfile.TemporaryDirectory() as td2:
            r2 = Path(td2)
            subprocess.run(["git", "-C", td2, "init", "-q"])
            subprocess.run(["git", "-C", td2, "config", "user.email", "t@t"])
            subprocess.run(["git", "-C", td2, "config", "user.name", "t"])
            (r2 / "a.py").write_text("x=1\n", encoding="utf-8")
            subprocess.run(["git", "-C", td2, "add", "-A"]); subprocess.run(["git", "-C", td2, "commit", "-q", "-m", "i"])
            expect("v2.93 _has_changes: чистое дерево -> нет правок", _has_changes(r2) is False)
            # правка через «shell» (прямое изменение файла, не через write-op) -> детектится
            (r2 / "a.py").write_text("x=2\n", encoding="utf-8")
            expect("v2.93 _has_changes: правка tracked-файла (как из shell) детектится", _has_changes(r2) is True)
            _git(r2, "checkout", "--", ".")
            # снимок untracked ДО подготовки; пользовательский untracked существует заранее
            (r2 / "user_note.txt").write_text("mine\n", encoding="utf-8")
            before = _untracked(r2)
            expect("v2.93 _untracked: видит пользовательский untracked", "user_note.txt" in before)
            # подготовка создаёт НОВЫЙ untracked (эмуляция package-lock.json от npm install)
            (r2 / "package-lock.json").write_text("{}\n", encoding="utf-8")
            delta = _untracked(r2) - before
            expect("v2.93 snapshot-delta: новый untracked подготовки в delta", delta == {"package-lock.json"})
            expect("v2.93 snapshot-delta: пользовательский untracked НЕ в delta (не удалим)",
                   "user_note.txt" not in delta)

        # v2.93 интеграция: правка ТОЛЬКО через shell (0 write-op) всё равно коммитится (не теряем работу)
        it_sh = iter([
            {"op": "shell", "command": "python3 -c \"open('shelledit.py','w').write('s=1\\n')\""},
            {"done": True, "summary": "через shell"},
        ])
        pol_sh = tool_broker.Policy(level="execution", write_scope=["src/"])
        rep_sh = run_pipeline("правка через shell", sig, root, lambda c: next(it_sh),
                              policy=pol_sh, budget={"max_model_calls": 5}, feature="shell-fn",
                              commit=True, isolate=True, install_deps=False)
        expect("v2.93: правка через shell (applied_writes=0) всё равно даёт коммит",
               rep_sh["loop"]["applied_writes"] == 0 and bool(rep_sh["commit"]["sha"]))
        _git(root, "checkout", "-q", orig_branch)

        # v2.108 Operational Context: context_prelude РЕАЛЬНО доходит до модели (в base_context петли).
        seen_ctx = {}
        def _capturing(c):
            seen_ctx.setdefault("first", c)
            return {"done": True}
        run_pipeline("проверка prelude", sig, root, _capturing, policy=pol,
                     budget={"max_model_calls": 3}, feature="prelude-fn", isolate=True,
                     install_deps=False, context_prelude="MARKER_CONTEXT_PAYLOAD_XYZ")
        expect("v2.108: context_prelude попал в prompt модели (base_context петли)",
               "MARKER_CONTEXT_PAYLOAD_XYZ" in (seen_ctx.get("first") or ""))
        _git(root, "checkout", "-q", orig_branch)

        # v2.109 Real Resume: первый прогон коммитит работу; resume ПРОДОЛЖАЕТ поверх неё
        # (ветка/коммит НЕ удаляются, worktree переиспользуется, resume_context доходит до модели).
        it_r1 = iter([{"op": "write", "path": "src/first.py", "content": "a=1\n"},
                      {"done": True, "summary": "фаза 1"}])
        rep_r1 = run_pipeline("resume фаза 1", sig, root, lambda c: next(it_r1),
                              budget={"max_model_calls": 5}, feature="resume-fn",
                              commit=True, isolate=True, install_deps=False)
        sha1 = (rep_r1.get("commit") or {}).get("sha")
        expect("v2.109 resume: фаза 1 закоммичена на ветке", bool(sha1))
        _git(root, "checkout", "-q", orig_branch)

        seen_r = {}
        it_r2 = iter([{"op": "write", "path": "src/second.py", "content": "b=2\n"},
                      {"done": True, "summary": "фаза 2"}])
        def _resume_prop(c):
            seen_r.setdefault("ctx", c)
            return next(it_r2)
        rep_r2 = run_pipeline("resume фаза 2", sig, root, _resume_prop,
                              budget={"max_model_calls": 5}, feature="resume-fn",
                              commit=True, isolate=True, install_deps=False,
                              resume=True, resume_context="MARKER_RESUME_STATE_ABC")
        rinfo = rep_r2.get("resume") or {}
        expect("v2.109 resume: НЕ ошибка про несохранённые коммиты (продолжаем, а не падаем)",
               rep_r2.get("status") != "error")
        expect("v2.109 resume: resumed=True + ветка переиспользована (работа не потеряна)",
               rinfo.get("resumed") is True and rinfo.get("reused_branch") is True)
        expect("v2.109 resume: resume_context РЕАЛЬНО в prompt модели",
               "MARKER_RESUME_STATE_ABC" in (seen_r.get("ctx") or ""))
        wt_r = root / ".ai" / "worktrees" / "resume-fn"
        expect("v2.109 resume: работа фазы 1 сохранена в worktree (продолжили поверх, не с нуля)",
               (wt_r / "src" / "first.py").exists() and (wt_r / "src" / "second.py").exists())
        _git(root, "checkout", "-q", orig_branch)

        # v2.109 resume: нечего продолжать (нет ветки) -> честный fresh, resumed=False + причина
        it_r3 = iter([{"op": "write", "path": "src/n.py", "content": "n=1\n"}, {"done": True}])
        rep_r3 = run_pipeline("resume без прошлого", sig, root, lambda c: next(it_r3),
                              budget={"max_model_calls": 5}, feature="resume-none",
                              commit=True, isolate=True, install_deps=False, resume=True)
        rinfo3 = rep_r3.get("resume") or {}
        expect("v2.109 resume: нет прошлого прогона -> честный fresh (resumed=False + причина)",
               rinfo3.get("resumed") is False and bool(rinfo3.get("reason"))
               and rep_r3.get("status") != "error")
        _git(root, "checkout", "-q", orig_branch)

        # v2.110 Real Spec-First: неполный spec.yaml для WorkItem -> «не пускает в implementation»
        import spec_levels as _sl_t
        sig_sf = {"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]}
        _sl_t.create_spec(root, "spec-fn", sig_sf)   # все разделы missing (неполон)
        it_sf = iter([{"op": "write", "path": "src/sf.py", "content": "s=1\n"}, {"done": True}])
        rep_sf = run_pipeline("spec-first блок", sig_sf, root, lambda c: next(it_sf),
                              budget={"max_model_calls": 5}, feature="spec-fn",
                              commit=True, isolate=True, install_deps=False, baseline_diff=True)
        expect("v2.110 spec-first: неполный spec.yaml -> ready_for_pr=False + incomplete_sections",
               rep_sf.get("ready_for_pr") is False
               and rep_sf["spec_first"]["ok"] is False and rep_sf["spec_first"]["incomplete_sections"])
        _git(root, "checkout", "-q", orig_branch)

        # заполнить spec.yaml -> spec-first больше НЕ блокирует (проверяем именно спек-гейт)
        import yaml as _yaml_t
        _sp = root / "features" / "spec-fn2" / "spec.yaml"
        _sp.parent.mkdir(parents=True, exist_ok=True)
        _full_secs = {s: {"status": "complete", "content": "x"} for s in _sl_t.required_sections(0)}
        _sp.write_text(_yaml_t.safe_dump({"schema_version": 1, "kind": "spec", "workitem_id": "spec-fn2",
                                          "level": 0, "sections": _full_secs}), encoding="utf-8")
        it_sf2 = iter([{"op": "write", "path": "src/sf2.py", "content": "s=2\n"}, {"done": True}])
        rep_sf2 = run_pipeline("spec-first полон", sig_sf, root, lambda c: next(it_sf2),
                               budget={"max_model_calls": 5}, feature="spec-fn2",
                               commit=True, isolate=True, install_deps=False, baseline_diff=True)
        expect("v2.110 spec-first: полный spec.yaml -> спек-гейт не блокирует (ok=True)",
               rep_sf2["spec_first"]["ok"] is True and not rep_sf2["spec_first"]["incomplete_sections"])
        _git(root, "checkout", "-q", orig_branch)

        # v2.118 (finding живого прогона): провал install при ПРОШЕДШИХ проверках не блокирует ready
        expect("v2.118 env: проверки прошли (test=pass) -> окружение квалифицировано, install-провал не в счёт",
               _env_unqualified({"test": {"status": "pass"}, "build": {"status": "not_run"}}) is False)
        expect("v2.118 env: exit 127 в упавшей проверке -> окружение НЕ квалифицировано (блок сохраняется)",
               _env_unqualified({"test": {"status": "fail", "runs": [{"ok": False, "exit_code": 127}]}}) is True)
        expect("v2.118 env: 'No module named' в выводе -> окружение НЕ квалифицировано",
               _env_unqualified({"test": {"status": "fail",
                                          "runs": [{"ok": False, "exit_code": 1,
                                                    "output_tail": "ModuleNotFoundError: No module named 'foo'"}]}}) is True)
        expect("v2.118 env: честный fail проверки (exit 1, код сломан) -> НЕ считается env-провалом",
               _env_unqualified({"test": {"status": "fail",
                                          "runs": [{"ok": False, "exit_code": 1,
                                                    "output_tail": "AssertionError: 2 != 3"}]}}) is False)
        # v2.121 (P1.4): install-провал НЕ прощается без доказательства — нет запущенных проверок ->
        # окружение НЕ доказано (раньше _env_unqualified возвращал False при пустых checks — дыра)
        expect("v2.121 env: проверок не запускалось -> окружение НЕ доказано (proven_ok=False)",
               _env_proven_ok({}) is False and _env_proven_ok({"build": {"status": "not_run"},
                                                               "test": {"status": "not_run"}}) is False)
        expect("v2.121 env: хотя бы одна pass -> доказано; только env-симптомы -> НЕ доказано",
               _env_proven_ok({"test": {"status": "pass"}}) is True
               and _env_proven_ok({"test": {"status": "fail", "runs": [{"ok": False, "exit_code": 127}]}}) is False)

        # v2.119 (finding живого прогона): тул-кэши (untracked) не делают дерево «грязным после проверок»
        with tempfile.TemporaryDirectory() as tdc:
            rc = Path(tdc)
            _git(rc, "init", "-q"); _git(rc, "config", "user.email", "t@t"); _git(rc, "config", "user.name", "t")
            (rc / "m.py").write_text("x=1\n", encoding="utf-8")
            _git(rc, "add", "-A"); _git(rc, "commit", "-q", "-m", "i")
            expect("v2.119 tree: чистое дерево -> clean", _tree_clean_after_checks(rc) is True)
            # pytest/npm кэши как untracked -> терпимо (после проверок)
            (rc / "__pycache__").mkdir(); (rc / "__pycache__" / "m.cpython-311.pyc").write_text("x", encoding="utf-8")
            (rc / ".pytest_cache").mkdir(); (rc / ".pytest_cache" / "v").write_text("x", encoding="utf-8")
            (rc / "node_modules").mkdir(); (rc / "node_modules" / "pkg.js").write_text("x", encoding="utf-8")
            expect("v2.119 tree: только тул-кэши (untracked) -> дерево считается чистым (не блок)",
                   _tree_clean_after_checks(rc) is True and _tree_clean(rc) is False)
            # НЕ-кэш untracked файл -> грязь (не прячем реальные артефакты)
            (rc / "leftover.txt").write_text("real", encoding="utf-8")
            expect("v2.119 tree: НЕ-кэш untracked (leftover.txt) -> дерево грязное (честно)",
                   _tree_clean_after_checks(rc) is False)
            (rc / "leftover.txt").unlink()
            # модификация TRACKED файла проверками -> грязь (evidence-целостность сохранена)
            (rc / "m.py").write_text("x=2\n", encoding="utf-8")
            expect("v2.119 tree: правка TRACKED файла проверками -> дерево грязное (P0.5 сохранён)",
                   _tree_clean_after_checks(rc) is False)

        # v2.95: security-скан ловит секрет в изменениях -> гейт security блокирует с деталями
        # (ENGINEERING-план содержит security). Не ложный green: секрет -> security в unmet.
        sig_eng = {"task_type": "ENGINEERING", "size": "small", "risk": "medium", "affected_areas": ["core"]}
        # Не канонический пример AWS: `AKIAIOSFODNN7EXAMPLE` — публичный образец, и
        # детектор с 19.08.2026 его не считает утечкой. Позитивной фикстуре нужен ключ,
        # похожий на настоящий.
        _aws_fx = "AKIA" + "QRSTUVWX9012YZAB"   # v3.0.4: собрано в рантайме (без статического секрет-литерала)
        it_sec = iter([{"op": "write", "path": "src/leak.py",
                        "content": f'API_KEY = "{_aws_fx}"\n'}, {"done": True}])
        rep_sec = run_pipeline("добавить конфиг", sig_eng, root, lambda c: next(it_sec),
                               policy=pol, budget={"max_model_calls": 5}, feature="sec-fn",
                               commit=True, isolate=True, install_deps=False)
        expect("v2.101: security-pack поймал секрет (домен secrets в blocking)",
               rep_sec.get("security_scan") and "secrets" in rep_sec["security_scan"]["blocking"])
        expect("v2.101: секрет -> security блокирует (в unmet, не ложный green)",
               "security" in rep_sec["gates"]["unmet"])
        _git(root, "checkout", "-q", orig_branch)

        # v3.0.13 (блок C, тест-гэп): _security_scan_error FAIL-CLOSED. Если security pack БРОСАЕТ
        # (git-сбой/инфра), security-гейт обязан стать fail (не тихо пропасть -> ложный green). Прежде
        # эта ветка не имела ассерта. Монкипатчим run_pack на raiser.
        import security_pack as _sp_mod
        _orig_rp = _sp_mod.run_pack
        _sp_mod.run_pack = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("scan boom (git недоступен)"))
        try:
            it_se = iter([{"op": "write", "path": "src/se.py", "content": "s=1\n"}, {"done": True}])
            rep_se = run_pipeline("скан падает", sig_eng, root, lambda c: next(it_se),
                                  policy=pol, budget={"max_model_calls": 5}, feature="scanerr-fn",
                                  commit=True, isolate=True, install_deps=False)
        finally:
            _sp_mod.run_pack = _orig_rp
        expect("v3.0.13 тест-гэп: security scan бросил -> security=fail (fail-closed, не ложный green)",
               "security" in rep_se["gates"]["unmet"] and not rep_se["ready_for_pr"])
        _git(root, "checkout", "-q", orig_branch)

        # v2.125 (finding живого прогона): новая зависимость в QUICK-задаче — security pack ЗАПУСКАЕТСЯ
        # (не только когда security в плане workflow) и security ФОРСИРУЕТСЯ в оценку гейтов -> блокирует
        # без ApprovalRecord даже в QUICK (раньше новая зависимость в QUICK проскакивала).
        sig_q = {"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]}
        pol_dep = tool_broker.Policy(level="execution", block_push=True)   # без write_scope: requirements.txt в корне
        it_dep = iter([{"op": "write", "path": "requirements.txt", "content": "flask\n"}, {"done": True}])
        rep_dep = run_pipeline("добавить зависимость", sig_q, root, lambda c: next(it_dep),
                               policy=pol_dep, budget={"max_model_calls": 5}, feature="dep-fn",
                               commit=True, isolate=True, install_deps=False)
        expect("v2.125: QUICK + новая зависимость -> security pack запущен (домен dependencies)",
               rep_dep.get("security_scan") and "dependencies" in (rep_dep["security_scan"].get("needs_review") or []))
        expect("v2.125: security ФОРСИРОВАН в оценку и блокирует без ApprovalRecord даже в QUICK",
               "security" in rep_dep["gates"]["evaluated"] and "security" in rep_dep["gates"]["unmet"]
               and rep_dep["ready_for_pr"] is False)
        _git(root, "checkout", "-q", orig_branch)

        # v2.106 #1: независимый security-reviewer закрывает needs_review домены -> security НЕ в unmet.
        # Чистая (без секретов) ENGINEERING-правка + --review + mock-ревьюер pass.
        it_secrev = iter([{"op": "write", "path": "src/clean.py", "content": "def f():\n    return 1\n"},
                          {"done": True}])
        sec_reviewer = lambda c: {"kind": "reviewer-result", "status": "pass",
                                  "summary": "injection-surface чист"}  # noqa: E731
        rep_secrev = run_pipeline("чистая правка", sig_eng, root, lambda c: next(it_secrev),
                                  policy=pol, budget={"max_model_calls": 8}, feature="secrev-fn",
                                  commit=True, isolate=True, install_deps=False,
                                  review=True, reviewer_proposer=sec_reviewer)
        expect("v2.106 #1: security-reviewer pass -> security закрыт (не в unmet)",
               "security" not in rep_secrev["gates"]["unmet"])
        _git(root, "checkout", "-q", orig_branch)

        # v3.7.1 STRICT JUDGE (trust alignment): needs_review-домен rate_limiting (только security_reviewer)
        # через сигнал api_change. A/B: qualified-судья закрывает vs НЕТ судьи -> pending_human.
        sig_api = dict(sig_eng, api_change=True)
        it_q = iter([{"op": "write", "path": "src/rl_a.py", "content": "def a():\n    return 1\n"}, {"done": True}])
        rep_q = run_pipeline("api rate strict-on", sig_api, root, lambda c: next(it_q),
                             policy=pol, budget={"max_model_calls": 8}, feature="rl-q-fn",
                             commit=True, isolate=True, install_deps=False,
                             review=True, reviewer_proposer=sec_reviewer, strict_judge_qualified=True)
        _sec_a = next((g for g in rep_q["gates"].get("gate_results", []) if g.get("gate") == "security"), {})

        def _has(g, sub):
            return any(sub in b for b in (g.get("blockers") or []))
        # strict=True (qualified судья) -> reviewer-ветка: #5 pending_human-guard НЕ берётся
        expect("v3.7.3 A: qualified судья НЕ берёт #5-guard (идёт через security-reviewer)",
               not _has(_sec_a, "нет QUALIFIED security-судьи"))
        _git(root, "checkout", "-q", orig_branch)
        it_strict = iter([{"op": "write", "path": "src/rl_b.py", "content": "def b():\n    return 1\n"}, {"done": True}])
        rep_strict = run_pipeline("api rate strict-off", sig_api, root, lambda c: next(it_strict),
                                  policy=pol, budget={"max_model_calls": 8}, feature="rl-b-fn",
                                  commit=True, isolate=True, install_deps=False,
                                  review=True, reviewer_proposer=sec_reviewer, strict_judge_qualified=False)
        _sec_b = next((g for g in rep_strict["gates"].get("gate_results", []) if g.get("gate") == "security"), {})
        # strict=False (нет qualified security-судьи), нет ApprovalRecord -> security pending_human
        expect("v3.7.3 B: нет qualified судьи + нет ApprovalRecord -> security fail (pending_human)",
               "security" in rep_strict["gates"]["unmet"] and _sec_b.get("status") == "fail"
               and _has(_sec_b, "нет QUALIFIED security-судьи"))
        expect("v3.7.3 C: #5-guard даёт человеку путь закрыть (блокер называет ApprovalRecord)",
               _has(_sec_b, "ApprovalRecord"))

        # v3.8.4 RE-EVALUATE-ONLY: green-except-security ветка (QUICK+api_change, без spec-гейтов) ->
        # человек добавил ApprovalRecord -> переоценить гейты БЕЗ переавторинга (loop stopped=reevaluate-only,
        # план/SHA не меняются -> plan-bound approval валиден) -> #5-блок security снят человеком. Закрывает
        # gap: resume --execute переписывал код и инвалидировал plan-bound approvals.
        import security_pack as _sp_re, approvals as _appr_re
        sig_q = {"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["api"], "api_change": True}
        it_q1 = iter([{"op": "write", "path": "rq.py", "content": "def rq():\n    return 1\n"}, {"done": True}])
        run_pipeline("quick api sec", sig_q, root, lambda c: next(it_q1), policy=pol,
                     budget={"max_model_calls": 8}, feature="reeval-fn", commit=True, isolate=True,
                     install_deps=False, review=True, reviewer_proposer=sec_reviewer, strict_judge_qualified=False)
        # Здесь нужны ИМЕНА доменов, требующих ревью при этих signals, а не скан репозитория.
        # Прежде стоял `base=None` — то есть охват «весь репозиторий» (заявка #139); теперь охват
        # без базы — названный отказ, и правильный способ спросить домены — подать карту файлов.
        _nrq = _sp_re.run_pack(files_content={"rq.py": "def rq():\n    return 1\n"},
                               signals=sig_q).get("needs_review") or ["rate_limiting"]
        # v3.37: план кладём НА ДИСК и связываем одобрение с его настоящим хэшем. Прежде здесь стояло
        # binds_to="reeval-fn-plan" — выдуманная строка, которую никто не сверял: плана не было, и
        # проверка молча пропускала запись. То есть тест назывался «plan-bound approval валиден», а
        # привязки не существовало. Теперь она есть, и именно она проверяется.
        _rf = root / "features" / "reeval-fn"
        _rf.mkdir(parents=True, exist_ok=True)
        (_rf / "run-plan.yaml").write_text("base_workflow: QUICK\ngates: [security]\n", encoding="utf-8")
        for _d in _nrq:
            _appr_re.write_record(root, "reeval-fn", approval=_d, approved_by="human@owner",
                                  scope=f"security {_d}", reason="человек одобрил (reeval тест)",
                                  created_at="2026-07-29", expires_at="2026-12-31",
                                  risk="medium", source="human")
        rep_re = run_pipeline("quick api sec", sig_q, root, lambda c: {"done": True}, policy=pol,
                              budget={"max_model_calls": 8}, feature="reeval-fn", commit=True, isolate=True,
                              install_deps=False, review=True, reviewer_proposer=sec_reviewer,
                              strict_judge_qualified=False, reevaluate_only=True)
        _sec_re = next((g for g in rep_re["gates"].get("gate_results", []) if g.get("gate") == "security"), {})
        expect("v3.8.4 re-evaluate-only: путь БЕЗ переавторинга (loop stopped=reevaluate-only)",
               (rep_re.get("loop") or {}).get("stopped") == "reevaluate-only")
        expect("v3.8.4 re-evaluate-only: человеко-одобрение сняло #5-блок security (approval закрыл)",
               not any("нет QUALIFIED security-судьи" in b for b in (_sec_re.get("blockers") or [])))
        _git(root, "checkout", "-q", orig_branch)

        # v2.106 #1 (fail-closed): secret_boundary требует человека даже при pass ревьюера
        it_sb = iter([{"op": "write", "path": "src/sb.py", "content": "def g():\n    return 2\n"}, {"done": True}])
        rep_sb = run_pipeline("граница секретов", dict(sig_eng, secret_boundary=True), root,
                              lambda c: next(it_sb), policy=pol, budget={"max_model_calls": 8},
                              feature="sb-fn", commit=True, isolate=True, install_deps=False,
                              review=True, reviewer_proposer=sec_reviewer)
        expect("v2.106 #1: secret_boundary без human_approved -> security остаётся заблокирован",
               "security" in rep_sb["gates"]["unmet"])
        _git(root, "checkout", "-q", orig_branch)

        # v2.106 #2: spec-depth — ENGINEERING без --author -> requirements/plan незакрыты -> в spec_depth.missing
        it_sd = iter([{"op": "write", "path": "src/sd.py", "content": "x=1\n"}, {"done": True}])
        rep_sd = run_pipeline("eng без артефактов", sig_eng, root, lambda c: next(it_sd),
                              policy=pol, budget={"max_model_calls": 5}, feature="sd-fn",
                              commit=True, isolate=True, install_deps=False)
        expect("v2.106 #2: spec-depth блокирует (незакрытые разделы уровня) + в отчёте",
               rep_sd["spec_depth"]["ok"] is False and rep_sd["spec_depth"]["missing"]
               and rep_sd["ready_for_pr"] is False)
        _git(root, "checkout", "-q", orig_branch)

        # v2.106 #3: context budget overflow -> ready False + причина декомпозиции
        it_ov = iter([{"op": "write", "path": "src/ov.py", "content": "y=2\n"}, {"done": True}])
        rep_ov = run_pipeline("overflow", dict(sig, context_budget=1), root, lambda c: next(it_ov),
                              policy=pol, budget={"max_model_calls": 5}, feature="ov-fn",
                              commit=True, isolate=True, install_deps=False)
        expect("v2.106 #3: context overflow -> ready_for_pr False + причина декомпозиции",
               rep_ov["context_overflow"] is True and rep_ov["ready_for_pr"] is False
               and any("декомпоз" in n for n in rep_ov["not_yet"]))
        _git(root, "checkout", "-q", orig_branch)

        # v2.62: open_pr=True вызывает механизм draft PR; без токена -> honest unavailable
        # (токены снимаем, т.к. CI может выставлять GITHUB_TOKEN — иначе тест дёрнет сеть)
        saved = {k: os.environ.pop(k, None) for k in ("GITHUB_TOKEN", "GH_TOKEN")}
        try:
            it_pr = iter([{"op": "write", "path": "src/pr.py", "content": "z=3\n"}, {"done": True}])
            rep_pr = run_pipeline("с PR", sig, root, lambda c: next(it_pr),
                                  budget={"max_model_calls": 5}, feature="pr-fn",
                                  commit=True, isolate=True, open_pr=True, install_deps=False)
            # v3.0.16 Phase A (finding аудита #1): run_pipeline НЕ доставляет — только планирует. open_pr +
            # ready -> delivery.status='planned', delivery_plan заполнен, overall='ready-undelivered' (PR НЕ
            # открыт из pipeline). Фактическую доставку (и unavailable/delivered) выполняет контроллер.
            expect("v3.0.16 #1: run_pipeline(open_pr) НЕ открывает PR — только delivery_plan + planned",
                   rep_pr["delivery"]["status"] == "planned"
                   and rep_pr.get("draft_pr") is None
                   and isinstance(rep_pr.get("delivery_plan"), dict)
                   and rep_pr["delivery_plan"].get("ready_for_delivery") is True)
            expect("v3.0.16 #1: open_pr+ready в pipeline -> overall=ready-undelivered (доставку финализирует контроллер)",
                   rep_pr["delivery"]["requested"] is True
                   and rep_pr["overall_status"] == "ready-undelivered")
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v

        # P0.1 (аудит v2.79): baseline-diff НЕ обходит прочие блокирующие гейты. Сигнал ui_changed
        # добавляет трек VISUAL с блокирующим ux_review (без evidence) -> not ready, хоть регрессий нет.
        sig_ui = dict(sig); sig_ui["ui_changed"] = True
        it_p01 = iter([{"op": "write", "path": "src/p01.py", "content": "p=1\n"}, {"done": True}])
        rep_p01 = run_pipeline("baseline не обходит гейты", sig_ui, root, lambda c: next(it_p01),
                               policy=pol, budget={"max_model_calls": 5}, feature="p01-fn",
                               commit=True, baseline_diff=True)
        expect("P0.1: baseline-diff НЕ обходит прочие блокирующие гейты (ux_review unmet -> not ready)",
               rep_p01["gates"]["other_blocking_unmet"] and rep_p01["ready_for_pr"] is False)
        expect("P0.1: gate_results и tested_revision в отчёте (evidence/аудит)",
               isinstance(rep_p01["gates"]["gate_results"], list)
               and rep_p01["gates"]["tested_revision"] == rep_p01["commit"]["sha"])
        _git(root, "checkout", "-q", orig_branch)

        # v2.71 (finding живого прогона): _install_dependencies ставит зависимости стека перед
        # проверками. Детерминированно проверяем механизм безвредной install-командой (true).
        prof_inst = {"stacks": [{"language": "node", "install_command": "true"},
                                {"language": "python", "install_command": "true"},
                                {"language": "go", "install_command": None}]}
        prep = _install_dependencies(prof_inst, root, pol)
        expect("install: install_command выполнены (dedup, None пропущен)",
               len(prep) == 1 and prep[0]["ok"] is True and prep[0]["command"] == "true")

        # v2.72 (finding живого прогона): baseline-diff отличает регрессии от пред-существующих
        base = {"build": {"status": "pass"}, "test": {"status": "fail"}, "lint": {"status": "pass"}}
        after = {"build": {"status": "fail"}, "test": {"status": "pass"}, "lint": {"status": "pass"}}
        regr, fx = _diff_checks(base, after)
        expect("baseline-diff: build pass->fail = регрессия", regr == ["build"])
        expect("baseline-diff: test fail->pass = починка", fx == ["test"])
        expect("baseline-diff: пред-существующий fail->fail (без ухудшения) не в счёт",
               _diff_checks({"x": {"status": "fail"}}, {"x": {"status": "fail"}}) == ([], []))

        # v2.77 (finding живого прогона): fail->fail, но ХУЖЕ (1 failed -> 8 failed) = регрессия
        base_t = {"test": {"status": "fail", "runs": [{"output_tail": "Tests  1 failed | 531 passed"}]}}
        worse_t = {"test": {"status": "fail", "runs": [{"output_tail": "Tests  8 failed | 524 passed"}]}}
        same_t = {"test": {"status": "fail", "runs": [{"output_tail": "Tests  1 failed | 531 passed"}]}}
        expect("within-check: 1 failed -> 8 failed = регрессия", _diff_checks(base_t, worse_t) == (["test"], []))
        expect("within-check: 1 failed -> 1 failed (без роста) = не регрессия",
               _diff_checks(base_t, same_t) == ([], []))
        expect("failure-signal: считает 'N failed'/'N errors'",
               _failure_signal({"runs": [{"output_tail": "Found 5 errors"}]}) == 5)

        # v2.84: структурные id падений — «починил один тест, сломал другой» (1 failed -> 1 failed,
        # но ДРУГОЙ тест) счётчик пропускал; теперь новый id = регрессия.
        base_id = {"test": {"status": "fail", "runs": [{"output_tail":
                   "FAILED tests/test_a.py::test_one\n1 failed, 10 passed"}]}}
        swap_id = {"test": {"status": "fail", "runs": [{"output_tail":
                   "FAILED tests/test_b.py::test_two\n1 failed, 10 passed"}]}}
        same_id = {"test": {"status": "fail", "runs": [{"output_tail":
                   "FAILED tests/test_a.py::test_one\n1 failed, 10 passed"}]}}
        expect("structured-id: тот же счётчик, но ДРУГОЙ упавший тест = регрессия",
               _diff_checks(base_id, swap_id) == (["test"], []))
        expect("structured-id: тот же упавший тест (тот же id) = не регрессия",
               _diff_checks(base_id, same_id) == ([], []))
        expect("failure-ids: извлекает pytest FAILED node id",
               "tests/test_a.py::test_one" in _failure_ids(base_id["test"]))
        # v2.122 (finding обкатки S10): красная база — профильный узел починен, НЕ связанный
        # пред-существующий остаётся красным. Чек в целом red (fail->fail), но fixed должен быть
        # непуст на уровне node-id, а regressions — пуст (нет новых падений). Раньше fixed=[] держал
        # ложный not-ready под --require-fix на легитимном фиксе.
        s10_base = {"test": {"status": "fail", "runs": [{"output_tail":
                    "FAILED test_task.py::test_target\nFAILED test_legacy.py::test_old\n2 failed"}]}}
        s10_after = {"test": {"status": "fail", "runs": [{"output_tail":
                     "FAILED test_legacy.py::test_old\n1 failed, 1 passed"}]}}
        expect("S10 red-base: профильный узел починен, пред-существующий остался = fixed непуст, regress пуст",
               _diff_checks(s10_base, s10_after) == ([], ["test"]))
        # v3.0.15 (аудит P1, явная таблица): baseline test_a=fail,test_b=fail; after test_a=pass,test_b=fail
        # -> fixed=[test], regressions=[] (симметричный diff по structural failure-ids; красный чек НЕ
        # блокирует легитимный фикс одного узла при оставшемся старом падении). Закрыто ещё в v2.122.
        _rb_base = {"test": {"status": "fail", "runs": [{"output_tail":
                    "FAILED tests/t.py::test_a\nFAILED tests/t.py::test_b\n2 failed"}]}}
        _rb_after = {"test": {"status": "fail", "runs": [{"output_tail":
                     "FAILED tests/t.py::test_b\n1 failed, 1 passed"}]}}
        expect("v3.0.15 require_fix: {a:fail,b:fail}->{a:pass,b:fail} = fixed=[test], regressions=[]",
               _diff_checks(_rb_base, _rb_after) == ([], ["test"]))
        expect("S10 guard: непарсибельный after (build-fail без node-id) НЕ фабрикует fixed",
               _diff_checks(s10_base, {"test": {"status": "fail", "runs": [{"output_tail": "BUILD FAILED"}]}}) == ([], []))
        expect("S10 не ломает swap: починил один — сломал другой = регрессия, НЕ fixed",
               _diff_checks(base_id, swap_id) == (["test"], []))
        # стек-квалификация go: РЕАЛЬНЫЙ вывод `go test`. Раньше id схлопывался в {'FAIL'} и swap
        # (починил TestSub, сломал TestAdd в ОДНОМ пакете) не ловился -> ложный green для go-репо.
        go_sub = {"test": {"status": "fail", "runs": [{"output_tail":
                  "--- FAIL: TestSub (0.00s)\n    calc_test.go:13: Sub(5,2) = 3; want 999\nFAIL\nFAIL\tcalc\t0.002s\nFAIL"}]}}
        go_add = {"test": {"status": "fail", "runs": [{"output_tail":
                  "--- FAIL: TestAdd (0.00s)\n    calc_test.go:6: Add(2,3) = 6; want 5\nFAIL\nFAIL\tcalc\t0.003s\nFAIL"}]}}
        expect("go: извлекает имя упавшего теста (--- FAIL: TestSub)",
               "TestSub" in _failure_ids(go_sub["test"]))
        expect("go structured-id: починил TestSub, сломал TestAdd (тот же пакет) = регрессия",
               _diff_checks(go_sub, go_add) == (["test"], []))
        expect("go: тот же упавший тест, другое ВРЕМЯ прогона = НЕ регрессия",
               _diff_checks(go_sub, {"test": {"status": "fail", "runs": [{"output_tail":
                   "--- FAIL: TestSub (0.01s)\n    calc_test.go:13: Sub(5,2) = 3; want 999\nFAIL\nFAIL\tcalc\t0.009s\nFAIL"}]}}) == ([], []))
        # стек-квалификация rust: РЕАЛЬНЫЙ вывод `cargo test`. Раньше id был константой из строки
        # "error: test failed" -> swap (починил test_sub, сломал test_add) не ловился -> ложный green.
        rs_sub = {"test": {"status": "fail", "runs": [{"output_tail":
                  "thread 'tests::test_sub' (13663) panicked at src/lib.rs:10:21:\nassertion `left == right` failed\n"
                  "failures:\n    tests::test_sub\ntest result: FAILED. 1 passed; 1 failed; finished in 0.28s\n"
                  "error: test failed, to rerun pass `--lib`"}]}}
        rs_add = {"test": {"status": "fail", "runs": [{"output_tail":
                  "thread 'tests::test_add' (13999) panicked at src/lib.rs:8:21:\nassertion `left == right` failed\n"
                  "failures:\n    tests::test_add\ntest result: FAILED. 1 passed; 1 failed; finished in 0.19s\n"
                  "error: test failed, to rerun pass `--lib`"}]}}
        expect("rust: извлекает имя упавшего теста (thread 'tests::test_sub' panicked)",
               any("tests::test_sub" in i for i in _failure_ids(rs_sub["test"])))
        expect("rust structured-id: починил test_sub, сломал test_add = регрессия",
               _diff_checks(rs_sub, rs_add) == (["test"], []))
        expect("rust: тот же упавший тест (другой pid) = НЕ регрессия",
               _diff_checks(rs_sub, {"test": {"status": "fail", "runs": [{"output_tail":
                   "thread 'tests::test_sub' (55555) panicked at src/lib.rs:10:21:\nassertion `left == right` failed\n"
                   "failures:\n    tests::test_sub\ntest result: FAILED. 1 passed; 1 failed; finished in 0.30s\n"
                   "error: test failed, to rerun pass `--lib`"}]}}) == ([], []))
        # стек-квалификация java: РЕАЛЬНЫЙ вывод maven-surefire. Раньше НИ один паттерн не ловил
        # java-падение (id пустой), maven печатает "Failures: 1" (слово перед числом -> счётчик 0)
        # -> swap не ловился = ложный green. Теперь берём Class.method упавшего теста.
        jv_sub = {"test": {"status": "fail", "runs": [{"output_tail":
                  "[ERROR] CalcTest.testSub -- Time elapsed: 0.007 s <<< FAILURE!\n"
                  "org.opentest4j.AssertionFailedError: expected: <999> but was: <3>\n"
                  "[ERROR]   CalcTest.testSub:5 expected: <999> but was: <3>\n"
                  "[ERROR] Tests run: 2, Failures: 1, Errors: 0, Skipped: 0"}]}}
        jv_add = {"test": {"status": "fail", "runs": [{"output_tail":
                  "[ERROR] CalcTest.testAdd -- Time elapsed: 0.008 s <<< FAILURE!\n"
                  "org.opentest4j.AssertionFailedError: expected: <999> but was: <5>\n"
                  "[ERROR]   CalcTest.testAdd:4 expected: <999> but was: <5>\n"
                  "[ERROR] Tests run: 2, Failures: 1, Errors: 0, Skipped: 0"}]}}
        expect("java: извлекает Class.method упавшего теста (CalcTest.testSub)",
               any("CalcTest.testSub" in i for i in _failure_ids(jv_sub["test"])))
        expect("java structured-id: починил testSub, сломал testAdd = регрессия",
               _diff_checks(jv_sub, jv_add) == (["test"], []))
        # tsc: новый код ошибки в новом месте = регрессия
        base_ts = {"typecheck": {"status": "fail", "runs": [{"output_tail":
                   "src/a.ts(3,5): error TS2322: Type error"}]}}
        new_ts = {"typecheck": {"status": "fail", "runs": [{"output_tail":
                  "src/a.ts(3,5): error TS2322: Type error\nsrc/b.ts(9,1): error TS2531: Object is possibly null"}]}}
        expect("structured-id: новая tsc-ошибка в новом файле = регрессия",
               _diff_checks(base_ts, new_ts) == (["typecheck"], []))

        # v2.88 (finding живого прогона ii-sreda): vite печатает "Build failed in 1.41s" — ВРЕМЯ
        # волатильно. Раньше id падения включал время -> новый id каждый прогон -> ЛОЖНАЯ регрессия
        # на неизменной красной сборке. Теперь время нормализуется, а реальная строка ошибки — id.
        vite_err = ('src/shared/ui/index.tsx (19:9): "Markdown" is not exported by '
                    '"src/shared/ui/markdown.ts", imported by "src/shared/ui/index.tsx".')
        base_vite = {"build": {"status": "fail", "runs": [{"output_tail": "✗ Build failed in 1.38s\nerror during build:\n" + vite_err}]}}
        after_vite = {"build": {"status": "fail", "runs": [{"output_tail": "✗ Build failed in 1.41s\nerror during build:\n" + vite_err}]}}
        expect("vite: та же ошибка сборки, другое ВРЕМЯ (1.38s->1.41s) = НЕ регрессия (ложный триггер устранён)",
               _diff_checks(base_vite, after_vite) == ([], []))
        new_vite = {"build": {"status": "fail", "runs": [{"output_tail": "✗ Build failed in 1.55s\nerror during build:\nsrc/shared/lib/formatPrice.ts (2:9): \"x\" is not defined"}]}}
        expect("vite: НОВАЯ ошибка сборки в другом файле = регрессия (реальную поломку различаем)",
               _diff_checks(base_vite, new_vite) == (["build"], []))
        expect("failure-ids: время нормализовано (id стабилен между прогонами)",
               _failure_ids(base_vite["build"]) == _failure_ids(after_vite["build"]))

        # v2.85 (finding аудита): потеря покрытия — самый острый ложный green. Модель «чинит»
        # красный тест, УДАЛЯЯ его -> tests_absent -> status warn. Раньше fail->warn/pass->warn не
        # считались регрессией -> ready_for_pr=true на удалённых тестах. Теперь = регрессия.
        expect("coverage-loss: pass->warn (проверка перестала выполняться) = регрессия",
               _diff_checks({"test": {"status": "pass"}}, {"test": {"status": "warn"}}) == (["test"], []))
        expect("coverage-loss: fail->warn (падавший тест удалён, а не починен) = регрессия",
               _diff_checks({"test": {"status": "fail"}}, {"test": {"status": "warn"}}) == (["test"], []))
        expect("coverage: warn->warn (тестов не было и нет) = НЕ регрессия",
               _diff_checks({"test": {"status": "warn"}}, {"test": {"status": "warn"}}) == ([], []))
        expect("coverage: warn->pass (тесты появились) = НЕ регрессия (улучшение)",
               _diff_checks({"test": {"status": "warn"}}, {"test": {"status": "pass"}}) == ([], []))
        # v2.87 (finding аудита): симметрично — warn/not_run -> fail = НОВАЯ краснота = регрессия.
        # На базе тестов не было (warn), правка добавила ПАДАЮЩИЙ тест -> раньше проскакивало
        # (implementation_verification baseline-освобождён) -> ложный green. Теперь ловим.
        expect("new-red: warn->fail (добавлен падающий тест) = регрессия",
               _diff_checks({"test": {"status": "warn"}}, {"test": {"status": "fail"}}) == (["test"], []))
        expect("new-red: not_run->fail = регрессия",
               _diff_checks({"x": {"status": "not_run"}}, {"x": {"status": "fail"}}) == (["x"], []))
        expect("new-red: None(нет в базе)->fail = регрессия",
               _diff_checks({}, {"x": {"status": "fail"}}) == (["x"], []))

        # v2.74: свод падающих проверок базы -> модель видит реальный вывод (что чинить)
        fs = _baseline_failure_summary({
            "test": {"status": "fail", "runs": [
                {"command": "npm test", "exit_code": 1, "ok": False,
                 "output_tail": "expected 'Вчера' got 'Сегодня'"}]},
            "build": {"status": "pass", "runs": [{"command": "npm run build", "ok": True}]}})
        expect("baseline-summary: включает падающий тест с выводом, пропускает прошедший build",
               "expected 'Вчера'" in fs and "npm test" in fs and "npm run build" not in fs)

        # интеграция: baseline_diff на репо без тулчейна (проверки not_run -> нет регрессий) ->
        # правка проходит по критерию no-regressions даже без «всё зелёное»
        it_bd = iter([{"op": "write", "path": "src/bd.py", "content": "b=1\n"}, {"done": True}])
        rep_bd = run_pipeline("baseline-diff", sig, root, lambda c: next(it_bd), policy=pol,
                              budget={"max_model_calls": 5}, feature="bd-fn",
                              commit=True, baseline_diff=True)
        expect("baseline_diff: критерий no-regressions в отчёте",
               rep_bd["ready_criterion"] == "no-regressions" and rep_bd["baseline"] is not None)
        expect("baseline_diff: нет регрессий -> ready_for_pr True",
               rep_bd["baseline"]["no_regressions"] is True and rep_bd["ready_for_pr"] is True)
        _git(root, "checkout", "-q", orig_branch)

        # v2.77 require_fix: no-regressions есть, но fixed пуст -> НЕ ready (правка не починила)
        it_rf = iter([{"op": "write", "path": "src/rf.py", "content": "r=1\n"}, {"done": True}])
        rep_rf = run_pipeline("require-fix", sig, root, lambda c: next(it_rf), policy=pol,
                              budget={"max_model_calls": 5}, feature="rf-fn",
                              commit=True, baseline_diff=True, require_fix=True)
        expect("require_fix: без fixed -> ready_for_pr False (не сломал, но и не починил)",
               rep_rf["baseline"]["no_regressions"] is True and rep_rf["ready_for_pr"] is False
               and rep_rf["ready_criterion"] == "no-regressions+require-fix")
        _git(root, "checkout", "-q", orig_branch)

        # v2.81 Containment: политика ПО УМОЛЧАНИЮ (policy не передан) блокирует git push
        # (block_push) и объявляет действующую изоляцию честно в report["containment"].
        # rep_iso создан без явной policy -> дефолт движка.
        expect("containment: дефолтная политика движка блокирует push + честный report",
               isinstance(rep_iso.get("containment"), dict)
               and rep_iso["containment"]["block_push"] is True
               and rep_iso["containment"]["sandbox"] is False
               and rep_iso["containment"]["shell_mode"] == "unrestricted")
        # sandbox=True -> shell по allowlist (произвольный shell выключен) — видно в отчёте
        it_sb = iter([{"op": "write", "path": "src/sb.py", "content": "s=1\n"}, {"done": True}])
        rep_sb = run_pipeline("в песочнице", sig, root, lambda c: next(it_sb),
                              budget={"max_model_calls": 5}, feature="sb-fn",
                              commit=True, sandbox=True, install_deps=False)
        expect("containment: sandbox=True -> shell_mode=allowlist + block_push в отчёте",
               rep_sb["containment"]["sandbox"] is True
               and rep_sb["containment"]["shell_mode"] == "allowlist"
               and rep_sb["containment"]["block_push"] is True)
        _git(root, "checkout", "-q", orig_branch)

        # v2.83 Full RunPlan: независимый ревью ai-review гейтов (writer ≠ judge).
        # QUICK + ui_changed -> трек VISUAL добавляет ux_review (ai-review). Без ревью он блокирует.
        sig_rv = dict(sig); sig_rv["ui_changed"] = True
        it_nr = iter([{"op": "write", "path": "src/nr.py", "content": "n=1\n"}, {"done": True}])
        rep_nr = run_pipeline("ui без ревью", sig_rv, root, lambda c: next(it_nr),
                              budget={"max_model_calls": 5}, feature="nr-fn",
                              commit=True, isolate=True, install_deps=False)
        expect("review: ui_changed -> ux_review в плане и БЕЗ ревью блокирует (unmet)",
               "ux_review" in rep_nr["gates"]["evaluated"] and "ux_review" in rep_nr["gates"]["unmet"]
               and rep_nr["reviews"] is None)
        _git(root, "checkout", "-q", orig_branch)

        # с независимым ревьюером, который выносит pass -> ux_review закрыт легитимно (вердикт judge).
        # v3.0.11: ревьюер СНАЧАЛА читает изменённый файл (реальная верификация), затем pass — иначе
        # блокирующий гейт не закрывается по рубер-стампу (0 reads).
        def pass_provider(prompt):
            if "--- src/rp.py ---" in prompt:
                return '{"kind":"reviewer-result","status":"pass","checks":[{"id":"ok","status":"pass"}]}'
            return '{"op":"read","path":"src/rp.py"}'
        it_rp = iter([{"op": "write", "path": "src/rp.py", "content": "p=1\n"}, {"done": True}])
        rep_rp = run_pipeline("ui с ревью pass", sig_rv, root, lambda c: next(it_rp),
                              budget={"max_model_calls": 20}, feature="rp-fn",
                              commit=True, isolate=True, install_deps=False,
                              review=True, reviewer_proposer=pass_provider)
        expect("review: независимый reviewer pass -> ux_review НЕ в unmet (закрыт вердиктом)",
               "ux_review" not in rep_rp["gates"]["unmet"]
               and any(r["gate"] == "ux_review" and r["status"] == "pass" for r in (rep_rp["reviews"] or [])))
        _git(root, "checkout", "-q", orig_branch)

        # ревьюер выносит fail -> ux_review блокирует (судья сильнее писателя; writer не переопределяет)
        fail_provider = lambda prompt: '{"kind":"reviewer-result","status":"fail","checks":[{"id":"ux","status":"fail"}],"blockers":["нет состояний экрана"]}'
        it_rf2 = iter([{"op": "write", "path": "src/rf2.py", "content": "f=1\n"}, {"done": True}])
        rep_rf2 = run_pipeline("ui с ревью fail", sig_rv, root, lambda c: next(it_rf2),
                               budget={"max_model_calls": 20}, feature="rf2-fn",
                               commit=True, isolate=True, install_deps=False,
                               review=True, reviewer_proposer=fail_provider)
        expect("review: reviewer fail -> ux_review блокирует (writer не переопределяет судью)",
               "ux_review" in rep_rf2["gates"]["unmet"]
               and any(r["gate"] == "ux_review" and r["status"] == "fail" for r in (rep_rf2["reviews"] or [])))
        _git(root, "checkout", "-q", orig_branch)

        # честная граница: детерминированный артефакт-гейт ревьюер НЕ закрывает (requirements — не ai-review)
        expect("review: детерминированные артефакт-гейты не входят в reviewable (requirements)",
               "requirements" not in _reviewable_gates(["requirements", "specification", "ux_review"], sig_rv)
               and "ux_review" in _reviewable_gates(["requirements", "ux_review"], sig_rv))

        # v2.85 (finding аудита): reviewer WARN с blockers на блокирующем гейте НЕ закрывает его -> блок.
        # rc11: warn ОБЯЗАН нести конкретные blockers (иначе вердикт невалиден — блок без причины).
        warn_provider = lambda prompt: ('{"kind":"reviewer-result","status":"warn",'
                                        '"checks":[{"id":"x","status":"warn"}],'
                                        '"blockers":["состояние загрузки экрана не покрыто"]}')
        it_rw = iter([{"op": "write", "path": "src/rw.py", "content": "w=1\n"}, {"done": True}])
        rep_rw = run_pipeline("ui с ревью warn", sig_rv, root, lambda c: next(it_rw),
                              budget={"max_model_calls": 20}, feature="rw-fn",
                              commit=True, isolate=True, install_deps=False,
                              review=True, reviewer_proposer=warn_provider)
        expect("review: reviewer WARN(c blockers) на блокирующем ux_review -> гейт блокирует (не тихий pass)",
               "ux_review" in rep_rw["gates"]["unmet"]
               and any(r["gate"] == "ux_review" and r["status"] == "warn" for r in (rep_rw["reviews"] or [])))
        _git(root, "checkout", "-q", orig_branch)

        # rc11: contentless warn (без blockers) — НЕвалидный вердикт (блок без причины): гейт НЕ
        # закрывается (остаётся unmet), а трейс помечается errors — вердикт отвергнут, не «тихий блок».
        cwarn_provider = lambda prompt: '{"kind":"reviewer-result","status":"warn","checks":[{"id":"x","status":"warn"}]}'
        it_cw = iter([{"op": "write", "path": "src/cw.py", "content": "c=1\n"}, {"done": True}])
        rep_cw = run_pipeline("ui с ревью warn без причины", sig_rv, root, lambda c: next(it_cw),
                              budget={"max_model_calls": 20}, feature="cw-fn",
                              commit=True, isolate=True, install_deps=False,
                              review=True, reviewer_proposer=cwarn_provider)
        expect("review rc11: warn без blockers -> вердикт невалиден (errors) и ux_review остаётся unmet",
               "ux_review" in rep_cw["gates"]["unmet"]
               and any(r["gate"] == "ux_review" and r.get("errors") for r in (rep_cw["reviews"] or [])))
        _git(root, "checkout", "-q", orig_branch)

        # v3.0-rc9 (finding живого прогона kimi): ревьюеру ОБЯЗАН передаваться контекст изменения
        # (дифф + список файлов). Раньше base_context был пуст -> прилежная модель честно возвращала
        # fail «нечего читать», делая ai-review структурно непроходимым. Ревьюер здесь ставит pass
        # ТОЛЬКО если реально увидел изменённый путь в своём промпте — доказывает доставку диффа.
        def ctx_reviewer(prompt):
            if "--- src/cx.py ---" in prompt:        # v3.0.11: уже прочитал реальный файл -> pass
                return '{"kind":"reviewer-result","status":"pass","checks":[{"id":"seen","status":"pass"}]}'
            if "src/cx.py" in prompt:                # дифф доставлен -> читаем изменённый путь
                return '{"op":"read","path":"src/cx.py"}'
            return ('{"kind":"reviewer-result","status":"fail","checks":[{"id":"seen","status":"fail"}],'
                    '"blockers":["контекст изменения пуст: не дан дифф/список файлов"]}')
        it_cx = iter([{"op": "write", "path": "src/cx.py", "content": "cx=1\n"}, {"done": True}])
        rep_cx = run_pipeline("ui с ревью, проверка доставки диффа", sig_rv, root, lambda c: next(it_cx),
                              budget={"max_model_calls": 20}, feature="cx-fn",
                              commit=True, isolate=True, install_deps=False,
                              review=True, reviewer_proposer=ctx_reviewer)
        expect("review rc9: ревьюер получает контекст изменения (дифф) -> видит src/cx.py и ставит pass",
               "ux_review" not in rep_cx["gates"]["unmet"]
               and any(r["gate"] == "ux_review" and r["status"] == "pass" for r in (rep_cx["reviews"] or [])))
        _git(root, "checkout", "-q", orig_branch)

        # v3.0.11 (finding аудита P2): рубер-стамп — pass БЕЗ единого чтения на БЛОКИРУЮЩЕМ гейте НЕ
        # закрывает его (симметрия с security-путём: «увидел дифф в контексте» != «проверил чтением»).
        rubber = lambda prompt: '{"kind":"reviewer-result","status":"pass","checks":[{"id":"ok","status":"pass"}]}'
        it_rs = iter([{"op": "write", "path": "src/rs.py", "content": "r=1\n"}, {"done": True}])
        rep_rs = run_pipeline("ui рубер-стамп без чтений", sig_rv, root, lambda c: next(it_rs),
                              budget={"max_model_calls": 20}, feature="rs-fn",
                              commit=True, isolate=True, install_deps=False,
                              review=True, reviewer_proposer=rubber)
        expect("v3.0.11 A8: pass БЕЗ чтений (0 reads) на блокирующем ux_review -> НЕ закрыт (рубер-стамп)",
               "ux_review" in rep_rs["gates"]["unmet"]
               and any(r["gate"] == "ux_review" and r.get("closed_as") == "blocked"
                       for r in (rep_rs["reviews"] or [])))
        _git(root, "checkout", "-q", orig_branch)

        # _change_context напрямую: список изменённых файлов + unified-дифф на точной ревизии
        _git(root, "checkout", "-q", "-B", "cx-direct")
        # src/ мог исчезнуть: git не хранит ПУСТЫЕ каталоги, а пайплайн с commit=True без isolate
        # делает `git add -A` и уносит содержимое на рабочую ветку — возврат на базовую удаляет и
        # файлы, и каталог. Зависимость была НЕЯВНОЙ и держалась на версии git: локально (2.43)
        # каталог исчезал и тест падал FileNotFoundError, в CI (2.54) переживал. Тест, зелёный от
        # версии git, рано или поздно соврёт в обе стороны. Продуктового дефекта нет:
        # `ai-ops run --execute` всегда изолируется, пара commit=True + isolate=False есть только здесь.
        (root / "src").mkdir(exist_ok=True)
        (root / "src" / "cxd.py").write_text("def cxd():\n    return 42\n", encoding="utf-8")
        # Индексируем ТОЛЬКО проверяемый файл. `add -A` уносил в коммит ещё и артефакты прогонов,
        # накопленные ПРЕДЫДУЩИМИ шагами теста (.ai/reevaluate-evidence-*.json): стат-список
        # раздувался, дифф упирался в усечение _change_context на 12000 символов, и тело правки
        # («return 42») из контекста ВЫПАДАЛО. Проверка обязана мерить _change_context, а не объём
        # мусора рядом.
        #
        # Замерено, что это artefact теста, а не продукта: реальный прогон
        # (`isolate=True, commit=True`) коммитит РОВНО изменённый файл — проверено отдельным
        # прогоном в чистом репозитории, в коммите один src/real.py. Мусор копится только здесь,
        # где десятки шагов подряд работают в одном дереве без изоляции.
        _git(root, "add", "src/cxd.py"); _git(root, "commit", "-q", "-m", "cxd")
        _, cxsha, _ = _git(root, "rev-parse", "HEAD")
        cc = _change_context(root, cxsha.strip())
        expect("_change_context: содержит изменённый путь и тело диффа",
               "src/cxd.py" in cc and "return 42" in cc)
        expect("_change_context: пустая ревизия -> пустой контекст (прежнее поведение)",
               _change_context(root, None) == "" and _change_context(root, "") == "")

        # v3.0-rc16 (P0): _change_context_range — интегрированный дифф base..head (вся цепочка, не только
        # последний коммит). Два коммита поверх базы -> оба файла в range-контексте.
        _git(root, "checkout", "-q", "-B", "cx-range")
        _, base_r, _ = _git(root, "rev-parse", "HEAD"); base_r = base_r.strip()
        (root / "src").mkdir(exist_ok=True)
        (root / "src" / "rA.py").write_text("A = 1\n", encoding="utf-8")
        _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "pkgA")
        (root / "src" / "rB.py").write_text("B = 2\n", encoding="utf-8")
        _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "pkgB")
        _, head_r, _ = _git(root, "rev-parse", "HEAD"); head_r = head_r.strip()
        cr = _change_context_range(root, base_r, head_r)
        expect("v3.0-rc16 _change_context_range: видит ВСЕ коммиты диапазона (pkgA И pkgB), не только последний",
               "src/rA.py" in cr and "src/rB.py" in cr and "pkgA" in cr and "pkgB" in cr)
        # деградация: без base -> одиночная ревизия (только последний коммит)
        single = _change_context_range(root, None, head_r)
        expect("v3.0-rc16 _change_context_range: без base -> деградация до одиночной ревизии (только rB)",
               "src/rB.py" in single and "src/rA.py" not in single)
        _git(root, "checkout", "-q", orig_branch); _git(root, "branch", "-D", "cx-range")

        # v3.0-rc16 (P0): _security_verdict_errors — валидатор security-вердикта (убивает false-green)
        import validate_reviewer_result as _vrr2
        bad_pass = {"status": "pass"}          # НЕТ checks/gate/schema — раньше принимался как pass
        expect("v3.0-rc16 security-verdict: голый {status:pass} -> невалиден (нет checks/структуры)",
               bool(_security_verdict_errors(bad_pass, "abc123", ["injection"], _vrr2)))
        good_pass = {"schema_version": 1, "kind": "reviewer-result", "gate": "security",
                     "status": "pass", "reviewed_revision": "abc123",
                     "checks": [{"id": "injection", "status": "pass"}],
                     "domain_results": [{"domain": "injection", "status": "pass",
                                         "checks": [{"id": "no_injection_surface", "status": "pass"}],
                                         "evidence": [{"type": "code-read", "path": "a.py", "lines": "1-5"}]}]}
        expect("v3.0-rc16 security-verdict: структурный pass c domain_results -> валиден",
               _security_verdict_errors(good_pass, "abc123", ["injection"], _vrr2) == [])
        expect("v3.0-rc16 security-verdict: reviewed_revision != проверяемой -> невалиден",
               any("revision" in e for e in _security_verdict_errors(
                   {**good_pass, "reviewed_revision": "OTHER"}, "abc123", ["injection"], _vrr2)))
        # v3.0.1 (finding аудита P0): SecurityVerdict v2 — domain_results обязан покрыть КАЖДЫЙ применимый
        # домен. Один общий check по 4 доменам -> невалиден; пропущенный/лишний домен -> невалиден.
        four = ["authentication", "authorization_idol", "input_validation", "data_isolation"]
        one_generic = {"schema_version": 1, "kind": "reviewer-result", "gate": "security",
                       "status": "pass", "reviewed_revision": "abc123",
                       "checks": [{"id": "security-ok", "status": "pass"}]}
        expect("v3.0.1 SecVerdict-v2: 4 применимых домена + нет domain_results -> невалиден",
               any("domain_results" in e for e in _security_verdict_errors(one_generic, "abc123", four, _vrr2)))
        def _dr(doms, st="pass"):   # v3.0.7/v3.0.9 v2.1/v2.3: per-domain checks + evidence для pass
            return [{"domain": d, "status": st, "checks": [{"id": f"{d}_ok", "status": st}],
                     "evidence": [{"type": "code-read", "path": f"{d}.py", "lines": "1-9"}]} for d in doms]
        covered4 = {**one_generic, "domain_results": _dr(four)}
        expect("v3.0.1 SecVerdict-v2: domain_results покрывает все 4 (с per-domain checks) -> валиден",
               _security_verdict_errors(covered4, "abc123", four, _vrr2) == [])

        # v3.6.8 (finding живой квалификации): evidence type='file' с path — это code-read, а не «нераспознанный
        # type». Раньше валидный вердикт k3 (type='file'+path+lines) отвергался -> security ложно блокировал.
        file_ev = {**one_generic, "domain_results": [{"domain": "input_validation", "status": "pass",
                   "checks": [{"id": "iv_ok", "status": "pass"}],
                   "evidence": [{"type": "file", "path": "pricing.py", "lines": "10-11"}]}]}
        expect("v3.6.8 SecVerdict: evidence type='file'+path -> принимается как code-read (валиден)",
               _security_verdict_errors(file_ev, "abc123", ["input_validation"], _vrr2) == [])
        expect("v3.6.8 анти-false-green: type='file' на прочитанный путь -> валиден (reads-сверка ок)",
               _security_verdict_errors(file_ev, "abc123", ["input_validation"], _vrr2,
                                        reviewer_reads=["pricing.py"]) == [])
        expect("v3.6.8 анти-false-green: type='file' на НЕпрочитанный путь -> сфабрикован (невалиден)",
               any("сфабрикован" in e for e in _security_verdict_errors(
                   file_ev, "abc123", ["input_validation"], _vrr2, reviewer_reads=["other.py"])))
        noev = {**one_generic, "domain_results": [{"domain": "input_validation", "status": "pass",
                "checks": [{"id": "x", "status": "pass"}], "evidence": [{"type": "vibes"}]}]}
        expect("v3.6.8: evidence без распознаваемого type И без path -> невалиден (защита цела)",
               bool(_security_verdict_errors(noev, "abc123", ["input_validation"], _vrr2)))
        three = {**one_generic, "domain_results": _dr(four[:3])}
        expect("v3.0.1 SecVerdict-v2: покрыто 3 из 4 доменов -> невалиден (не закрыт)",
               any("не покрывает" in e for e in _security_verdict_errors(three, "abc123", four, _vrr2)))
        warn_dom = {**one_generic, "domain_results": [{"domain": d, "status": ("warn" if d == four[0] else "pass"),
                                                       "checks": [{"id": f"{d}_ok", "status": "pass"}]} for d in four]}
        expect("v3.0.1 SecVerdict-v2: warn в домене при общем pass -> несогласовано (невалиден)",
               any("несогласованно" in e for e in _security_verdict_errors(warn_dom, "abc123", four, _vrr2)))
        # v3.0.7 (finding аудита P1): SecurityVerdict v2.1 — pass домена БЕЗ per-domain checks не закрывает
        no_ev = {**one_generic, "domain_results": [{"domain": d, "status": "pass"} for d in four]}   # нет checks
        expect("v3.0.7 SecVerdict-v2.1: домены без per-domain checks -> невалиден (нет доказательств по домену)",
               any("domain-specific checks" in e for e in _security_verdict_errors(no_ev, "abc123", four, _vrr2)))
        # v3.0.8 SecVerdict-v2.2: пустой nested-check `checks:[{}]` больше НЕ проходит (нужен id+status)
        empty_ck = {**one_generic, "domain_results": [{"domain": d, "status": "pass", "checks": [{}]} for d in four]}
        expect("v3.0.8 SecVerdict-v2.2: nested-check без id/status (checks:[{}]) -> невалиден",
               any("nested-check без id" in e for e in _security_verdict_errors(empty_ck, "abc123", four, _vrr2)))
        # v3.0.9 SecVerdict-v2.3: pass-домен с id+status, но БЕЗ evidence-ссылки -> невалиден
        no_ref = {**one_generic, "domain_results": [{"domain": d, "status": "pass",
                                                     "checks": [{"id": f"{d}_ok", "status": "pass"}]} for d in four]}
        expect("v3.0.9 SecVerdict-v2.3: pass без evidence-ссылки -> невалиден (id+status не доказательство)",
               any("без evidence" in e for e in _security_verdict_errors(no_ref, "abc123", four, _vrr2)))
        # v3.0.10 (finding аудита P1): EvidenceRef — структура + сверка с РЕАЛЬНЫМ trace ревьюера.
        _one = ["injection"]

        def _dom_ev(ev):   # один домен injection pass с заданным evidence
            return {"schema_version": 1, "kind": "reviewer-result", "gate": "security", "status": "pass",
                    "reviewed_revision": "abc123", "checks": [{"id": "c", "status": "pass"}],
                    "domain_results": [{"domain": "injection", "status": "pass",
                                        "checks": [{"id": "injection_ok", "status": "pass"}], "evidence": ev}]}
        # (a) строка вместо структурной ссылки -> невалиден
        expect("v3.0.10 EvidenceRef: строка 'checked' (не структура) -> невалиден",
               any("не структурная ссылка" in e
                   for e in _security_verdict_errors(_dom_ev(["checked"]), "abc123", _one, _vrr2)))
        # (b) code-read без сверки (reviewer_reads=None) -> форма валидна (обратная совместимость)
        expect("v3.0.10 EvidenceRef: code-read с path без trace -> валиден (форма)",
               _security_verdict_errors(_dom_ev([{"type": "code-read", "path": "src/a.py", "lines": "1-9"}]),
                                        "abc123", _one, _vrr2) == [])
        # (c) code-read + trace, файл ДЕЙСТВИТЕЛЬНО прочитан -> валиден
        expect("v3.0.10 EvidenceRef: code-read ссылается на реально прочитанный файл -> валиден",
               _security_verdict_errors(_dom_ev([{"type": "code-read", "path": "src/a.py", "lines": "1-9"}]),
                                        "abc123", _one, _vrr2, reviewer_reads=["src/a.py"]) == [])
        # (d) code-read + trace, файл ревьюер НЕ читал -> невалиден (сфабрикованная ссылка)
        expect("v3.0.10 EvidenceRef: code-read на непрочитанный файл при наличии trace -> невалиден (фабрикация)",
               any("которого нет среди реально прочитанных" in e
                   for e in _security_verdict_errors(_dom_ev([{"type": "code-read", "path": "src/ghost.py"}]),
                                                     "abc123", _one, _vrr2, reviewer_reads=["src/a.py"])))
        # (e) test evidence без command -> невалиден; с command -> валиден (reviewer trace не требуется)
        expect("v3.0.10 EvidenceRef: test evidence без command -> невалиден",
               any("test evidence без command" in e
                   for e in _security_verdict_errors(_dom_ev([{"type": "test"}]), "abc123", _one, _vrr2)))
        expect("v3.0.10 EvidenceRef: test evidence с command -> валиден",
               _security_verdict_errors(_dom_ev([{"type": "test", "command": "pytest tests/"}]),
                                        "abc123", _one, _vrr2) == [])
        # (f) неизвестный type -> невалиден
        expect("v3.0.10 EvidenceRef: неизвестный type -> невалиден",
               any("без распознаваемого type" in e
                   for e in _security_verdict_errors(_dom_ev([{"type": "vibes", "note": "ok"}]),
                                                     "abc123", _one, _vrr2)))
        # (g) v3.0.11: одинаковое имя, РАЗНЫЙ путь — basename-fallback убран -> невалиден (фабрикация)
        expect("v3.0.11 EvidenceRef: same-basename другой путь (tests/config.py vs src/prod/config.py) -> невалиден",
               any("которого нет среди реально прочитанных" in e
                   for e in _security_verdict_errors(_dom_ev([{"type": "code-read", "path": "src/prod/config.py"}]),
                                                     "abc123", _one, _vrr2, reviewer_reads=["tests/config.py"])))
        # v3.0.11 (finding аудита P1): destructive-approval валидируется STRICT (как в run_pipeline).
        # v3.37: разница «non-strict пропускает / strict отвергает» БОЛЬШЕ НЕ СУЩЕСТВУЕТ — рыхлую
        # запись без привязки отвергают ОБА режима. Проверяем именно это: strict больше не
        # единственная защита, а последний рубеж.
        import approvals as _a4
        _loose_destr = {"approval": "destructive", "approved_by": "u@x", "scope": ".", "reason": "ok"}
        expect("v3.37 destructive: рыхлая запись без привязки невалидна и БЕЗ strict",
               _a4._record_valid(_loose_destr, now=_a4._now_iso(), plan_hash="x") is False
               and _a4._record_valid(_loose_destr, now=_a4._now_iso(), plan_hash="x", strict=True) is False)
        _bound_destr = {**_loose_destr, "binds_to": "x"}
        expect("v3.37 destructive: привязанная запись проходит non-strict, но strict всё равно требует большего",
               _a4._record_valid(_bound_destr, now=_a4._now_iso(), plan_hash="x") is True
               and _a4._record_valid(_bound_destr, now=_a4._now_iso(), plan_hash="x", strict=True) is False)

        # v3.0-rc20 (finding аудита P0): high-risk домен, применимый ПО ПУТЯМ, требует ApprovalRecord
        # (reviewer не закрывает). Dockerfile/CI -> deployment_config; обычный src -> ничего; catch-all
        # secrets ('.*') НЕ форсирует human на любом файле.
        expect("v3.0-rc20 approval-by-path: Dockerfile -> deployment_config требует ApprovalRecord",
               "deployment_config" in _human_approval_domains_uncovered(str(root), "no-wi", ["Dockerfile", "src/x.py"]))
        expect("v3.0-rc20 approval-by-path: .github/workflows -> deployment_config",
               "deployment_config" in _human_approval_domains_uncovered(str(root), "no-wi", [".github/workflows/deploy.yml"]))
        expect("v3.0-rc20 approval-by-path: обычный src -> human-approval НЕ требуется (нет over-block)",
               _human_approval_domains_uncovered(str(root), "no-wi", ["src/app.py", "tests/t.py"]) == [])
        _git(root, "checkout", "-q", orig_branch)

        # v3.0.1 (finding аудита P0): BASE BINDING — рабочая ветка форкается от --base, а НЕ от текущего
        # HEAD. Делаем ветку feat-base с ДРУГИМ SHA, checkout остаётся на orig_branch, прогон с base=feat-base.
        _git(root, "checkout", "-q", "-B", "feat-base")
        (root / "src").mkdir(exist_ok=True)
        (root / "src" / "on_feat.py").write_text("FEAT = 1\n", encoding="utf-8")
        _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "commit on feat-base")
        _, feat_sha, _ = _git(root, "rev-parse", "HEAD"); feat_sha = feat_sha.strip()
        _git(root, "checkout", "-q", orig_branch)   # текущий checkout НЕ на feat-base
        it_bb = iter([{"op": "write", "path": "src/bb.py", "content": "b=1\n"}, {"done": True}])
        rep_bb = run_pipeline("base binding", {"task_type": "QUICK", "size": "small", "risk": "low",
                              "affected_areas": ["core"]}, root, lambda c: next(it_bb),
                              budget={"max_model_calls": 8}, feature="bb-fn",
                              commit=True, isolate=True, install_deps=False, base="feat-base")
        # ветка ai-ops/bb-fn должна форкнуться от feat_sha (виден on_feat.py в worktree), не от orig
        _wt_bb = root / ".ai" / "worktrees" / "bb-fn"
        _forked_ok = (_wt_bb / "src" / "on_feat.py").exists() if _wt_bb.is_dir() else False
        expect("v3.0.1 base-binding: worktree форкнут от --base (feat-base), а не от текущего HEAD",
               rep_bb.get("status") != "error" and _forked_ok
               and (rep_bb.get("base_binding") or {}).get("base_ref") == "feat-base")
        _git(root, "checkout", "-q", orig_branch)
        try:
            _wt2 = __import__("worktree"); _wt2.remove(root, "bb-fn", force=True)
        # Причина ЗАПИСАНА (срез tests ратчета 2026-08-12): уборка временного worktree ПОСЛЕ
        # вынесенных выше `expect`. Её отказ не участвует ни в одном утверждении теста; ронять тут
        # значило бы подменить результат проверки base-binding ошибкой удаления каталога. Мусор
        # добирается следующей строкой (`worktree prune`).
        except Exception: pass  # noqa: BLE001,S110 — уборка после вынесенных проверок
        _git(root, "worktree", "prune"); _git(root, "branch", "-D", "ai-ops/bb-fn"); _git(root, "branch", "-D", "feat-base")

        # v3.0.1 (P0): high-risk approval — legacy «рыхлая» запись (без binds_to/expires_at/risk/source)
        # НЕ закрывает high-risk домен (strict). Кладём такую запись и всё равно uncovered.
        import approvals as _appr3  # noqa: F401 — модуль нужен соседним проверкам блока
        # Рыхлая запись: без binds_to/expires_at/risk/source -> high-risk домен ею не закрывается.
        # v3.37: кладём YAML напрямую — `write_record` такую запись больше не создаёт (привязка
        # безусловна), но на дисках дочек до этой версии она лежит, и проверять надо именно её.
        import yaml as _y3
        _ad3 = root / "features" / "no-wi" / "approvals"
        _ad3.mkdir(parents=True, exist_ok=True)
        (_ad3 / "deployment_config.yaml").write_text(_y3.safe_dump(
            {"schema_version": 1, "kind": "ApprovalRecord", "approval": "deployment_config",
             "approved_by": "u@x", "scope": ".", "reason": "ok"}, allow_unicode=True), encoding="utf-8")
        expect("v3.0.1 strict-approval: legacy рыхлый ApprovalRecord НЕ закрывает high-risk deployment_config",
               "deployment_config" in _human_approval_domains_uncovered(str(root), "no-wi", ["Dockerfile"]))

        # v3.0.2/v3.0.7 (finding аудита P0): _resolve_base — explicit строго, auto без хардкода main.
        expect("v3.0.7 resolve-base: явная локальная ветка -> resolved + source=explicit-local + SHA",
               (_rb := _resolve_base(root, orig_branch)).get("resolved") is True
               and _rb.get("source") == "explicit-local" and _rb.get("mode") == "explicit"
               and _rb.get("base_sha"))
        expect("v3.0.2 resolve-base: явная несуществующая ветка -> resolved=False (НЕ тихий HEAD)",
               _resolve_base(root, "no-such-branch-xyz").get("resolved") is False)
        # v3.0.7 auto-режим: base=None -> ВСЕГДА резолвится (в пределе — текущая ветка), не хардкод main
        _ab = _resolve_base(root, None)
        expect("v3.0.7 resolve-base: auto (base=None) -> resolved, mode=auto, реальная ветка (не 'main'-хардкод)",
               _ab.get("resolved") is True and _ab.get("mode") == "auto"
               and _ab.get("base_ref") == orig_branch and _ab.get("base_sha"))
        # v3.0.9 (finding аудита P0.1): единый RemoteBaseVerifier fail-closed — репо БЕЗ origin/ветки
        # в origin -> unverifiable (доставка недоступна, НЕ «успех по умолчанию»); одинаково для обеих цепочек.
        _rvb = _verify_remote_base(root, orig_branch, _resolve_base(root, orig_branch).get("base_sha"))
        expect("v3.0.9 verify-remote-base: нет origin -> unverifiable (fail-closed, не открыть PR)",
               _rvb.get("verdict") == "unverifiable" and _rvb.get("reason"))
        # v3.0.7 (P0.2): ЯВНАЯ несуществующая --base -> preflight-БЛОК ДО модели (0 model calls),
        # НЕ выполнение от произвольного HEAD. Раньше только доставка блокировалась; теперь весь прогон.
        it_nb = iter([{"op": "write", "path": "src/nb.py", "content": "n=1\n"}, {"done": True}])
        _model_calls = {"n": 0}
        def _counting_prop(c):
            _model_calls["n"] += 1
            return next(it_nb)
        rep_nb = run_pipeline("несуществующая база", {"task_type": "QUICK", "size": "small",
                              "risk": "low", "affected_areas": ["core"]}, root, _counting_prop,
                              budget={"max_model_calls": 8}, feature="nb-fn",
                              commit=True, isolate=True, open_pr=True, install_deps=False, base="no-such-branch-xyz")
        expect("v3.0.7 base-preflight: явная несуществующая base -> status=error, ready=False, base_binding.resolved=False",
               rep_nb.get("status") == "error" and rep_nb.get("ready_for_pr") is False
               and (rep_nb.get("base_binding") or {}).get("resolved") is False
               and "base-preflight" in (rep_nb.get("error") or ""))
        expect("v3.0.7 base-preflight: НОЛЬ вызовов модели (блок до исполнения) + worktree не создан",
               _model_calls["n"] == 0 and not (root / ".ai" / "worktrees" / "nb-fn").exists())
        _git(root, "checkout", "-q", orig_branch)

        # v2.85 (finding аудита): security НЕ отдаётся self-review той же модели даже без сигналов
        expect("no-self-review: security не в reviewable даже без спец-сигналов",
               "security" not in _reviewable_gates(["security", "ux_review"], sig_rv)
               and "ai_red_team" not in _reviewable_gates(["ai_red_team", "ux_review"], sig_rv))

        # v2.86 Product Authoring: ENGINEERING-план содержит артефакт-гейты requirements/plan_readiness.
        # БЕЗ --author они блокируют; с --author (валидный артефакт) — закрываются формой.
        sig_eng = {"task_type": "ENGINEERING", "size": "small", "risk": "low", "affected_areas": ["core"]}
        it_na = iter([{"op": "write", "path": "src/na.py", "content": "n=1\n"}, {"done": True}])
        rep_na = run_pipeline("рефактор без артефактов", sig_eng, root, lambda c: next(it_na),
                              budget={"max_model_calls": 5}, feature="eng-na",
                              commit=True, isolate=True, install_deps=False)
        has_art_gates = ("requirements" in rep_na["gates"]["evaluated"]
                         and "plan_readiness" in rep_na["gates"]["evaluated"])
        expect("authoring: ENGINEERING-план содержит requirements/plan_readiness",
               has_art_gates)
        expect("authoring: БЕЗ --author артефакт-гейты блокируют (unmet)",
               "requirements" in rep_na["gates"]["unmet"] and "plan_readiness" in rep_na["gates"]["unmet"]
               and rep_na["authored"] is None)
        _git(root, "checkout", "-q", orig_branch)

        def author_provider(prompt):
            if "requirements-artifact" in prompt:
                return ("schema_version: 1\nkind: requirements-artifact\nrequirements:\n"
                        "  - id: R1\n    statement: фильтр по статусу сужает список\n"
                        "    acceptance:\n      - when статус=paid then только оплаченные\n")
            if "spec-change" in prompt:      # v2.89: ENGINEERING-план включает specification
                return ("schema_version: 1\nkind: spec-change\ncapability: catalog\nwhy: нужен фильтр\n"
                        "what_changes:\n  - добавить фильтр по статусу\ntasks:\n  - реализовать\n"
                        "requirements:\n  - name: Filter\n    text: The system SHALL filter by status.\n"
                        "    scenarios:\n      - {name: T, when: статус=paid, then: показаны оплаченные}\n")
            return ("schema_version: 1\nkind: plan-artifact\nwork_packages:\n"
                    "  - id: WP1\n    summary: добавить фильтр\n    depends_on: []\n"
                    "write_scope:\n  - src/\n")
        it_au = iter([{"op": "write", "path": "src/au.py", "content": "a=1\n"}, {"done": True}])
        rep_au = run_pipeline("рефактор с артефактами", sig_eng, root, lambda c: next(it_au),
                              budget={"max_model_calls": 5}, feature="eng-au",
                              commit=True, isolate=True, install_deps=False,
                              author=True, author_proposer=author_provider)
        expect("authoring: валидный артефакт закрывает requirements/plan_readiness (форма)",
               "requirements" not in rep_au["gates"]["unmet"]
               and "plan_readiness" not in rep_au["gates"]["unmet"])
        expect("authoring: трейс authored валиден + артефакт на диске",
               rep_au["authored"] and all(a["valid"] for a in rep_au["authored"])
               and (root / ".ai" / "worktrees" / "eng-au" / ".ai" / "runplan" / "eng-au" / "requirements.yaml").exists())
        _git(root, "checkout", "-q", orig_branch)

        # невалидный артефакт (author вернул мусор) -> гейт НЕ закрывается (форма не подтверждена)
        bad_author = lambda prompt: "это не yaml артефакта, просто текст"
        it_ba = iter([{"op": "write", "path": "src/ba.py", "content": "b=1\n"}, {"done": True}])
        rep_ba = run_pipeline("рефактор с битым артефактом", sig_eng, root, lambda c: next(it_ba),
                              budget={"max_model_calls": 5}, feature="eng-ba",
                              commit=True, isolate=True, install_deps=False,
                              author=True, author_proposer=bad_author)
        expect("authoring: невалидный артефакт -> requirements остаётся блокирующим (нет фабрикации)",
               "requirements" in rep_ba["gates"]["unmet"]
               and any(not a["valid"] for a in (rep_ba["authored"] or [])))
        _git(root, "checkout", "-q", orig_branch)

        # v3.0-rc14 (finding живой квалификации kimi): author ФЛАКНУЛ на первой попытке (пустой/битый
        # YAML) -> ретрай с нуджем -> валидный артефакт. Без ретрая флаки-провайдер ложно оставлял
        # гейт незакрытым (не движковый дефект — но на multi-package прогоне почти всегда кто-то падал).
        def flaky_author(prompt):
            if "[повтор" not in prompt:          # первая попытка — битый вывод (как флаки-провайдер)
                return "(пустой ответ модели)"
            return author_provider(prompt)       # на ретрае с нуджем — валидный артефакт
        it_fk = iter([{"op": "write", "path": "src/fk.py", "content": "f=1\n"}, {"done": True}])
        rep_fk = run_pipeline("рефактор с флаки-автором", sig_eng, root, lambda c: next(it_fk),
                              budget={"max_model_calls": 20}, feature="eng-fk",
                              commit=True, isolate=True, install_deps=False,
                              author=True, author_proposer=flaky_author)
        # ФОРМА всех артефактов восстановлена ретраем (valid=True); закрытие specification-гейта
        # отдельно зависит от openspec CLI (в CI его нет) — потому проверяем requirements + valid-форму,
        # а не "specification not in unmet" (это готча openspec, не про ретрай).
        expect("v3.0-rc14 authoring: флак на 1-й попытке -> ретрай восстанавливает валидную ФОРМУ артефактов",
               "requirements" not in rep_fk["gates"]["unmet"]
               and rep_fk["authored"] and all(a["valid"] for a in rep_fk["authored"]))
        _git(root, "checkout", "-q", orig_branch)

        # v3.0-rc14: но если author флакает ВСЕГДА — гейт честно НЕ закрывается (ретрай не фабрикует)
        always_bad = lambda prompt: "(пустой ответ модели)"
        it_ab = iter([{"op": "write", "path": "src/ab.py", "content": "b=1\n"}, {"done": True}])
        rep_ab = run_pipeline("рефактор с вечно-битым автором", sig_eng, root, lambda c: next(it_ab),
                              budget={"max_model_calls": 20}, feature="eng-ab",
                              commit=True, isolate=True, install_deps=False,
                              author=True, author_proposer=always_bad)
        expect("v3.0-rc14 authoring: вечный флак -> гейт остаётся блокирующим после ретраев (честно)",
               "requirements" in rep_ab["gates"]["unmet"]
               and any(not a["valid"] for a in (rep_ab["authored"] or [])))
        # v3.0-rc5 (finding живого прогона kimi): парсер терпим к прозе/несколькими блокам
        expect("v3.0-rc5 parse: YAML после прозы (без ограды) извлекается",
               (_parse_yaml_block("Вот артефакт:\n\nschema_version: 1\nkind: requirements-artifact\n"
                                  "requirements:\n  - id: R1\n") or {}).get("kind") == "requirements-artifact")
        expect("v3.0-rc5 parse: несколько ```-блоков — берётся первый валидный dict",
               (_parse_yaml_block("```text\nбла\n```\nтекст\n```yaml\nschema_version: 1\nkind: plan-artifact\n```")
                or {}).get("kind") == "plan-artifact")
        expect("v3.0-rc5 parse: мусор без YAML -> None (нет фабрикации)",
               _parse_yaml_block("просто текст без артефакта") is None)
        # v2.123 (P0.1) НАСТОЯЩИЙ Spec-First: невалидная author-спека -> tool loop НЕ запущен (0 кода)
        expect("v2.123 (P0.1): невалидная спека -> tool loop НЕ запущен (spec-prestage-failed, 0 impl)",
               rep_ba["loop"]["stopped"] == "spec-prestage-failed"
               and rep_ba["spec_first"]["prestage"]["implementation_skipped"] is True
               and rep_ba["ready_for_pr"] is False)
        expect("v2.123 (P0.1): при невалидной спеке код НЕ записан (src/ba.py отсутствует)",
               not (root / ".ai" / "worktrees" / "eng-ba" / "src" / "ba.py").exists())
        # позитив: валидная спека -> реализация ЗАПУСКАЕТСЯ (src/au.py записан), prestage не пропущен
        expect("v2.123 (P0.1): валидная спека -> реализация запущена (src/au.py записан)",
               (root / ".ai" / "worktrees" / "eng-au" / "src" / "au.py").exists()
               and rep_au["spec_first"]["prestage"]["implementation_skipped"] is False)
        _git(root, "checkout", "-q", orig_branch)

        # v2.89: specification authoring (OpenSpec). Тестируем _run_authoring напрямую со стабом
        # openspec_validate (реальный CLI в CI может отсутствовать — стаб делает тест детерминированным).
        spec_author = lambda prompt: (
            "schema_version: 1\nkind: spec-change\ncapability: pricing\nwhy: нужна утилита цены\n"
            "what_changes:\n  - добавить formatPrice\ntasks:\n  - реализовать\n  - тест\n"
            "requirements:\n  - name: Formatting\n    text: The system SHALL format price.\n"
            "    scenarios:\n      - {name: T, when: formatPrice(1000), then: returns 1 000}\n")
        gev_ok, auth_ok, _ = _run_authoring(spec_author, root, ["specification"], {}, "spec-ok",
                                            "форматирование цены", {"max_model_calls": 5},
                                            openspec_validate=lambda wr, cid: (True, True, "valid"))
        expect("spec-authoring: CLI доступен + strict OK -> specification закрыт (openspec_valid)",
               "specification" in gev_ok
               and gev_ok["specification"]["provided"] == ["openspec_valid", "requirements_covered"]
               and (root / "openspec" / "changes" / "spec-ok" / "proposal.md").exists())
        gev_absent, auth_absent, _ = _run_authoring(spec_author, root, ["specification"], {}, "spec-abs",
                                                    "форматирование", {"max_model_calls": 5},
                                                    openspec_validate=lambda wr, cid: (False, False, "нет CLI"))
        expect("spec-authoring: CLI отсутствует -> specification НЕ закрыт (честный блок, нет фабрикации)",
               "specification" not in gev_absent
               and any(a["gate"] == "specification" and a.get("closed") is False for a in auth_absent))
        gev_bad, auth_bad, _ = _run_authoring(lambda p: "не yaml", root, ["specification"], {}, "spec-bad",
                                              "x", {"max_model_calls": 5},
                                              openspec_validate=lambda wr, cid: (True, True, "valid"))
        expect("spec-authoring: битый spec от автора -> не закрыт (форма не прошла)",
               "specification" not in gev_bad
               and any(a["gate"] == "specification" and not a["valid"] for a in auth_bad))
        # v3.0-rc8 (finding живого прогона kimi): task-строка с двоеточием («Написать тесты: A, B») YAML
        # парсит как mapping -> раньше vsa.check «список строк» падал. Нормализация -> валиден.
        colon_author = lambda prompt: (
            "schema_version: 1\nkind: spec-change\ncapability: pricing\nwhy: нужна утилита\n"
            "what_changes:\n  - добавить formatPrice\n"
            "tasks:\n  - Написать unit-тесты: все ветвления, граничные значения, ошибочный ввод\n  - реализовать\n"
            "requirements:\n  - name: Fmt\n    text: The system SHALL format price.\n"
            "    scenarios:\n      - {name: T, when: x, then: y}\n")
        gev_colon, auth_colon, _ = _run_authoring(colon_author, root, ["specification"], {}, "spec-colon",
                                                  "цена", {"max_model_calls": 5},
                                                  openspec_validate=lambda wr, cid: (True, True, "valid"))
        expect("v3.0-rc8: task-строка с двоеточием нормализуется -> specification валиден (не ложный блок)",
               any(a["gate"] == "specification" and a["valid"] for a in auth_colon))

        # write вне scope -> denied, файл не создан, но pipeline не падает
        it2 = iter([{"op": "write", "path": "config/x", "content": "y"}, {"done": True}])
        rep2 = run_pipeline("вне scope", sig, root, lambda c: next(it2), policy=pol,
                            budget={"max_model_calls": 5})
        expect("pipeline: out-of-scope запись отклонена (denied>0)", rep2["loop"]["denied"] >= 1
               and not (root / "config" / "x").exists())

    assert ok, "перенесённый селфтест execution_pipeline: см. строки FAIL в выводе"
