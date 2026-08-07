"""Селфтест workpackage_executor, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from workpackage_executor import (  # noqa: F401 — имена, которые использует тело
    Path,
    _aggregate_close_security,
    _aggregate_code_review,
    _collect_base_checks_at,
    _git,
    _hard_stop,
    _ordered,
    _pkg_hash,
    _plan_hash,
    _validate_sequence_plan_schema,
    execute_sequence,
    json,
    retry_package,
)


@pytest.mark.slow
def test_workpackage_executor_selftest():
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

    def _pass_reviewer(prompt):
        # v3.0.1: mock-ревьюер pass. Для security-промпта (SecurityVerdict v2) парсит применимые
        # домены из промпта и эмитит domain_results по каждому — иначе строгий контракт отклонит.
        import re as _re
        import json as _json
        p = prompt or ""
        # v3.0.11: ревьюер СНАЧАЛА реально читает изменённый файл (реальный trace), затем выносит pass —
        # иначе блокирующий гейт (code_review/ux_review) не закрывается по 0-read рубер-стампу, а security-
        # evidence code-read не сойдётся с trace. Файл берём из seeded-диффа (fallback calc.py).
        _cand = _re.search(r"\+\+\+ b/(\S+)", p)
        _path = _cand.group(1) if _cand else "calc.py"
        if f"--- {_path} ---" not in p:                      # ещё не читал -> читаем
            return _json.dumps({"op": "read", "path": _path})
        res = {"kind": "reviewer-result", "status": "pass", "checks": [{"id": "ok", "status": "pass"}]}
        m = _re.search(r"применимым доменам:\s*([^\n(]+)", p)
        if m:
            doms = [d.strip() for d in m.group(1).split(",") if d.strip()]
            if doms:
                # evidence code-read ссылается на РЕАЛЬНО прочитанный файл (сверка с trace, без basename-fallback)
                res["domain_results"] = [{"domain": d, "status": "pass",
                                          "checks": [{"id": f"{d}_ok", "status": "pass"}],
                                          "evidence": [{"type": "code-read", "path": _path, "lines": "1-10"}]}
                                         for d in doms]
        return _json.dumps(res, ensure_ascii=False)
    reviewer = _pass_reviewer

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
        # v3.0.8 (finding аудита P0.2): sequence_base_sha записан durable СРАЗУ (в том же плане, не best-effort)
        import yaml as _yy
        _plan = _yy.safe_load((root / "features" / "seq" / "sequence-plan.yaml").read_text(encoding="utf-8"))
        expect("v3.0.8: sequence_base_sha + base_ref в durable-плане сразу (не дописан позже)",
               bool(_plan.get("sequence_base_sha")) and bool(_plan.get("base_ref")))
        # v3.0.8 (finding аудита P0.3): ПОВРЕЖДЁННЫЙ SequencePlan -> lifecycle-corrupted (halt), НЕ перезапись
        _corrupt_root = None
        with tempfile.TemporaryDirectory() as _tdc:
            _rc = Path(_tdc); cur_c = mkrepo(_tdc)
            _pk = atomic_planner.decompose(sig, wid="seqc", child_root=_rc)["work_packages"]
            (_rc / "features" / "seqc").mkdir(parents=True, exist_ok=True)
            (_rc / "features" / "seqc" / "sequence-plan.yaml").write_text("{ это: [не, валидный, yaml", encoding="utf-8")
            _before = (_rc / "features" / "seqc" / "sequence-plan.yaml").read_text(encoding="utf-8")
            seq_c = execute_sequence("x", sig, _rc, _pk, prop_for, feature="seqc", base=cur_c,
                                     author=True, author_proposer=author, review=True, reviewer_proposer=reviewer)
            _after = (_rc / "features" / "seqc" / "sequence-plan.yaml").read_text(encoding="utf-8")
            expect("v3.0.8 P0.3: повреждённый SequencePlan -> lifecycle-corrupted, 0 пакетов, файл НЕ перезаписан",
                   "lifecycle-corrupted" in (seq_c.get("error") or "") and not seq_c.get("packages")
                   and _after == _before and seq_c.get("corrupt_sha256"))
        expect("v2.124: у каждого пакета снимок lifecycle (run-plan.yaml в своём каталоге)",
               all((root / "features" / "seq" / "work-packages" / p["id"] / "run-plan.yaml").is_file()
                   for p in seq["packages"]))
        expect("v2.124: агрегатный вердикт (aggregate_ready) в отчёте", "aggregate_ready" in seq)
        expect("v2.124: aggregate verify на финальном SHA выполнен (verified)",
               (seq.get("aggregate") or {}).get("verified") is True
               and (seq.get("aggregate") or {}).get("final_sha") == seq["final_sha"])

        # v3.0-rc4 (P0.4): после полного прогона HEAD ветки на пакете 3 -> resume с пакета 2 запрещён
        # (ветка ушла вперёд checkpoint предшественника).
        seq_drift = execute_sequence("x", sig, root, pkgs, prop_for, feature="seq", base=cur,
                                     author=True, author_proposer=author, review=True, reviewer_proposer=reviewer,
                                     resume_from=pkgs[1]["id"])
        expect("v3.0-rc4 resume (P0.4): HEAD не на checkpoint предшественника -> error",
               "error" in seq_drift and "checkpoint" in (seq_drift.get("error") or "").lower())
        # валидный resume: сбрасываем ветку на checkpoint пакета 1, затем resume с пакета 2
        _git(root / ".ai" / "worktrees" / "seq", "reset", "--hard", seq["packages"][0]["sha"])
        buf2 = io.StringIO()
        with contextlib.redirect_stderr(buf2):
            seq_r = execute_sequence("большой рефактор", sig, root, pkgs, prop_for, feature="seq",
                                     base=cur, author=True, author_proposer=author,
                                     review=True, reviewer_proposer=reviewer,
                                     resume_from=pkgs[1]["id"])
        skipped = [p for p in seq_r["packages"] if p.get("status") == "resumed-skip"]
        expect("v2.124/rc4 resume: валидный checkpoint -> пакет 1 resumed-skip, дальше исполняется",
               "error" not in seq_r and seq_r.get("resumed_from") == pkgs[1]["id"] and len(skipped) == 1
               and skipped[0]["id"] == pkgs[0]["id"] and skipped[0].get("sha"))
        # v3.0-rc2 (P0.3): неизвестный resume_from -> ОШИБКА, не тихий старт с нуля
        seq_bad = execute_sequence("x", sig, root, pkgs, prop_for, feature="seq", base=cur,
                                   resume_from="pkg-НЕТ-ТАКОГО")
        expect("v3.0-rc2 resume: неизвестный resume_from -> error (не старт с нуля)",
               "error" in seq_bad and seq_bad["executed_all"] is False and not seq_bad["packages"])
        # v3.0-rc4 (P0.3): дрейф SequencePlan (planner перестроил пакеты) -> resume запрещён
        pkgs_drift = [dict(p) for p in pkgs]
        pkgs_drift[0] = {**pkgs_drift[0], "scope": ["ДРУГАЯ-ПОДСИСТЕМА"]}   # тот же id, другой scope -> др. hash
        seq_pd = execute_sequence("x", sig, root, pkgs_drift, prop_for, feature="seq", base=cur,
                                  resume_from=pkgs[1]["id"])
        expect("v3.0-rc4 resume (P0.3): дрейф SequencePlan -> error (нужен replan)",
               "error" in seq_pd and "дрейф" in (seq_pd.get("error") or "").lower())
        # v3.0.10 (finding аудита P1): дрейф ловится и БЕЗ resume_from (сохранённый план — иммутабелен).
        seq_pd2 = execute_sequence("x", sig, root, pkgs_drift, prop_for, feature="seq", base=cur)
        expect("v3.0.10: дрейф SequencePlan БЕЗ resume_from -> error (план иммутабелен)",
               "error" in seq_pd2 and "дрейф" in (seq_pd2.get("error") or "").lower())

        # v3.0.10 (finding аудита P1): ПОЛНАЯ integrity-валидация SequencePlan (чистая функция).
        def _valid_plan(wid="seq"):
            _o = _ordered([{"id": "WP1", "order": 1, "depends_on": [], "scope": "a", "write_scope": ["."]},
                           {"id": "WP2", "order": 2, "depends_on": ["WP1"], "scope": "b", "write_scope": ["."]}])
            return {"schema_version": 1, "kind": "SequencePlan", "workitem_id": wid, "total": 2,
                    "plan_hash": _plan_hash(_o), "base_ref": "main", "sequence_base_sha": "deadbeef",
                    "packages": [{"id": p["id"], "order": p["order"], "depends_on": p["depends_on"],
                                  "scope": p["scope"], "write_scope": p["write_scope"],
                                  "pkg_hash": _pkg_hash(p)} for p in _o]}
        expect("v3.0.10 plan-integrity: валидный план -> None",
               _validate_sequence_plan_schema(_valid_plan(), expected_wid="seq") is None)
        expect("v3.0.10 plan-integrity: чужой workitem_id -> ошибка",
               "чужой" in (_validate_sequence_plan_schema(_valid_plan("OTHER"), expected_wid="seq") or ""))
        expect("v3.0.10 plan-integrity: неподдерживаемая schema_version -> ошибка",
               "schema_version" in (_validate_sequence_plan_schema({**_valid_plan(), "schema_version": 2},
                                                                    expected_wid="seq") or ""))
        def _reseal(plan):   # пересчитать pkg_hash каждого пакета + общий plan_hash (чтобы тест изолировал
            for _p in plan["packages"]:                     # СТРУКТУРНОЕ нарушение, а не дрейф хэша)
                _p["pkg_hash"] = _pkg_hash(_p)
            plan["plan_hash"] = _plan_hash(_ordered(plan["packages"]))
            return plan
        _dup = _valid_plan(); _dup["packages"][1]["id"] = "WP1"; _reseal(_dup)
        expect("v3.0.10 plan-integrity: дубль package id -> ошибка",
               "дубли package id" in (_validate_sequence_plan_schema(_dup, expected_wid="seq") or ""))
        _dupord = _valid_plan(); _dupord["packages"][1]["order"] = 1; _reseal(_dupord)
        expect("v3.0.10 plan-integrity: дубль order -> ошибка",
               "дубли order" in (_validate_sequence_plan_schema(_dupord, expected_wid="seq") or ""))
        _baddep = _valid_plan(); _baddep["packages"][1]["depends_on"] = ["WP-NONE"]; _reseal(_baddep)
        expect("v3.0.10 plan-integrity: depends_on на несуществующий пакет -> ошибка",
               "несуществующего" in (_validate_sequence_plan_schema(_baddep, expected_wid="seq") or ""))
        _cyc = _valid_plan(); _cyc["packages"][0]["depends_on"] = ["WP2"]; _reseal(_cyc)   # WP1<->WP2 цикл
        expect("v3.0.10 plan-integrity: цикл зависимостей -> ошибка",
               "цикл" in (_validate_sequence_plan_schema(_cyc, expected_wid="seq") or ""))
        _badpk = _valid_plan(); _badpk["packages"][0]["pkg_hash"] = "0" * 16
        expect("v3.0.10 plan-integrity: подменённый pkg_hash -> ошибка",
               "pkg_hash не сходится" in (_validate_sequence_plan_schema(_badpk, expected_wid="seq") or ""))
        _badph = _valid_plan(); _badph["plan_hash"] = "0" * 16
        expect("v3.0.10 plan-integrity: подменённый plan_hash -> ошибка",
               "plan_hash не сходится" in (_validate_sequence_plan_schema(_badph, expected_wid="seq") or ""))
        # v3.0-rc2 (P0.3): пакет до resume_from без подтверждённого снимка -> error (не добавляем в completed)
        import tempfile as _tf
        with _tf.TemporaryDirectory() as td_e:
            re = Path(td_e); cur_e = mkrepo(td_e)
            pkgs_e = atomic_planner.decompose(sig, wid="seqe", child_root=re)["work_packages"]
            seq_e = execute_sequence("x", sig, re, pkgs_e, prop_for, feature="seqe", base=cur_e,
                                     resume_from=pkgs_e[1]["id"])   # снимков нет — пакет 1 не подтверждён
            expect("v3.0-rc2 resume: неподтверждённый пропущенный пакет -> error (не в completed)",
                   "error" in seq_e and pkgs_e[0]["id"] not in seq_e.get("completed", []))

        # v3.0-rc12 (finding живого sequential): исключение провайдера/инфры (ConnectionReset и т.п.)
        # ПОСЛЕ исчерпания ретраев НЕ роняет всю транзакцию traceback'ом — пакет честно фейлится
        # (infra-error), цепочка hard-stop, последующие пакеты НЕ исполняются, снимок пакета сохранён.
        with _tf.TemporaryDirectory() as td_x:
            rx = Path(td_x); cur_x = mkrepo(td_x)
            pkgs_x = atomic_planner.decompose(sig, wid="seqx", child_root=rx)["work_packages"]
            def prop_boom(pkg):
                return lambda c: {"done": True}          # не достигается — author падает раньше
            def boom_author(prompt):                     # воспроизводит живой сбой: ConnectionReset в author-вызове
                raise ConnectionResetError("[Errno 54] Connection reset by peer")
            seq_x = execute_sequence("x", sig, rx, pkgs_x, prop_boom, feature="seqx",
                                     base=cur_x, author=True, author_proposer=boom_author, review=False)
            p0 = seq_x["packages"][0] if seq_x.get("packages") else {}
            expect("v3.0-rc12: исключение провайдера -> НЕ traceback, пакет 1 честно остановлен",
                   bool(p0.get("stop_reason")) and "error" in (p0.get("stop_reason") or ""))
            # v3.0-rc13 (P1): типизированный failure envelope — ConnectionReset -> network, retryable
            expect("v3.0-rc13: failure классифицирован (network/retryable), не blanket infra-error",
                   (p0.get("failure") or {}).get("failure_class") == "network"
                   and (p0.get("failure") or {}).get("retryable") is True
                   and (p0.get("failure") or {}).get("exception_type") == "ConnectionResetError"
                   and (p0.get("failure") or {}).get("traceback_hash"))
            expect("v3.0-rc12: цепочка стоп на пакете 1, пакеты 2/3 НЕ исполнены (durable stop)",
                   seq_x.get("stopped_at") == pkgs_x[0]["id"] and len(seq_x["packages"]) == 1
                   and seq_x["executed_all"] is False and seq_x["ready_all"] is False)
            expect("v3.0-rc12: per-package снимок пакета 1 сохранён (транзакция не потеряла состояние)",
                   (rx / "features" / "seqx" / "work-packages" / pkgs_x[0]["id"] / "report.json").is_file())

        # v2.124.1 (finding живого прогона): с write_scope_for + author артефакты движка (.ai/runplan,
        # openspec) НЕ должны ловиться как scope-violation — write_scope ограничивает КОД, не артефакты.
        def prop_ws(pkg):
            sub = (pkg.get("scope") or ["core"])[0]
            it = iter([{"op": "write", "path": f"src/{sub}/mod.py", "content": "x = 1\n"}, {"done": True}])
            return lambda c: next(it)
        buf3 = io.StringIO()
        with contextlib.redirect_stderr(buf3):
            seq_ws = execute_sequence("рефактор со scope", sig, root, pkgs, prop_ws, feature="seqws",
                                      base=cur, author=True, author_proposer=author,
                                      review=True, reviewer_proposer=reviewer,
                                      write_scope_for=lambda pkg: pkg.get("write_scope"))
        expect("v2.124.1: authored-артефакты движка (.ai/openspec) НЕ ловятся как scope-violation",
               not any("scope-violation" in (p.get("stop_reason") or "") for p in seq_ws["packages"]))
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
               _hard_stop({"commit": {"sha": "a"}, "reviews": [{"gate": "code_review", "status": "fail"}]}) == "reviewer-blocked")
        # v3.0-rc13 (P0): reviewer WARN на блокирующем гейте (closed_as=blocked) ТОЖЕ останавливает —
        # это и был живой rc11-результат (warn -> gate fail -> ready_for_pr=false), раньше проскакивал.
        expect("v3.0-rc13 _hard_stop: reviewer WARN-blocking (closed_as=blocked) -> stop",
               _hard_stop({"commit": {"sha": "a"},
                           "reviews": [{"gate": "code_review", "status": "warn", "closed_as": "blocked"}]}) == "reviewer-blocked")
        expect("v3.0-rc13 _hard_stop: итоговый code_review-гейт fail с вынесенным вердиктом -> stop",
               _hard_stop({"commit": {"sha": "a"}, "reviews": [],
                           "gates": {"gate_results": [{"gate": "code_review", "status": "fail",
                                     "evidence": ["independent reviewer verdict @ abc"]}]}}) == "reviewer-blocked")
        expect("v3.0-rc13 _hard_stop: reviewer WARN на НЕблокирующем (closed_as!=blocked) -> НЕ стоп",
               _hard_stop({"commit": {"sha": "a"},
                           "reviews": [{"gate": "code_review", "status": "warn", "closed_as": "warn"}]}) is None)
        expect("v2.120 _hard_stop: scope-violation (write вне scope) -> stop",
               _hard_stop({"commit": {"sha": "a"}, "loop": {"denied_reasons": ["'x' вне write_scope ['src']"]}}) == "scope-violation")
        expect("v2.120 _hard_stop: awaiting evidence (гейты unmet, но коммит есть, без fail) -> НЕ стоп",
               _hard_stop({"commit": {"sha": "a"}, "gates": {"blocked": True, "unmet": ["requirements"]}}) is None)
        expect("v2.120 _hard_stop: заблокированный push (не scope) -> НЕ scope-violation",
               _hard_stop({"commit": {"sha": "a"}, "loop": {"denied_reasons": ["git push запрещён политикой"]}}) is None)
        # v3.0-rc2 (P0.2): security-стоп по РЕАЛЬНОМУ вердикту (pack blocked / security-гейт fail),
        # а не по недостижимому overall=="fail". Иначе security-блок проходил как awaiting evidence.
        expect("v3.0-rc2 _hard_stop: security_scan blocked -> стоп",
               _hard_stop({"commit": {"sha": "a"}, "security_scan": {"overall": "blocked"}}) == "security-fail")
        def _g(blk):
            return {"commit": {"sha": "a"}, "gates": {"gate_results": [
                {"gate": "security", "status": "fail", "blockers": [blk]}]}}
        expect("v3.0-rc4 _hard_stop: security-гейт fail — нет ApprovalRecord -> стоп",
               _hard_stop(_g("dependencies: нет валидного ApprovalRecord")) == "security-gate-fail")
        expect("v3.0-rc4 _hard_stop: security-гейт fail — сбой сканера (fail-closed) -> стоп",
               _hard_stop(_g("security scan упал (fail-closed): boom")) == "security-gate-fail")
        expect("v3.0-rc4 _hard_stop: security-гейт fail — reviewer не вынес pass -> стоп",
               _hard_stop(_g("security-reviewer не вынес pass")) == "security-gate-fail")
        expect("v3.0-rc4 _hard_stop: needs_review без поданного ревьюера (awaiting) -> НЕ стоп",
               _hard_stop({"commit": {"sha": "a"}, "security_scan": {"overall": "needs_review"},
                           "gates": {"gate_results": [{"gate": "security", "status": "fail",
                           "blockers": ["нужен независимый security-reviewer/человек по доменам: input_validation"]}]}}) is None)

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
        expect("v2.120/rc13 executor: reviewer FAIL на пакете 1 -> цепочка остановлена (reviewer-blocked)",
               seqr["stopped_at"] == pkgs[0]["id"] and seqr["executed_all"] is False
               and seqr["packages"][0]["stop_reason"] == "reviewer-blocked" and pkgs[2]["id"] not in ids_seen)

    # v3.0-rc13 (P0): reviewer WARN-на-блокирующем (closed_as=blocked) тоже стоп — живой rc11-случай
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); cur = mkrepo(td)
        sig = {"task_type": "ENGINEERING", "size": "large", "risk": "low",
               "affected_areas": ["catalog", "orders", "billing"]}
        pkgs = atomic_planner.decompose(sig, wid="seqw", child_root=root)["work_packages"]
        def prop_for(pkg):
            it = iter([{"op": "write", "path": f"src/{pkg['id']}.py", "content": "x=1\n"}, {"done": True}])
            return lambda c: next(it)
        warn_reviewer = lambda p: ('{"kind":"reviewer-result","status":"warn",'
                                   '"checks":[{"id":"c","status":"warn"}],"blockers":["сомнение по API"]}')
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            seqw = execute_sequence("рефактор с warn-ревью", sig, root, pkgs, prop_for, feature="seqw",
                                    base=cur, author=True, author_proposer=author,
                                    review=True, reviewer_proposer=warn_reviewer)
        ids_w = [p["id"] for p in seqw["packages"]]
        expect("v3.0-rc13 executor: reviewer WARN-blocking на пакете 1 -> цепочка стоп, пакет 3 не стартует",
               seqw["stopped_at"] == pkgs[0]["id"] and seqw["executed_all"] is False
               and seqw["packages"][0]["stop_reason"] == "reviewer-blocked" and pkgs[2]["id"] not in ids_w)

    # v3.0-rc13 (P1): доверенный retry_package — архив попытки + reset на checkpoint предшественника
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); cur = mkrepo(td)
        sig = {"task_type": "ENGINEERING", "size": "large", "risk": "low",
               "affected_areas": ["catalog", "orders", "billing"]}
        pkgs = atomic_planner.decompose(sig, wid="seqrt", child_root=root)["work_packages"]
        def prop_for(pkg):
            it = iter([{"op": "write", "path": f"src/{pkg['id']}.py", "content": "x=1\n"}, {"done": True}])
            return lambda c: next(it)
        pass_reviewer = _pass_reviewer
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            seqrt = execute_sequence("рефактор для retry", sig, root, pkgs, prop_for, feature="seqrt",
                                     base=cur, author=True, author_proposer=author,
                                     review=True, reviewer_proposer=pass_reviewer)
        p1_sha = seqrt["packages"][0].get("sha")
        wt = root / ".ai" / "worktrees" / "seqrt"
        expect("v3.0-rc13 retry: предусловие — пакеты исполнены, снимок sequence-plan с базой",
               p1_sha and (root / "features" / "seqrt" / "sequence-plan.yaml").is_file())
        rt = retry_package(root, "seqrt", pkgs[1]["id"])
        head_after = _git(wt if wt.is_dir() else root, "rev-parse", "HEAD")[1]
        expect("v3.0-rc13 retry: reset ветки на checkpoint предшественника (пакет 1 SHA), без ручного git",
               rt.get("ok") is True and rt.get("checkpoint") == p1_sha and head_after == p1_sha
               and rt.get("predecessor") == pkgs[0]["id"])
        expect("v3.0-rc13 retry: проваленная попытка пакета 2 заархивирована (история не потеряна)",
               (root / "features" / "seqrt" / "work-packages" / pkgs[1]["id"] / "attempts" / "attempt-1" / "report.json").is_file())
        expect("v3.0-rc13 retry: неизвестный пакет -> честная ошибка (не тихий reset)",
               retry_package(root, "seqrt", "НЕТ-ТАКОГО").get("ok") is False)
        # v3.0.2 (finding аудита P0): resume/retry с ДРУГОЙ base (цепочка зафиксирована на base_ref) ->
        # base-contract-drift, не молчаливая смена контракта доставки. SequencePlan seqrt.base_ref==cur.
        seq_bd = execute_sequence("другая база", sig, root, pkgs, prop_for, feature="seqrt",
                                  base="release-xyz", author=True, author_proposer=author,
                                  review=True, reviewer_proposer=pass_reviewer,
                                  resume_from=pkgs[1]["id"])
        expect("v3.0.2 base-contract-drift: resume с другой base -> честная ошибка (нужен replan)",
               "error" in seq_bd and "base-contract-drift" in (seq_bd.get("error") or ""))

    # v3.0-rc16 (finding аудита P0): retry БЕЗ выделенного worktree -> fail-closed; основной checkout
    # (HEAD + рабочее дерево) НЕ ТРОГАЕТСЯ. Раньше vroot фолбэчил на child_root и reset --hard мог
    # сбросить основную ветку.
    import shutil as _sh_test
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); cur = mkrepo(td)
        sig = {"task_type": "ENGINEERING", "size": "large", "risk": "low",
               "affected_areas": ["catalog", "orders", "billing"]}
        pkgs = atomic_planner.decompose(sig, wid="seqsafe", child_root=root)["work_packages"]
        def prop_for(pkg):
            it = iter([{"op": "write", "path": f"src/{pkg['id']}.py", "content": "x=1\n"}, {"done": True}])
            return lambda c: next(it)
        pass_reviewer = _pass_reviewer
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            execute_sequence("рефактор safe-retry", sig, root, pkgs, prop_for, feature="seqsafe",
                             base=cur, author=True, author_proposer=author,
                             review=True, reviewer_proposer=pass_reviewer)
        # снимок основного checkout ДО retry
        main_head_before = _git(root, "rev-parse", "HEAD")[1]
        main_status_before = _git(root, "status", "--porcelain")[1]
        # УДАЛЯЕМ выделенный worktree (симулируем повреждение/отсутствие)
        wt = root / ".ai" / "worktrees" / "seqsafe"
        _git(root, "worktree", "remove", "--force", str(wt))
        _sh_test.rmtree(wt, ignore_errors=True)
        rt_unsafe = retry_package(root, "seqsafe", pkgs[1]["id"])
        main_head_after = _git(root, "rev-parse", "HEAD")[1]
        main_status_after = _git(root, "status", "--porcelain")[1]
        expect("v3.0-rc16 retry-safety: нет worktree -> fail-closed (ok=False)",
               rt_unsafe.get("ok") is False and "fail-closed" in (rt_unsafe.get("error") or ""))
        expect("v3.0-rc16 retry-safety: основной checkout НЕ тронут (HEAD + рабочее дерево неизменны)",
               main_head_after == main_head_before and main_status_after == main_status_before)

    # v3.0-rc20 (finding аудита P0): aggregate code_review — ТОЛЬКО явный валидный pass; no-verdict/invalid
    # -> ok=False (раньше fail-OPEN). И _collect_base_checks_at: несуществующая база -> None (не доказан).
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); cur = mkrepo(td)
        # no-verdict reviewer (всегда невалидный текст) -> code_review не закрыт -> ok=False
        nover = lambda p: "я не буду выносить структурный вердикт, просто текст"
        ok_nv, _ = _aggregate_code_review(root, cur, cur, {"task_type": "ENGINEERING"}, nover, True)
        expect("v3.0-rc20 aggregate-review: no-verdict/invalid -> ok=False (не fail-open)", ok_nv is False)
        # без ревью (не запрошено) -> ok=True (per-package ревью уже было)
        ok_nr, _ = _aggregate_code_review(root, cur, cur, {}, None, False)
        expect("v3.0-rc20 aggregate-review: без ревью -> ok=True (не блокируем на этом уровне)", ok_nr is True)
        # baseline provenance: несуществующий base_sha -> None (baseline НЕ доказан -> нет fallback)
        expect("v3.0-rc20 baseline-provenance: несуществующая база -> None (не доказан)",
               _collect_base_checks_at(root, "0" * 40, False) is None)
        _res = _collect_base_checks_at(root, _git(root, "rev-parse", "HEAD")[1], False)
        expect("v3.0-rc20 baseline-provenance: валидная база -> proven=True + HEAD==base",
               isinstance(_res, dict) and _res.get("proven") is True)

    # v3.8.3-rc2 (#4/#4b): enforcement #5 на АГРЕГАТЕ — общий reviewer НЕ закрывает; qualified-судья ИЛИ
    # человеко-approval на ИНТЕГРАЦИОННОМ SHA закрывают. Прямой unit на _aggregate_close_security.
    import approvals as _appr_t
    _isha = "a" * 40
    _agg_nr = {"overall": "needs_review", "needs_review": ["rate_limiting"], "results": []}
    _gen_reviewer = lambda *a, **k: "VERDICT: pass"   # общий code-reviewer (не должен закрывать security)
    # (i) общий reviewer_proposer + НЕТ qualified-судьи, НЕТ человека -> остаётся needs_review
    _r_i, _ = _aggregate_close_security(dict(_agg_nr), Path("."), None, _isha, {}, _gen_reviewer, True,
                                        security_reviewer_proposer=None, strict_judge_qualified=False,
                                        wid=None, child_root=None)
    expect("rc2 #4: общий code-reviewer НЕ закрывает aggregate security (остаётся needs_review)",
           _r_i.get("overall") == "needs_review" and _r_i.get("closed_by") is None)
    with tempfile.TemporaryDirectory() as _hd:
        _appr_t.write_record(_hd, "seq-agg", approval="rate_limiting", approved_by="human@owner",
                             scope="security rate_limiting", reason="человек одобрил integration-SHA",
                             created_at="2026-07-29", binds_to=_isha, expires_at="2026-12-31",
                             risk="high", source="human")
        # (ii) человеко-approval, привязанный К ИНТЕГРАЦИОННОМУ SHA -> закрывает
        _r_ii, _ = _aggregate_close_security(dict(_agg_nr), Path(_hd), None, _isha, {}, _gen_reviewer, True,
                                             security_reviewer_proposer=None, strict_judge_qualified=False,
                                             wid="seq-agg", child_root=_hd)
        expect("rc2 #4b: человеко-approval на integration-SHA закрывает aggregate security",
               _r_ii.get("overall") == "clear" and _r_ii.get("closed_by") == "human-approval-integration-sha")
        # (iii) тот же approval, но проверяем на ДРУГОМ integration-SHA -> binds_to mismatch -> НЕ закрывает
        _r_iii, _ = _aggregate_close_security(dict(_agg_nr), Path(_hd), None, "b" * 40, {}, _gen_reviewer, True,
                                              security_reviewer_proposer=None, strict_judge_qualified=False,
                                              wid="seq-agg", child_root=_hd)
        expect("rc2 #4b: approval на ДРУГОМ SHA -> aggregate security НЕ закрыт (SHA-binding)",
               _r_iii.get("overall") == "needs_review")

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

    assert ok, "перенесённый селфтест workpackage_executor: см. строки FAIL в выводе"
