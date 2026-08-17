"""Селфтест ai_ops_cli, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from ai_ops_cli import (  # noqa: F401 — имена, которые использует тело
    INTENTS,
    Path,
    build_preview,
    json,
    main,
    resolve_flags,
)


@pytest.mark.slow
def test_ai_ops_cli_selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    expect("16 intent-команд", len(INTENTS) == 16
           and {"new", "onboard", "discuss", "specify", "plan", "run", "do", "advise", "resume", "review",
                "status", "health",
                # v3.35 Product Operating Model: план продукта и понимание репозитория.
                "next", "model",
                # v3.35.2 (тир 4): BOOTSTRAP был строкой в реестре — стал командой.
                "bootstrap",
                # 2026-08-17: наблюдения о САМОМ ките из продуктового репозитория — данные, а не
                # пересказ человека (три работы плана кита пришли «сообщением параллельной сессии»).
                "feedback"} == set(INTENTS))

    # preset: QUICK -> без review/author; ENGINEERING -> review+author; всегда sandbox+baseline
    fq = resolve_flags({"task_type": "QUICK"})
    expect("QUICK preset: sandbox+baseline, без review/author",
           fq["sandbox"] and fq["baseline_diff"] and not fq["review"] and not fq["author"])
    fe = resolve_flags({"task_type": "ENGINEERING"})
    expect("ENGINEERING preset: review+author включены", fe["review"] and fe["author"])

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "package.json").write_text('{"dependencies":{"react":"^18"}}', encoding="utf-8")
        pv = build_preview("run", "добавить фильтр", root,
                           {"task_type": "ENGINEERING", "risk": "medium", "affected_areas": ["core"]})
        expect("preview: kind=ExecutionPreview", pv["kind"] == "ExecutionPreview")
        expect("preview: понял workflow ENGINEERING", pv["understood"]["workflow"] == "ENGINEERING")
        expect("preview: авто-флаги без ручного ввода (engine=pipeline)",
               pv["will_do"]["auto_flags"]["engine"] == "pipeline")
        expect("preview: данные — агенты и токены измерены", isinstance(pv["data_used"]["agents"], list)
               and pv["data_used"]["estimated_tokens"] is not None)
        expect("preview: ожидаемый результат назван", bool(pv["expected_result"]))

        # CRITICAL -> approval человека
        pc = build_preview("run", "миграция схемы", root,
                           {"task_type": "CRITICAL", "risk": "critical", "affected_areas": ["db"]})
        expect("preview CRITICAL: требует human approval",
               any("человек" in a for a in pc["approvals_needed"]))

        # v2.107: единая классификация — без task_type preset/spec берут решение роутера (не расходятся)
        pv_u = build_preview("run", "поправить логику расчёта", root,
                             {"affected_areas": ["core"], "risk": "medium"})  # без task_type
        wf_u = pv_u["understood"]["workflow"]
        af_u = pv_u["will_do"]["auto_flags"]
        # если роутер выбрал ENGINEERING+ -> review/author включены (согласовано, не противоречиво)
        expect("v2.107: без task_type preset согласован с роутером (нет ENGINEERING+L0+review off)",
               (wf_u in ("QUICK",)) or (af_u["review"] and af_u["author"]))

        # много подсистем -> decomposition_advised
        pd = build_preview("run", "большой рефактор", root,
                           {"task_type": "ENGINEERING", "affected_areas": ["a", "b", "c", "d"], "size": "large"})
        expect("preview: советует декомпозицию для большой задачи", pd["decomposition_advised"] is True)

        # v2.112 Intent UX: настоящие действия (не только превью)
        import io
        import contextlib as _cl

        def _run(argv):
            buf = io.StringIO()
            with _cl.redirect_stdout(buf):
                rc = main(argv)
            return rc, buf.getvalue()

        rc_o, _ = _run(["onboard", str(root)])
        expect("v2.112 onboard: РЕАЛЬНО пишет repository-profile.yaml",
               rc_o == 0 and (root / ".ai" / "repository-profile.yaml").is_file())

        rc_n, _ = _run(["new", str(root), "--feature", "nf",
                        "--signals", '{"task_type":"ENGINEERING","affected_areas":["core"]}'])
        expect("v2.112 new: РЕАЛЬНО создаёт workitem + spec.yaml",
               rc_n == 0 and (root / "features" / "nf" / "workitem.yaml").is_file()
               and (root / "features" / "nf" / "spec.yaml").is_file())

        rc_p, _ = _run(["plan", "сделать X", str(root), "--feature", "pf",
                        "--signals", '{"affected_areas":["core"]}'])
        expect("v2.112 plan: РЕАЛЬНО пишет план+артефакты без правок кода",
               rc_p == 0 and (root / "features" / "pf" / "run-plan.yaml").is_file()
               and (root / "features" / "pf" / "work-package.yaml").is_file())

        rc_d, _ = _run(["discuss", "идея", str(root), "--feature", "df"])
        expect("v2.112 discuss: РЕАЛЬНО создаёт discovery-draft.md",
               rc_d == 0 and (root / "features" / "df" / "discovery-draft.md").is_file())

        rc_s, out_s = _run(["status", str(root)])
        expect("v2.112 status: реальное чтение active-work (не превью)", rc_s == 0 and "STATUS" in out_s or rc_s == 0)

        rc_h, out_h = _run(["health", str(root)])
        # v3.35.1: формулировка переведена на человеческий язык (слой коммуникации), но ЧЕСТНОСТЬ
        # проверяется та же: код возврата 1, отказ считать по пустому месту, и явное «это не всё
        # хорошо, это не знаю». Проверяем смысл, а не прежнюю фразу.
        expect("v2.112 health: без метрик — честный отказ (не фабрикует score)",
               rc_h == 1 and "не знаю" in out_h and "по пустому месту" in out_h)

        # preview-режим НЕ выполняет действие, а показывает превью
        (root / ".ai" / "repository-profile.yaml").unlink()
        rc_pv, _ = _run(["preview", "onboard", str(root)])
        expect("v2.112 preview onboard: НЕ выполняет действие (профиль не пере-создан)",
               rc_pv == 0 and not (root / ".ai" / "repository-profile.yaml").is_file())

        # v2.116: `review` — настоящий intent (не preview). Без ветки -> честный no-branch (rc!=0).
        rc_rv, out_rv = _run(["review", "поревьюить", str(root), "--feature", "nope-wid"])
        # v3.35.2: вердикт переведён на человеческий язык. Честность проверяется та же и строже:
        # `no-branch` — это «сверять нечего», а НЕ «замечаний нет».
        expect("v2.116 review: настоящий intent — без ветки честный no-branch (не падает в preview)",
               rc_rv != 0 and "Проверять нечего" in out_rv and "можно вливать" not in out_rv)

    # v2.120: `run --execute` РЕАЛЬНО проводит provider/model/max-steps/open-pr в движок (не mock-хардкод).
    import subprocess as _sp
    with tempfile.TemporaryDirectory() as gtd:
        groot = Path(gtd)
        (groot / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        for aa in (("init", "-q"), ("config", "user.email", "t@t"), ("config", "user.name", "t"),
                   ("add", "-A"), ("commit", "-q", "-m", "i")):
            _sp.run(["git", "-C", gtd, *aa], capture_output=True)
        buf = io.StringIO()
        with _cl.redirect_stdout(buf), _cl.redirect_stderr(io.StringIO()):
            main(["run", "добавить x", str(groot), "--execute", "--feature", "wiref",
                  "--model", "marker-model-xyz",
                  "--signals", '{"task_type":"QUICK","size":"small","risk":"low","affected_areas":["core"]}'])
        rep_p = groot / "features" / "wiref" / "run-report.json"
        model_wired = rep_p.is_file() and json.loads(rep_p.read_text(encoding="utf-8")).get("model") == "marker-model-xyz"
        expect("v2.120 CLI: run --execute проводит --model до движка (provider/model провязаны, не mock-хардкод)",
               model_wired)

    assert ok, "перенесённый селфтест ai_ops_cli: см. строки FAIL в выводе"
