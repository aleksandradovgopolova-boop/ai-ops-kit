"""Селфтест ai_ops_run, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from ai_ops_run import (  # noqa: F401 — имена, которые использует тело
    Path,
    _ls,
    _provider_trust,
    _reconcile_pending_delivery,
    _review_fix_context,
    _with_provider_fallback,
    active_work,
    exit_code,
    print_human,
    run,
)


@pytest.mark.slow
def test_ai_ops_run_selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    # v3.8.3-rc2 (#6) PROVIDER FALLBACK: retryable infra-сбой -> switch; не-retryable -> проброс; нет fb -> as-is
    _sw = {"to": None}
    _wrapped = _with_provider_fallback(
        (lambda *a, **k: (_ for _ in ()).throw(TimeoutError("request timed out"))),  # retryable (network)
        (lambda *a, **k: "FALLBACK-OK"), on_switch=lambda e: _sw.update(to="fb"))
    expect("rc2 #6: retryable infra-сбой (timeout) -> переключение на fallback-провайдер",
           _wrapped("m") == "FALLBACK-OK" and _sw["to"] == "fb")
    expect("rc2 #6: после switch остаёмся на fallback (primary не зовём)", _wrapped("m2") == "FALLBACK-OK")
    _raised = False
    try:
        _with_provider_fallback(
            (lambda *a, **k: (_ for _ in ()).throw(ValueError("bad code"))),  # НЕ retryable
            (lambda *a, **k: "X"))("m")
    except ValueError:
        _raised = True
    expect("rc2 #6: не-retryable (плохой код/тест) -> НЕ fallback, исключение пробрасывается", _raised)
    _p = lambda *a, **k: "P"
    expect("rc2 #6: нет fallback-модели -> провайдер без обёртки (as-is)",
           _with_provider_fallback(_p, None) is _p)

    # v3.8.3-rc3 JIT PROVIDER TRUST: каждая реально вызываемая модель (primary/fallback/escalation)
    # проходит key presence + KLP/TTL. primary not ready -> block; необязательный not ready -> исключить.
    import datetime as _dtt
    _now3 = _dtt.date.today().isoformat()
    _r1 = _provider_trust("deepseek", "K1", {}, {"K1": "x"}, _now3, {})
    expect("rc3 trust: ключ есть, KLP нет -> ready", _r1["ready"] is True)
    _klp_exp = {"K2": {"env_ref": "K2", "next_rotation_at": "2000-01-01"}}
    _r2 = _provider_trust("kimi", "K2", _klp_exp, {"K2": "x"}, _now3, {})
    expect("rc3 trust: ключ есть, но KLP-ротация просрочена -> НЕ ready (кандидат исключается, primary не блокируется)",
           _r2["ready"] is False and "ротация" in (_r2.get("reason") or ""))
    _r3 = _provider_trust("qwen", "K3", {}, {}, _now3, {})
    expect("rc3 trust: ключа нет в env -> НЕ ready", _r3["ready"] is False and _r3.get("reason"))
    _cc = {}
    _a3 = _provider_trust("p", "K1", {}, {"K1": "x"}, _now3, _cc)
    _b3 = _provider_trust("p", "K1", {}, {"K1": "x"}, _now3, _cc)
    expect("rc3 trust: результат кэшируется по provider (1 проверка на реально вызываемую модель)", _a3 is _b3)

    sig = {"task_type": "PRODUCT", "risk": "medium",
           "available_providers": ["anthropic"], "available_runtimes": ["claude-code"],
           "ui_changed": True, "measurable_behavior": True, "user_facing_change": True,
           "affected_areas": ["catalog", "orders-api"]}

    # planned-путь (claude-code): каркас есть, статус planned
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        r = run("фильтр по статусу в каталоге заказов", sig, root, runtime="claude-code",
                engine="controller")   # planned-путь — контроллер (pipeline теперь дефолт)
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
        expect("гейты треков агрегированы (ux_review/analytics_design_readiness)",
               {"ux_review", "analytics_design_readiness"} <= set(r["gates"]))
        # v3.27.6: analytics_runtime_verification НЕ входит в дорелизный RunPlan (только после release)
        expect("analytics_runtime_verification НЕ в дорелизном RunPlan",
               "analytics_runtime_verification" not in set(r["gates"]))

    # v3.0-rc4 (P0.1): immutable resume — смена классификации/policy при resume блокируется (нужен replan)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        fdir = root / "features" / "immx"
        fdir.mkdir(parents=True)
        (fdir / "run-settings.yaml").write_text(
            "schema_version: 1\nkind: run-settings\nworkitem_id: immx\n"
            "signals:\n  task_type: ENGINEERING\n  risk: high\npolicy:\n  sandbox: true\n", encoding="utf-8")
        r_drift = run("продолжить", {"task_type": "QUICK", "risk": "low"}, root,
                      engine="pipeline", feature="immx", resume=True)
        expect("v3.0-rc4 P0.1: resume со сменой task_type -> error (drift, нужен replan)",
               r_drift.get("status") == "error" and "replan" in (r_drift.get("error") or "").lower()
               and "task_type" in ((r_drift.get("resume") or {}).get("drift") or []))
        r_replan = run("продолжить", {"task_type": "QUICK", "risk": "low"}, root,
                       engine="pipeline", feature="immx", resume=True, replan=True)
        expect("v3.0-rc4 P0.1: replan=True -> проходит drift-проверку (ошибка уже не про replan)",
               "replan" not in (r_replan.get("error") or "").lower())
        expect("planned: без --feature wid = wi-<hash>", fid.startswith("wi-"))

        # v3.0.12 (finding аудита блок B): битый run-settings на resume -> FAIL-CLOSED (не тихий дефолт +
        # перезапись контракта). Прежде safe_load(...) or {} -> {} -> молчаливая деградация до дефолтов.
        _cf = root / "features" / "corr"; _cf.mkdir(parents=True)
        (_cf / "run-settings.yaml").write_text("", encoding="utf-8")   # оборванная запись
        _rc = run("продолжить", {"task_type": "QUICK", "risk": "low"}, root,
                  engine="pipeline", feature="corr", resume=True)
        expect("v3.0.12: битый run-settings на resume -> status=error (не тихий дефолт)",
               _rc.get("status") == "error" and "повреждён" in (_rc.get("error") or ""))
        # и файл НЕ перезаписан дефолтами (остался пустым — контракт не уничтожен молча)
        expect("v3.0.12: повреждённый run-settings НЕ перезаписан (recovery — явная операция)",
               (_cf / "run-settings.yaml").read_text(encoding="utf-8") == "")

    # v3.0.10 (finding аудита P0): base ПЕРЕПИСАН -> resume заблокирован ДАЖЕ с force_resume=True
    # (старую работу нельзя выдать за проверенную против новой базы; снимается только replan).
    with tempfile.TemporaryDirectory() as td:
        import subprocess as _sp
        root = Path(td)

        def _g(*a):
            return _sp.run(["git", "-C", td, *a], capture_output=True, text=True).stdout.strip()
        for a in (("init", "-q"), ("config", "user.email", "t@t"), ("config", "user.name", "t")):
            _g(*a)
        (root / "f").write_text("x", encoding="utf-8"); _g("add", "-A"); _g("commit", "-q", "-m", "A")
        base_A = _g("rev-parse", "HEAD")
        cur = _g("rev-parse", "--abbrev-ref", "HEAD")
        _g("checkout", "-q", "-b", "ai-ops/rwx")
        (root / "w").write_text("work", encoding="utf-8"); _g("add", "-A"); _g("commit", "-q", "-m", "W")
        work_sha = _g("rev-parse", "HEAD")
        _g("checkout", "-q", cur)
        # base переписан на несвязанный orphan-коммит (force-push назад/пересоздание)
        _g("checkout", "-q", "--orphan", "reborn")
        (root / "z").write_text("z", encoding="utf-8"); _g("add", "-A"); _g("commit", "-q", "-m", "R")
        _g("branch", "-f", cur, _g("rev-parse", "HEAD")); _g("checkout", "-q", cur)
        fdir = root / "features" / "rwx"; fdir.mkdir(parents=True)
        (fdir / "run-settings.yaml").write_text(
            "schema_version: 1\nkind: run-settings\nworkitem_id: rwx\n"
            "signals:\n  task_type: QUICK\n  risk: low\npolicy:\n"
            f"  base: {cur}\n  base_binding:\n    base_ref: {cur}\n    base_sha: {base_A}\n", encoding="utf-8")
        (fdir / "run-handoff.yaml").write_text(
            f"kind: RunHandoff\nworkitem_id: rwx\nresume_from_revision: {work_sha}\n"
            f"base_binding:\n  kind: BaseBinding\n  base_ref: {cur}\n  base_sha: {base_A}\n"
            "next_action: продолжить\nopen_questions: []\n", encoding="utf-8")
        r_rw = run("продолжить", {"task_type": "QUICK", "risk": "low"}, root,
                   engine="pipeline", feature="rwx", resume=True, force_resume=True)
        expect("v3.0.10/14 P0: base переписан + force_resume=True -> ВСЁ РАВНО blocked (force не снимает)",
               r_rw.get("status") == "blocked"
               and (r_rw.get("resume") or {}).get("base_rewritten") is True
               and "свежий" in (r_rw.get("error") or "").lower())
        # v3.0.14: replan тоже НЕ снимает блок на resume-пути (reuse устаревшего worktree) — нужен fresh run
        r_rw2 = run("продолжить", {"task_type": "QUICK", "risk": "low"}, root,
                    engine="pipeline", feature="rwx", resume=True, replan=True)
        expect("v3.0.14 P0: base переписан + replan (всё ещё resume) -> ВСЁ РАВНО blocked (нужен fresh run)",
               r_rw2.get("status") == "blocked"
               and (r_rw2.get("resume") or {}).get("base_rewritten") is True)

    # v3.0.14 (finding аудита #1, вариант B): FAST-FORWARD базы + force_resume -> ВСЁ РАВНО blocked
    # (работа не интегрирована с новой базой; force не снимает, нужен --replan).
    with tempfile.TemporaryDirectory() as td:
        import subprocess as _sp2
        root = Path(td)

        def _g2(*a):
            return _sp2.run(["git", "-C", td, *a], capture_output=True, text=True).stdout.strip()
        for a in (("init", "-q"), ("config", "user.email", "t@t"), ("config", "user.name", "t")):
            _g2(*a)
        (root / "f").write_text("x", encoding="utf-8"); _g2("add", "-A"); _g2("commit", "-q", "-m", "A")
        base_A = _g2("rev-parse", "HEAD")
        cur = _g2("rev-parse", "--abbrev-ref", "HEAD")
        _g2("checkout", "-q", "-b", "ai-ops/ffx")
        (root / "w").write_text("work", encoding="utf-8"); _g2("add", "-A"); _g2("commit", "-q", "-m", "W")
        work_sha = _g2("rev-parse", "HEAD")
        _g2("checkout", "-q", cur)
        # база УШЛА ВПЕРЁД (fast-forward): новый коммит на cur; base_A остаётся предком
        (root / "b2").write_text("advance", encoding="utf-8"); _g2("add", "-A"); _g2("commit", "-q", "-m", "B")
        fdir = root / "features" / "ffx"; fdir.mkdir(parents=True)
        (fdir / "run-settings.yaml").write_text(
            "schema_version: 1\nkind: run-settings\nworkitem_id: ffx\n"
            "signals:\n  task_type: QUICK\n  risk: low\npolicy:\n"
            f"  base: {cur}\n  base_binding:\n    base_ref: {cur}\n    base_sha: {base_A}\n", encoding="utf-8")
        (fdir / "run-handoff.yaml").write_text(
            f"kind: RunHandoff\nworkitem_id: ffx\nresume_from_revision: {work_sha}\n"
            f"base_binding:\n  kind: BaseBinding\n  base_ref: {cur}\n  base_sha: {base_A}\n"
            "next_action: продолжить\nopen_questions: []\n", encoding="utf-8")
        r_ff = run("продолжить", {"task_type": "QUICK", "risk": "low"}, root,
                   engine="pipeline", feature="ffx", resume=True, force_resume=True)
        # v3.0.15 (finding аудита P1): write BARRIER — сбой durable-записи RunPlan -> прогон НЕ начат
        # (0 вызовов модели). Монкипатчим durable_write на провал.
        _orig_dw = _ls.durable_write
        _ls.durable_write = lambda *a, **k: {"ok": False, "error": "smoke IO fail"}
        try:
            r_bar = run("барьер", {"task_type": "QUICK", "risk": "low", "affected_areas": ["core"]}, root,
                        engine="pipeline", proposer=lambda c: {"done": True}, execute=True, feature="barx")
        finally:
            _ls.durable_write = _orig_dw
        expect("v3.0.15 write-barrier: сбой durable RunPlan -> status=error (прогон не начат)",
               r_bar.get("status") == "error" and "RunPlan" in (r_bar.get("error") or ""))

        expect("v3.0.14 #1: fast-forward базы + force_resume -> blocked (force не снимает, нужен fresh run)",
               r_ff.get("status") == "blocked"
               and (r_ff.get("resume") or {}).get("base_moved") is True
               and "свежий" in (r_ff.get("error") or "").lower())

    # v2.51: привязка к ИМЕНОВАННОЙ фиче — срезы истории копятся на неё, не на wi-<hash>
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        rf = run("фильтр по типу в библиотеке", sig, root, runtime="claude-code",
                 feature="library-view", engine="controller")   # planned-каркас — контроллер
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
        # v3.0.14 (#3): event journal записан, цепочка цела, есть run_start+run_end
        _jr = _ls.journal_read(root / "features" / pfid / "lifecycle-journal.jsonl")
        expect("v3.0.14: lifecycle-journal записан + checksum-цепочка цела",
               _jr["ok"] and {e["kind"] for e in _jr["events"]} >= {"run_start", "run_end"})
        # v3.0.15 (P0): commit barrier — checkpoint ready_for_delivery ПРЕДШЕСТВУЕТ run_end (доставка
        # только после durable-фиксации). Порядок событий по seq: ready_for_delivery до run_end.
        _seq_by_kind = {e["kind"]: e["seq"] for e in _jr["events"]}
        expect("v3.0.15 commit-barrier: journal имеет ready_for_delivery ДО run_end",
               "ready_for_delivery" in _seq_by_kind
               and _seq_by_kind["ready_for_delivery"] < _seq_by_kind["run_end"])
        expect("v2.94: pipeline зарегистрировал active-work",
               (root / ".ai" / "runtime" / "active-work.yaml").exists())
        expect("v2.94: lifecycle-артефакты в отчёте", isinstance(rp.get("lifecycle"), dict)
               and rp["lifecycle"].get("workitem") == f"features/{pfid}/workitem.yaml")
        _awd = active_work.load(root / ".ai" / "runtime" / "active-work.yaml")
        # F-012: `done` — ТОЛЬКО для доведённой работы. Прогон снят с учёта в любом исходе, но
        # незакрытые гейты дают blocked с причиной: иначе `ai-ops status` показывает пустоту там,
        # где работа не сделана (находка живой квалификации на niti).
        _awe = next((w for w in _awd.get("active", []) if w.get("id") == pfid), None)
        expect("F-012: active-work снята с учёта по завершении прогона", _awe is not None)
        expect("F-012: статус отражает исход (done только при ready_for_pr, иначе blocked+причина)",
               bool(_awe) and (_awe.get("status") == "done" if rp.get("ready_for_pr")
                               else (_awe.get("status") == "blocked" and _awe.get("status_reason"))))
        expect("v2.94: единый план — движок НЕ строил второй (workitem_id совпал)",
               rp["workitem_id"] == pfid)

        # v3.0-rc17 (finding живого прогона): исключение провайдера (напр. HTTP 429 kimi ПОСЛЕ исчерпания
        # ретраев) НЕ роняет CLI traceback'ом — одиночный прогон возвращает ЧЕСТНЫЙ error-отчёт
        # (status=error, ready_for_pr=False, exit 2) с типизированным failure, как sequential (rc12/rc16).
        def _boom(c):
            raise ConnectionResetError("[Errno 54] Connection reset by peer")
        rep_boom = run("задача с падающим провайдером", {"task_type": "QUICK", "size": "small",
                       "risk": "low", "affected_areas": ["core"]}, root, engine="pipeline",
                       execute=True, proposer=_boom, feature="boomwi")
        expect("v3.0-rc17: исключение провайдера -> честный error-отчёт (не traceback)",
               rep_boom.get("status") == "error" and rep_boom.get("ready_for_pr") is False
               and rep_boom.get("kind") == "execution-pipeline"
               and (rep_boom.get("failure") or {}).get("failure_class") == "network"
               and (rep_boom.get("failure") or {}).get("retryable") is True)
        expect("v3.0-rc17: exit_code(provider-error)=2 (не 0)", exit_code(rep_boom) == 2)
        # F-012: упавший прогон тоже снимается с учёта, но `done` про него — ложь: код не написан.
        _awb = next((w for w in active_work.load(root / ".ai" / "runtime" / "active-work.yaml")
                     .get("active", []) if w.get("id") == "boomwi"), None)
        expect("v3.0-rc17/F-012: падение провайдера -> active-work снята с учёта как blocked, не done",
               bool(_awb) and _awb.get("status") == "blocked"
               and "ConnectionResetError" in (_awb.get("status_reason") or ""))
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
        # v2.111: атомарный -> конкретных пакетов нет (не выдумываем разбиение)
        expect("v2.111: атомарный пакет -> work_packages пуст",
               rp["work_package"].get("work_packages") == [])
        # v2.119: mock-прогон -> заметка «живой предложитель» уместна (осталась в not_yet)
        expect("v2.119: mock-провайдер -> заметка «живой предложитель» присутствует",
               any("живой предложитель" in n for n in (rp.get("not_yet") or [])))
        # v2.119: живой провайдер -> заметка убрана (не вводит в заблуждение)
        pscript2 = iter([{"op": "write", "path": "src/b.py", "content": "b=1\n"}, {"done": True}])
        rp_live = run("добавить b", {"task_type": "QUICK", "size": "small", "risk": "low",
                                     "affected_areas": ["core"]}, root, engine="pipeline",
                      proposer=lambda c: next(pscript2), provider_name="anthropic", feature="live-fn")
        expect("v2.119: живой провайдер -> заметка «живой предложитель» убрана из not_yet",
               not any("живой предложитель" in n for n in (rp_live.get("not_yet") or [])))
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
        # v3.0.11 (finding аудита P1): завершённый прогон несёт overall_status (не top-level status).
        # delivery-failed (ready, но PR не доставлен) ОБЯЗАН давать ненулевой код — иначе CI видит успех.
        expect("v3.0.11 exit_code: overall_status=delivery-failed -> 1 (не 0)",
               exit_code({"kind": "execution-pipeline", "ready_for_pr": True,
                          "overall_status": "delivery-failed"}) == 1)
        expect("v3.0.11 exit_code: overall_status=delivered + ready -> 0",
               exit_code({"kind": "execution-pipeline", "ready_for_pr": True,
                          "overall_status": "delivered"}) == 0)
        expect("v3.0.11 exit_code: overall_status=error -> 2",
               exit_code({"kind": "execution-pipeline", "ready_for_pr": True,
                          "overall_status": "error"}) == 2)

    # v3.8.3: reevaluate_only ПРОКИНУТ через run() -> run_pipeline (не orphan). Side-effect proof: после
    # первого execute-прогона (создана ветка) повторный reevaluate_only НЕ переавторит -> loop
    # stopped=reevaluate-only (путь без переавторинга реально взят через entrypoint, не только run_pipeline).
    import inspect as _insp
    expect("v3.8.3: run() принимает reevaluate_only", "reevaluate_only" in _insp.signature(run).parameters)
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(["git", "-C", td, "init", "-q"])
        subprocess.run(["git", "-C", td, "config", "user.email", "t@t"])
        subprocess.run(["git", "-C", td, "config", "user.name", "t"])
        _rr = Path(td); (_rr / "seed").write_text("x", encoding="utf-8")
        subprocess.run(["git", "-C", td, "add", "-A"]); subprocess.run(["git", "-C", td, "commit", "-q", "-m", "i"])
        _ps = iter([{"op": "write", "path": "rv.py", "content": "def f():\n    return 1\n"}, {"done": True}])
        _sig_rv = {"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]}
        run("add rv", _sig_rv, _rr, engine="pipeline", execute=True, feature="rev-x",
            proposer=lambda c: next(_ps))
        _r2 = run("reeval", _sig_rv, _rr, engine="pipeline", execute=True, feature="rev-x",
                  reevaluate_only=True, proposer=lambda c: {"done": True})
        expect("v3.8.3: run() прокидывает reevaluate_only -> run_pipeline (loop stopped=reevaluate-only)",
               (_r2.get("loop") or {}).get("stopped") == "reevaluate-only")

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
        # v3.0.2: base=cur (реальная ветка репо) — консистентно с resume-фазами; иначе на репо с
        # дефолтом master (как CI) base=main из фазы 1 расходится с base=master в resume -> ложная ревалидация.
        r_p1 = run("фаза 1", sig_r, root, engine="pipeline", proposer=lambda c: next(s1),
                   execute=True, feature="ctl-resume", install_deps=False, base=cur)
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
        # v3.0.14 (finding аудита #1, вариант B): база УШЛА ВПЕРЁД (fast-forward) -> --force БОЛЬШЕ НЕ
        # продолжает на устаревшем worktree (иначе PR против непроверенной интеграции с новой базой).
        # Теперь это blocked (base_moved), recourse — свежий прогон от новой базы. Прежде здесь force
        # «осознанно продолжал» — это и был закрытый trust-разрыв.
        s4 = iter([{"op": "write", "path": "src/phase4.py", "content": "p=4\n"}, {"done": True}])
        r_force = run("фаза 4", sig_r, root, engine="pipeline", proposer=lambda c: next(s4),
                      execute=True, feature="ctl-resume", install_deps=False, resume=True,
                      force_resume=True, base=cur)
        expect("v3.0.14 ctl: fast-forward базы + --force -> blocked (base_moved), не продолжает на устаревшем",
               r_force.get("status") == "blocked"
               and (r_force.get("resume") or {}).get("base_moved") is True)

    # orchestrated-путь (generic-orchestrator, mock без evidence -> blocked, но транзакция прошла)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        r2 = run("починить опечатку", {"task_type": "QUICK", "affected_areas": ["docs"]},
                 root, runtime="generic-orchestrator", provider_name="mock", execute=True,
                 engine="controller")   # orchestrated-путь — контроллер (pipeline теперь дефолт)
        expect("orchestrated: исполнение прошло, статус blocked|done",
               r2["status"] in ("blocked", "done") and r2["execution"] == "orchestrated")
        expect("orchestrated: состояние по WorkItem",
               f"workitems/{r2['workitem_id']}" in r2["run_state"])
        # P0.1: exit_code для controller — blocked -> 1, planned/done -> 0
        expect("P0.1: exit_code(blocked)=1", exit_code(r2) == (1 if r2["status"] == "blocked" else 0))
        expect("P0.1: exit_code(planned)=0", exit_code({"status": "planned"}) == 0)

    # v3.0.17 Delivery Outbox Integrity: per-delivery_id immutable outbox + СТРОГАЯ сверка идентичности +
    # барьеры записи (crash-recovery, детерминированно).
    import pr_open as _pro
    _orig_rec = _pro.reconcile_delivery

    def _mk_intent(fdir, did, wid, branch, commit, repo="o/r", base_ref="main"):
        obx = fdir / "delivery-outbox"
        _ls.durable_write(obx / f"{did}.intent.yaml",
                          {"schema_version": 1, "kind": "DeliveryIntent", "delivery_id": did,
                           "workitem_id": wid, "repository": repo, "branch": branch, "base_ref": base_ref,
                           "base_sha": "b" * 40, "commit_sha": commit, "status": "intended"})
        return obx / f"{did}.receipt.yaml"

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # (1) Intent без Receipt + PR на remote со СТРОГО совпавшей идентичностью -> reconciled + sha_verified
        f1 = root / "features" / "dlv"; f1.mkdir(parents=True)
        _rp1 = _mk_intent(f1, "did1", "dlv", "ai-ops/dlv", "cafe1234")
        _pro.reconcile_delivery = lambda root, branch: {"status": "found", "url": "https://x/pr/7",
                                                        "number": 7, "repository": "o/r",
                                                        "head_sha": "cafe1234", "base_ref": "main",
                                                        "pr_state": "open", "merged": False}
        try:
            _r = _reconcile_pending_delivery(root / "features", "dlv", root)
        finally:
            _pro.reconcile_delivery = _orig_rec
        _d1 = _ls.load_guarded(_rp1, kind="DeliveryReceipt")
        expect("v3.0.17: Intent+PR строгая идентичность (head.sha==commit) -> reconciled + sha_verified",
               _r and _r[0]["status"] == "reconciled" and _d1["state"] == "ok"
               and _d1["data"]["remote_sha"] == "cafe1234" and _d1["data"]["sha_verified"] is True
               and _d1["data"]["pr_url"] == "https://x/pr/7")
        expect("v3.0.17: повторная реконсиляция -> None (Receipt есть, дубля нет)",
               _reconcile_pending_delivery(root / "features", "dlv", root) is None)

        # (2) P0-1: PR той же ветки, но ДРУГОЙ commit -> НЕ подтверждаем старую доставку (mismatch)
        f2 = root / "features" / "dlv2"; f2.mkdir(parents=True)
        _rp2 = _mk_intent(f2, "did2", "dlv2", "ai-ops/dlv2", "cafe1234")
        _pro.reconcile_delivery = lambda root, branch: {"status": "found", "url": "https://x/pr/8",
                                                        "number": 8, "repository": "o/r",
                                                        "head_sha": "9999DIFF", "base_ref": "main"}
        try:
            _r2 = _reconcile_pending_delivery(root / "features", "dlv2", root)
        finally:
            _pro.reconcile_delivery = _orig_rec
        _d2 = _ls.load_guarded(_rp2, kind="DeliveryReceipt")
        expect("v3.0.17 P0: PR ветки с ДРУГИМ commit -> mismatch, НЕ засчитан как старая доставка",
               _r2 and _r2[0]["status"] == "mismatch"
               and _d2["state"] == "ok" and _d2["data"]["status"] == "mismatch"
               and _d2["data"]["sha_verified"] is False and _d2["data"]["remote_sha"] == "9999DIFF")

        # (3) PR отсутствует на remote -> not-delivered (внешнее действие не долетело)
        f3 = root / "features" / "dlv3"; f3.mkdir(parents=True)
        _rp3 = _mk_intent(f3, "did3", "dlv3", "ai-ops/dlv3", "cafe1234")
        _pro.reconcile_delivery = lambda root, branch: {"status": "absent", "repository": "o/r"}
        try:
            _r3 = _reconcile_pending_delivery(root / "features", "dlv3", root)
        finally:
            _pro.reconcile_delivery = _orig_rec
        _d3 = _ls.load_guarded(_rp3, kind="DeliveryReceipt")
        expect("v3.0.17: PR отсутствует -> receipt not-delivered (честно)",
               _r3 and _r3[0]["status"] == "reconciled-absent"
               and _d3["state"] == "ok" and _d3["data"]["status"] == "not-delivered")

        # (4) P1-2: Intent остался status='intended' (маркер outcome_unknown потерян) -> реконсиляция ВСЁ РАВНО
        # ловит его ПО ФАКТУ отсутствия Receipt (не по полю status).
        f4 = root / "features" / "dlv4"; f4.mkdir(parents=True)
        _rp4 = _mk_intent(f4, "did4", "dlv4", "ai-ops/dlv4", "cafe1234")   # status=intended
        _pro.reconcile_delivery = lambda root, branch: {"status": "found", "url": "https://x/pr/9",
                                                        "number": 9, "repository": "o/r",
                                                        "head_sha": "cafe1234", "base_ref": "main"}
        try:
            _r4 = _reconcile_pending_delivery(root / "features", "dlv4", root)
        finally:
            _pro.reconcile_delivery = _orig_rec
        expect("v3.0.17 P1-2: Intent 'intended' без Receipt всё равно реконсилируется (по факту, не по status)",
               _r4 and _r4[0]["status"] == "reconciled"
               and _ls.load_guarded(_rp4, kind="DeliveryReceipt")["state"] == "ok")

        # (5) unavailable (нет сети/токена) -> оставляем на следующий прогон, Receipt НЕ пишем
        f5 = root / "features" / "dlv5"; f5.mkdir(parents=True)
        _rp5 = _mk_intent(f5, "did5", "dlv5", "ai-ops/dlv5", "cafe1234")
        _pro.reconcile_delivery = lambda root, branch: {"status": "unavailable"}
        try:
            _r5 = _reconcile_pending_delivery(root / "features", "dlv5", root)
        finally:
            _pro.reconcile_delivery = _orig_rec
        expect("v3.0.17: unavailable -> Receipt НЕ пишется (остаётся на следующий прогон)",
               _r5 and _r5[0]["status"] == "unavailable"
               and _ls.load_guarded(_rp5, kind="DeliveryReceipt")["state"] == "absent")

    # v3.1.1 (fix-loop): провал проверки на 1-й попытке -> блокеры писателю -> фикс на итерации -> ready.
    # fail-closed сохранён: без фикса и без бюджета остался бы блок (проверяем и это).
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for _a in (("init", "-q"), ("config", "user.email", "t@t"), ("config", "user.name", "t")):
            subprocess.run(["git", "-C", td, *_a], capture_output=True)
        # v3.27.7: реальные репо гитигнорят байткод. Без .gitignore прогон pytest в fix-loop создаёт
        # __pycache__/*.pyc, которые засоряют git-дерево worktree -> prepare_mutated_tree=True ->
        # overall_status=error -> ready_for_pr=False (флаки: на Linux/CI __pycache__ попадал в учёт,
        # на macOS — нет; тот же .pyc ломал и security-домены). Фикстура теперь как настоящий репо.
        (root / ".gitignore").write_text("__pycache__/\n*.pyc\n.pytest_cache/\n", encoding="utf-8")
        (root / "m.py").write_text("def base():\n    return 1\n", encoding="utf-8")
        (root / "test_base.py").write_text("from m import base\n\ndef test_base():\n    assert base() == 1\n",
                                           encoding="utf-8")
        (root / "pyproject.toml").write_text(
            "[project]\nname='m'\nversion='0.1.0'\n[tool.setuptools]\npy-modules=['m']\n"
            "[tool.pytest.ini_options]\npythonpath=['.']\n", encoding="utf-8")
        subprocess.run(["git", "-C", td, "add", "-A"], capture_output=True)
        subprocess.run(["git", "-C", td, "commit", "-q", "-m", "i"], capture_output=True)
        _cur = subprocess.run(["git", "-C", td, "rev-parse", "--abbrev-ref", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
        _st = {"buggy": False, "test": False, "fixed": False}

        def _fl_prop(context):
            fix = ("упала" in context) or ("Устрани" in context)   # маркер fix-контекста
            if fix:
                if not _st["fixed"]:
                    _st["fixed"] = True
                    return {"op": "write", "path": "m.py", "content": "def base():\n    return 1\n\ndef g(x):\n    return x + 1\n"}
                return {"done": True}
            if not _st["buggy"]:
                _st["buggy"] = True
                return {"op": "write", "path": "m.py", "content": "def base():\n    return 1\n\ndef g(x):\n    return x\n"}
            if not _st["test"]:
                _st["test"] = True
                return {"op": "write", "path": "test_g.py",
                        "content": "from m import g\n\ndef test_g():\n    assert g(1) == 2\n"}
            return {"done": True}
        # v3.1.1: полный прогон fix-loop требует pytest (чтобы тест реально упал->починился). CI-набор
        # quality гоняет без pytest -> интеграционную часть выполняем ТОЛЬКО при наличии pytest (как PQ8 с
        # openspec); логику fix-context покрывают unit-проверки ниже (без внешних инструментов).
        import importlib.util as _ilu
        if _ilu.find_spec("pytest") is not None:
            _sig_fl = {"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]}
            _rfl = run("добавить g(x)=x+1 с тестом", dict(_sig_fl), root, engine="pipeline",
                       provider_name="test", proposer=_fl_prop, execute=True, feature="fixloop",
                       install_deps=False, base=_cur, review_fix_attempts=1)
            expect("v3.1.1 fix-loop: провал теста -> итерация по блокерам -> ready_for_pr=True (pytest есть)",
                   _rfl.get("ready_for_pr") is True and "test" not in (_rfl.get("gates") or {}).get("unmet", []))
            _jfl = _ls.journal_read(root / "features" / "fixloop" / "lifecycle-journal.jsonl")
            expect("v3.1.1 fix-loop: событие fix_attempt в журнале",
                   any(e.get("kind") == "fix_attempt" for e in _jfl["events"]))
        else:
            expect("v3.1.1 fix-loop: pytest недоступен -> интеграционный прогон пропущен (unit покрывает логику)",
                   True)
        # v3.1.1: fix-context feed'ит КОНКРЕТНЫЕ блокеры ревьюера (не общий текст), если они есть в трейсе
        _fx = _review_fix_context({"ready_for_pr": False, "gates": {"unmet": ["code_review"]},
                                   "reviews": [{"gate": "code_review", "status": "fail",
                                                "blockers": ["нет докстринга у g", "нет проверки типа"]}]})
        expect("v3.1.1 fix-loop: конкретные blockers ревьюера попадают в fix-context",
               _fx and "нет докстринга у g" in _fx and "нет проверки типа" in _fx)
        # fail-closed: не-фиксируемый блок (human-approval) -> fix-context None (не зацикливаем)
        expect("v3.1.1 fix-loop: human-approval блок -> None (не зацикливаем)",
               _review_fix_context({"ready_for_pr": False, "error": "нужно human approval деплоя"}) is None)

    assert ok, "перенесённый селфтест ai_ops_run: см. строки FAIL в выводе"
