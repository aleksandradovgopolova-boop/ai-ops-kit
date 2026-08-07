"""Селфтест qual_run, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from qual_run import (  # noqa: F401 — имена, которые использует тело
    Path,
    evaluate_report,
    json,
    print_summary,
    run_qualification,
    slugify,
)


@pytest.mark.slow
def test_qual_run_selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    # slug безопасен и совместим с validate_workitem_id
    import run_plan
    for t in ["Мелкий БАГ-фикс: список!!!", "  ", "----", "UPPER Case Task", "🚀🚀"]:
        s = slugify(t)
        try:
            run_plan.validate_workitem_id(s)
            valid = True
        except ValueError:
            valid = False
        expect(f"slug валиден как workitem_id: {t!r}->{s!r}", valid)

    # кириллица транслитерируется (не схлопывается в один slug) и РАЗНЫЕ задачи -> РАЗНЫЕ slug
    expect("кириллица транслитерируется читаемо",
           slugify("Добавить фильтр").startswith("dobavit"))
    ru = [slugify(x) for x in ["Добавить фильтр", "Исправить баг", "Обновить доки"]]
    expect("разные русские задачи -> уникальные slug (нет коллизий)", len(set(ru)) == 3)

    # evaluate_report: полностью успешный отчёт -> ok
    good = {"kind": "execution-pipeline", "status": None,
            "loop": {"stopped": "done", "denied": 0},
            "commit": {"sha": "a" * 40, "evidence_on_exact_sha": True},
            "gates": {"blocked": False, "unmet": []}, "ready_for_pr": True}
    expect("evaluate: успешный отчёт -> ok", evaluate_report(good)["ok"] is True)

    # ready_for_pr — источник истины вердикта. При не-готовности собираем диагностику.
    def broke(**patch):
        r = json.loads(json.dumps(good)); r.update(patch); return evaluate_report(r)
    expect("evaluate: not ready_for_pr -> fail", broke(ready_for_pr=False)["ok"] is False)
    gb = broke(ready_for_pr=False, gates={"blocked": True, "unmet": ["x"]})
    expect("evaluate: not ready + gates.blocked -> fail c причиной gates",
           gb["ok"] is False and any("gates" in r for r in gb["reasons"]))
    sha = broke(ready_for_pr=False, commit={"sha": "a" * 40, "evidence_on_exact_sha": False})
    expect("evaluate: not ready + не точный SHA -> причина про SHA",
           sha["ok"] is False and any("SHA" in r for r in sha["reasons"]))
    reg = broke(ready_for_pr=False, baseline={"regressions": ["build"], "no_regressions": False})
    expect("evaluate: not ready + регрессии -> причина про регрессии",
           reg["ok"] is False and any("регресс" in r for r in reg["reasons"]))
    expect("evaluate: ready_for_pr=True -> ok даже при gates.blocked (baseline-diff)",
           broke(gates={"blocked": True, "unmet": ["x"]})["ok"] is True)
    expect("evaluate: status=error -> fail",
           evaluate_report({"status": "error", "error": "boom"})["ok"] is False)
    expect("evaluate: None -> fail", evaluate_report(None)["ok"] is False)

    # run_qualification: серия с инъецированным раннером (offline, без сети), отчёты пишутся
    with tempfile.TemporaryDirectory() as td:
        scripted = {"ok task": good,
                    "bad task": {"kind": "execution-pipeline", "loop": {"stopped": "done"},
                                 "commit": {"sha": "b" * 40, "evidence_on_exact_sha": True},
                                 "gates": {"blocked": True, "unmet": ["security"]},
                                 "ready_for_pr": False}}

        def runner(task):
            if task == "boom task":
                raise RuntimeError("provider down")
            return scripted[task]

        res = run_qualification(["ok task", "bad task", "boom task"], td, runner)
        by = {r["task"]: r for r in res}
        expect("серия: ok task прошла", by["ok task"]["ok"] is True)
        expect("серия: bad task провалена с причиной", by["bad task"]["ok"] is False
               and by["bad task"]["reasons"])
        expect("серия: исключение раннера -> честный fail (серия не упала)",
               by["boom task"]["ok"] is False)
        expect("серия: отчёты записаны на диск",
               (Path(td) / "01-ok-task.json").exists() and (Path(td) / "summary.json").exists())
        overall = print_summary(res)
        expect("серия: не все прошли -> overall False", overall is False)

        allgood = run_qualification(["ok task"], td, lambda t: good)
        expect("серия: все прошли -> overall True", print_summary(allgood) is True)

    assert ok, "перенесённый селфтест qual_run: см. строки FAIL в выводе"
