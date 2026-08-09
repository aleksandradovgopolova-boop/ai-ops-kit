"""Селфтест deploy_readiness, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from deploy_readiness import (  # noqa: F401 — имена, которые использует тело
    MATURITY,
    Path,
    assess,
    declaration_template,
    gate_status,
    should_run_deploy_readiness,
    summary_line,
)


@pytest.mark.slow
def test_deploy_readiness_selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    # --- применимость гейта ----------------------------------------------------------------------
    run, why = should_run_deploy_readiness([], {"deployment_change": True})
    expect("сигнал deployment_change -> гейт применим", run and "deployment_change" in why)
    expect("сигнал new_service -> применим", should_run_deploy_readiness([], {"new_service": True})[0])
    expect("DEPLOY-задача -> применим", should_run_deploy_readiness([], {"task_type": "deploy"})[0])
    expect("изменён Dockerfile -> применим", should_run_deploy_readiness(["Dockerfile"])[0])
    expect("изменён workflow -> применим",
           should_run_deploy_readiness([".github/workflows/deploy.yml"])[0])
    expect("изменён terraform -> применим", should_run_deploy_readiness(["infra/main.tf"])[0])
    expect("изменён k8s-манифест -> применим", should_run_deploy_readiness(["k8s/app.yaml"])[0])
    run, why = should_run_deploy_readiness(["src/app.ts"], {"task_type": "ENGINEERING"})
    expect("обычная правка кода -> гейт НЕприменим (honest skip)", not run and "неприменим" in why)

    # --- лестница --------------------------------------------------------------------------------
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        rep = assess(root)
        expect("пустой репозиторий -> absent", rep["deploy_maturity"] == "absent")
        expect("absent не маскируется под «ок» (норма для библиотеки)",
               "НОРМА" in rep["reason"] and "норма" in summary_line(root))
        expect("absent -> гейт при сигнале деплоя FAIL", gate_status("absent")[0] == "fail")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "Dockerfile").write_text("FROM alpine\n", encoding="utf-8")
        rep = assess(root)
        expect("Dockerfile без исполняемого пути -> configured",
               rep["deploy_maturity"] == "configured" and rep["config_markers"] == ["Dockerfile"])
        expect("configured -> гейт FAIL (задеплоить нечем)", gate_status("configured")[0] == "fail")
        expect("Dockerfile без пути -> путь неизвестен, платформенных подсказок нет",
               rep["deploy_path_unknown"] and rep["platform_hints"] == []
               and "НЕ следует" not in rep["reason"] and "НЕТ" in rep["reason"])

        # появляется исполняемый путь
        (root / "deploy.sh").write_text("#!/bin/sh\necho ship\n", encoding="utf-8")
        rep = assess(root)
        expect("deploy-скрипт -> runnable",
               rep["deploy_maturity"] == "runnable" and "deploy.sh" in rep["runnable_paths"])
        expect("runnable без отката -> находка no_rollback_declared",
               any(f["rule"] == "no_rollback_declared" for f in rep["findings"]))
        expect("runnable -> гейт PASS с оговоркой", gate_status("runnable")[0] == "pass")
        expect("summary_line сообщает про отсутствующий откат",
               "откат не объявлен" in summary_line(root))

        # откат + evidence -> verified
        (root / "rollback.sh").write_text("#!/bin/sh\necho undo\n", encoding="utf-8")
        rec = root / ".ai" / "runtime" / "deploy"
        rec.mkdir(parents=True)
        (rec / "DEP-001.json").write_text('{"environment": "production"}', encoding="utf-8")
        rep = assess(root)
        expect("runnable + откат + evidence -> verified", rep["deploy_maturity"] == "verified")
        expect("verified -> гейт PASS", gate_status("verified")[0] == "pass")
        expect("источники отката перечислены", "rollback.sh" in rep["rollback_sources"])

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        rec = root / ".ai" / "runtime" / "deploy"
        rec.mkdir(parents=True)
        (rec / "DEP-001.json").write_text("{}", encoding="utf-8")
        rep = assess(root)
        expect("записи поставок без исполняемого пути -> находка records_without_path",
               any(f["rule"] == "records_without_path" for f in rep["findings"]))
        expect("записи без пути НЕ дают verified", rep["deploy_maturity"] != "verified")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "package.json").write_text(
            '{"scripts": {"deploy:prod": "vercel --prod", "rollback": "vercel rollback"}}',
            encoding="utf-8")
        rep = assess(root)
        expect("npm-скрипт deploy:prod -> исполняемый путь",
               "package.json:scripts.deploy:prod" in rep["runnable_paths"])
        expect("npm-скрипт rollback -> откат объявлен", rep["rollback_declared"])
        (root / "package.json").write_text('{"scripts": {"build": "tsc"}}', encoding="utf-8")
        expect("build не считается деплоем", assess(root)["runnable_paths"] == [])
        (root / "package.json").write_text("{{ битый json", encoding="utf-8")
        expect("битый package.json не роняет снимок", assess(root)["deploy_maturity"] == "absent")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        wf = root / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "deploy.yml").write_text(
            "jobs:\n  ship:\n    environment: production\n    steps:\n      - run: ./ship.sh\n",
            encoding="utf-8")
        rep = assess(root)
        expect("CI-job с environment и шагами -> runnable",
               rep["deploy_maturity"] == "runnable"
               and ".github/workflows/deploy.yml:ship" in rep["runnable_paths"])
        (wf / "deploy.yml").write_text(
            "jobs:\n  ship:\n    environment: production\n    steps: []\n", encoding="utf-8")
        expect("CI-job с environment но БЕЗ шагов -> не исполняемый путь (configured)",
               assess(root)["deploy_maturity"] == "configured")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".ai-ops.yaml").write_text(
            "engineering_operating_model:\n  environments: [production]\n"
            "  deploy: {deploy_command: make deploy, rollback: make rollback}\n", encoding="utf-8")
        rep = assess(root)
        expect("deploy_command из конфига -> исполняемый путь",
               "config:deploy_command" in rep["runnable_paths"])
        expect("rollback из конфига -> откат объявлен", rep["rollback_declared"])
        expect("без записей поставок verified не достигается (runnable)",
               rep["deploy_maturity"] == "runnable")
        (root / ".ai-ops.yaml").write_text("{{ битый", encoding="utf-8")
        expect("битый конфиг не роняет снимок", assess(root)["deploy_maturity"] in MATURITY)

    # --- конфиг платформы = ПОДСКАЗКА, а не вывод (регрессия 3.20.1: инструмент заявлял, что поставку
    # ведёт vercel, лишь потому что нашёл vercel.json; на живом продукте это оказалось неправдой) -----
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "vercel.json").write_text('{"framework": "vite"}', encoding="utf-8")
        rep = assess(root)
        expect("конфиг платформы -> configured + путь поставки неизвестен",
               rep["deploy_maturity"] == "configured" and rep["deploy_path_unknown"] is True
               and rep["platform_hints"] == ["vercel.json"])
        expect("инструмент НЕ утверждает, что поставку ведёт найденная платформа",
               "ведёт" not in rep["reason"] and "путь существует" not in rep["reason"])
        expect("подсказка названа подсказкой, а не доказательством",
               "НЕ следует, что деплой идёт через них" in rep["reason"]
               and "наследием" in rep["reason"])
        expect("честная развилка: либо поставки нет, либо она вне репозитория",
               "поставки нет вовсе, либо она производится вне репозитория" in rep["reason"])
        f = [x for x in rep["findings"] if x["rule"] == "deploy_path_unknown"]
        expect("находка deploy_path_unknown с пометкой «не доказательство»",
               len(f) == 1 and "не доказательство" in f[0]["detail"])
        # объявили команду и откат -> поставка описана, незнание снято
        (root / ".ai-ops.yaml").write_text(
            "engineering_operating_model:\n  deploy: {deploy_command: vercel deploy --prod, "
            "rollback: vercel rollback}\n", encoding="utf-8")
        rep = assess(root)
        expect("объявленные deploy_command+rollback снимают незнание пути",
               rep["deploy_maturity"] == "runnable" and rep["deploy_path_unknown"] is False
               and not any(x["rule"] == "deploy_path_unknown" for x in rep["findings"]))

    expect("шаблон декларации содержит rollback и НЕ содержит чужого deploy-скрипта",
           "rollback:" in declaration_template() and "#!/bin/sh" not in declaration_template())
    expect("неприменимый гейт -> not_applicable", gate_status("verified", applicable=False)[0]
           == "not_applicable")
    expect("все ступени лестницы объявлены", MATURITY == ("absent", "configured", "runnable", "verified"))

    assert ok, "перенесённый селфтест deploy_readiness: см. строки FAIL в выводе"
