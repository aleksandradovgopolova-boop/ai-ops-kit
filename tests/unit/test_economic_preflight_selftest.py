"""Селфтест economic_preflight, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from economic_preflight import (  # noqa: F401 — имена, которые использует тело
    ESTIMATE_STATUS,
    Path,
    VERDICTS,
    _fmt,
    _rec,
    assess,
    check_economics,
    estimate,
    policy_from_config,
    summary_line,
)


@pytest.mark.slow
def test_economic_preflight_selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    def rules(v, key="violations"):
        return {x["rule"] for x in v[key]}

    # --- ЧЕСТНОСТЬ оценки -------------------------------------------------------------------------
    e0 = estimate(records=[])
    expect("нет истории -> unavailable, а НЕ ноль",
           e0["status"] == "unavailable" and e0["cost_median"] is None and e0["cost_max"] is None)
    expect("нет истории -> прогон НЕ блокируется (иначе первый прогон невозможен)",
           check_economics(e0)["allowed"] and check_economics(e0)["verdict"] == "proceed_unknown")
    expect("require_estimate=True -> отсутствие истории блокирует осознанно",
           check_economics(e0, policy={"require_estimate": True})["verdict"] == "block")

    e1 = estimate(records=[_rec("WI-1", 1.0), _rec("WI-1", 0.5), _rec("WI-2", 3.0),
                           _rec("WI-3", 2.0)])
    expect("история из завершённых задач -> measured_history", e1["status"] == "measured_history")
    expect("медиана/худшая считаются по ЗАДАЧАМ, не по вызовам",
           e1["sample_tasks"] == 3 and e1["cost_median"] == 2.0 and e1["cost_max"] == 3.0)
    expect("вызовы тоже агрегируются по задачам", e1["calls_max"] == 2 and e1["calls_median"] == 1)
    expect("выборка >= 3 -> уверенность medium", e1["confidence"] == "medium")
    expect("маленькая выборка -> low",
           estimate(records=[_rec("WI-1", 1.0)])["confidence"] == "low")

    e_part = estimate(records=[_rec("WI-1", 1.0), _rec("WI-1", None, "unavailable")])
    expect("неизвестная стоимость вызова НЕ считается нулём -> lower_bound",
           e_part["status"] == "estimated_lower_bound")
    expect("нижняя граница честно названа нижней границей",
           "НИЖНЯЯ ГРАНИЦА" in e_part["note"] and "может НЕ сработать" in e_part["note"])
    v_part = check_economics(e_part, {"max_cost": 100})
    expect("на нижней границе вердикт помечен как более мягкий, чем следует",
           "lower_bound_only" in rules(v_part, "advisories"))
    expect("завершённые задачи имеют приоритет над частичными",
           estimate(records=[_rec("WI-1", 1.0), _rec("WI-2", None, "unavailable")])["status"]
           == "measured_history")

    # --- вердикт против лимитов -------------------------------------------------------------------
    v = check_economics(e1, {"max_cost": 10, "max_model_calls": 50})
    expect("в пределах лимитов -> proceed", v["verdict"] == "proceed" and v["allowed"])

    v = check_economics(e1, {"max_cost": 2.5})
    expect("ХУДШИЙ прогон дороже лимита -> блок ДО траты",
           v["verdict"] == "block" and not v["allowed"]
           and "cost_limit_exceeded" in rules(v))
    expect("блок объясняет, что трата была бы прервана посередине",
           any("прервана посередине" in x["detail"] for x in v["violations"]))
    expect("решение по ХУДШЕМУ, а не по медиане (медиана 2.0 < лимита 2.5)",
           e1["cost_median"] < 2.5 < e1["cost_max"])

    v = check_economics(e1, {"max_model_calls": 1})
    expect("худший прогон по вызовам превышает лимит -> блок",
           "calls_limit_exceeded" in rules(v) and v["verdict"] == "block")

    v = check_economics(e1, {"max_cost": 10}, {"confirm_over_cost_usd": 1})
    expect("медиана выше порога подтверждения -> confirm_required (не блок)",
           v["verdict"] == "confirm_required" and v["allowed"]
           and "confirm_recommended" in rules(v, "advisories"))
    expect("enforce=block превращает требование подтверждения в блок",
           not check_economics(e1, {"max_cost": 10},
                               {"confirm_over_cost_usd": 1, "enforce": "block"})["allowed"])
    expect("порог подтверждения None -> подтверждение не требуется",
           check_economics(e1, {"max_cost": 10},
                           {"confirm_over_cost_usd": None})["verdict"] == "proceed")
    expect("лимитов нет вовсе -> не блокируем, но и не выдумываем их",
           check_economics(e1)["verdict"] in ("proceed", "confirm_required")
           and check_economics(e1)["limits"] == {"max_cost": None, "max_model_calls": None,
                                                 "max_duration": None})
    expect("низкая уверенность отражена в советах",
           "low_confidence" in rules(check_economics(estimate(records=[_rec('WI-1', 1.0)]),
                                                     {"max_cost": 10}), "advisories"))

    # --- конфиг и поверхность ---------------------------------------------------------------------
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        expect("нет .ai-ops.yaml -> политика по умолчанию", policy_from_config(root) == {})
        (root / ".ai-ops.yaml").write_text(
            "engineering_operating_model:\n  economics:\n    enforce: block\n"
            "    confirm_over_cost_usd: 1\n    require_estimate: true\n", encoding="utf-8")
        p = policy_from_config(root)
        expect("политика экономики читается из .ai-ops.yaml",
               p.get("enforce") == "block" and p.get("require_estimate") is True)
        (root / ".ai-ops.yaml").write_text("{{ битый", encoding="utf-8")
        expect("битый конфиг не роняет проверку", policy_from_config(root) == {})
        est, v = assess(root)
        expect("assess на репозитории без ledger -> unavailable + не блок",
               est["status"] == "unavailable" and v["allowed"])
        expect("summary_line не выдаёт unavailable за ноль",
               "unavailable" in summary_line(root) and "не ноль" in summary_line(root))
        expect("_fmt печатает вердикт и причину", "экономика ДО прогона" in _fmt(est, v))

    expect("статусы и вердикты объявлены",
           ESTIMATE_STATUS == ("measured_history", "estimated_lower_bound", "unavailable")
           and VERDICTS == ("proceed", "proceed_unknown", "confirm_required", "block"))

    assert ok, "перенесённый селфтест economic_preflight: см. строки FAIL в выводе"
