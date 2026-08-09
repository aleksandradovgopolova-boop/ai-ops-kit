"""Селфтест bench_lite, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from bench_lite import (  # noqa: F401 — имена, которые использует тело
    gate_policy,
    run_bench,
)


@pytest.mark.slow
def test_bench_lite_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + name)
        ok = ok and bool(cond)

    rep = run_bench()
    m = rep["metrics"]
    # инвариант безопасности — абсолютный
    expect("bench: false_green == 0 (движок никогда не отдаёт ready при обязательном блоке)",
           m["false_green"] == 0)
    expect("bench: 0 ошибок прогона (все кейсы исполнились)", m["error"] == 0)
    expect("bench: 0 расхождений по составу гейтов (mismatch)", m["mismatch"] == 0)
    # эталонные исходы совпали ровно (нет false_fail на заведомо готовых кейсах)
    expect("bench: false_fail == 0 (заведомо готовые кейсы доведены до ready)", m["false_fail"] == 0)
    expect("bench: все кейсы прошли (pass == total)", m["pass"] == rep["total"])
    # tool-free fix-loop реально сработал в CI-совместимом окружении
    expect("bench: fix-loop снял блок ревью tool-free (fix_recovered >= 1)", m["fix_recovered"] >= 1)
    # консервативный review измеряется (есть хотя бы один корректный review-блок)
    expect("bench: измерена консервативность review (review_blocked >= 1)", m["review_blocked"] >= 1)
    # схема отчёта пригодна к машинной обработке
    expect("bench: отчёт содержит per-case классификацию",
           all("classification" in c for c in rep["cases"]) and rep["total"] >= 4)

    # --- ДВЕ ИСТИНЫ (v3.1.6): policy_conformance vs quality_accuracy --------------------------------
    pc = rep["policy_conformance"]
    qa = rep["quality_accuracy"]
    UI = gate_policy.UI_GATES
    SAFE = gate_policy.SAFETY_UI_GATES

    # (1) policy_conformance: движок ИДЕАЛЬНО исполняет ТЕКУЩУЮ policy (нет false_green/false_fail/mismatch)
    expect("policy_conformance == 100% (движок исполняет текущую gate-policy как задумано)",
           pc["conformance_rate"] == 1.0 and pc["false_green"] == 0)

    # (2) engine floor: при полном добросовестном покрытии корректный код доходит до ready на КАЖДОМ impact
    expect("quality: engine_floor_ready (движок не источник false-fail ни на одном уровне impact)",
           qa["engine_floor_ready"] is True)
    # rate измерен, честно помечен как синтетический; live-rate НЕ выдаётся за измеренный
    expect("quality: synthetic_known_good_block_rate в [0,1], sample>=15, тип scripted, live=None",
           qa["synthetic_known_good_block_rate"] is not None
           and 0.0 <= qa["synthetic_known_good_block_rate"] <= 1.0
           and qa["sample_size"] >= 15 and qa["sample_type"] == "scripted_reviewer"
           and qa["live_reviewer_false_fail_rate"] is None)
    # атрибуция покрывает ВСЕ 4 UI review-гейта
    expect("quality: block_attribution покрывает все 4 UI-гейта",
           all(qa["block_attribution"].get(g, 0) >= 1 for g in UI))
    # КОНТРОЛЬ: backend (impact=none) доходит до ready -> false-fail сконцентрирован в UI-гейтах
    _bk = next((c for c in rep["cases"] if c["id"] == "kg_full_backend"), None)
    expect("quality: backend (impact=none) доходит до ready -> false-fail сконцентрирован в UI-ревью",
           _bk is not None and _bk["actual"].get("ready_for_pr") is True)
    # каждый known-good с blocked_by заблокирован ИМЕННО этим гейтом (среди UI-гейтов — ровно он)
    for c in rep["cases"]:
        exp_by = c["expected"].get("blocked_by")
        if exp_by:
            unmet = c["actual"].get("unmet", [])
            expect(f"quality: {c['id']} заблокирован именно {exp_by} (атрибуция точна)",
                   set(g for g in unmet if g in UI) == set(exp_by))

    # (3) ПРОЕКЦИЯ кандидатной политики: строгое снижение false-fail, но БЕЗ ослабления safety
    expect("shadow: кандидат СТРОГО снижает known_good_block_rate (есть что калибровать)",
           qa["projected_block_rate_after_calibration"] < qa["synthetic_known_good_block_rate"])
    # освобождаются ТОЛЬКО internal-кейсы и ТОЛЬКО по не-safety гейтам
    for cid in qa["projected_released"]:
        c = next(x for x in rep["cases"] if x["id"] == cid)
        unmet_ui = [g for g in c["actual"].get("unmet", []) if g in UI]
        expect(f"shadow: освобождён {cid} -> impact=internal и unmet без safety-гейтов",
               c["ui_impact"] == "internal" and not (set(unmet_ui) & set(SAFE)))
    # НИ ОДИН user_facing/critical заблокированный кейс не освобождается (safety сохранена)
    _released_impacts = {next(x for x in rep["cases"] if x["id"] == cid)["ui_impact"]
                         for cid in qa["projected_released"]}
    expect("shadow: ни один user_facing/critical кейс НЕ освобождён (safety не ослаблена)",
           not (_released_impacts & {"user_facing", "critical"}))

    # (4) SHADOW-диффы: user_facing/critical -> ноль ослабляющих отличий; движок остаётся источником истины
    for c in rep["cases"]:
        sh = c.get("shadow")
        if sh and c["ui_impact"] in ("user_facing", "critical"):
            weakening = [d for d in sh["differences"] if d["effect"] in ("would_unblock", "would_skip")]
            expect(f"shadow: {c['id']} ({c['ui_impact']}) без ослабляющих отличий кандидата",
                   not weakening)
    # ИНВАРИАНТ безопасности сохранён на всём корпусе
    expect("shadow: измерение/проекция НЕ порождают false_green (безопасность не ослаблена)",
           m["false_green"] == 0)

    # --- v3.1.8 ПРОМОУШЕН-КРИТЕРИЙ живого калиброванного enforcement ------------------------------
    ce = rep["calibrated_enforcement"]
    # (S1) абсолютная безопасность: калиброванная политика НЕ порождает false-green
    expect("calib: false_green == 0 под ЖИВОЙ калиброванной политикой (safety не ослаблена)",
           ce["calibrated_false_green"] == 0)
    # (S2) safety-регрессии (evidence=fail: реальный a11y/визуальный дефект) ОБЯЗАНЫ блокироваться,
    #      даже когда ревьюер добросовестно вынес pass — калибровка ловит пропущенное ревью
    expect("calib: ВСЕ safety-регрессии (evidence=fail) заблокированы (>=2)",
           ce["safety_regressions_total"] >= 2
           and ce["safety_regressions_blocked"] == ce["safety_regressions_total"])
    # (P1) residual false-fail = 0: КАЖДЫЙ should-pass кейс освобождён (≤ 0.10 промоушен-порог)
    expect("calib: residual_false_fail == 0 (все should-pass освобождены, rate ≤ 0.10)",
           ce["residual_false_fail"] == 0
           and (ce["residual_false_fail_rate"] is None or ce["residual_false_fail_rate"] <= 0.10))
    # (P2) детерминированное evidence реально освобождает user_facing (deterministic closure работает)
    expect("calib: evidence освобождает >=5 known-good (deterministic closure)",
           ce["evidence_released"] >= 5)
    # (P3) калибровка СТРОГО снижает block-rate относительно baseline (реальный A/B, не проекция).
    #      Порог >=0.5 — транспарентность; ПРОМОУШЕН держится на residual_false_fail_rate≤0.10 (P1),
    #      т.к. оставшиеся блоки — fail-closed (нет evidence / critical human-signoff), НЕ false-fail.
    expect("calib: calibrated_block_rate < baseline_block_rate и reduction >= 0.5",
           ce["calibrated_block_rate"] < ce["baseline_block_rate"] and ce["reduction"] >= 0.5)
    # (P4) НО оставшиеся блоки — строго fail-closed: каждый заблокированный calibrated known-good
    #      имеет calibrated_expected.ready=False (никакой should-pass не заблокирован)
    _kgc_blocked = [c for c in rep["cases"] if c["category"] == "known_good"
                    and "calibrated_actual" in c
                    and c["calibrated_actual"].get("ready_for_pr") is not True]
    expect("calib: каждый оставшийся блок обоснован (calibrated_expected.ready=False, fail-closed)",
           all(c["calibrated_expected"].get("ready") is False for c in _kgc_blocked))

    assert ok, "перенесённый селфтест bench_lite: см. строки FAIL в выводе"
