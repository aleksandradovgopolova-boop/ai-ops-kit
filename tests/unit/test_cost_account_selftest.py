"""Селфтест cost_account, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from cost_account import (  # noqa: F401 — имена, которые использует тело
    PKG,
    compare_configs,
    cost_per_successful_change,
    reconcile,
    yaml,
)


@pytest.mark.slow
def test_cost_account_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    # реальный BudgetContract из демо (run scope: max_model_calls=40, max_cost_usd=1.0)
    bud = yaml.safe_load((PKG / "examples" / "budget-demo" / "BUD-002.yaml").read_text(encoding="utf-8"))

    r = reconcile(bud, {"calls": 20, "cost_usd_est": 0.5})
    expect("в пределах бюджета -> within_budget", r["verdict"] == "within_budget"
           and r["dimensions"]["max_model_calls"]["remaining"] == 20)
    r = reconcile(bud, {"calls": 40, "cost_usd_est": 0.5})
    expect("spent == limit -> exhausted", r["verdict"] == "exhausted"
           and r["dimensions"]["max_model_calls"]["exhausted"] is True)
    r = reconcile(bud, {"calls": 45, "cost_usd_est": 0.5})
    expect("spent > limit -> over", r["verdict"] == "over"
           and r["dimensions"]["max_model_calls"]["over"] is True)
    r = reconcile(bud, {"calls": 20, "cost_usd_est": 1.5})
    expect("cost превышен -> over", r["verdict"] == "over"
           and r["dimensions"]["max_cost_usd"]["over"] is True)

    # честность: нет cost_usd_est -> measured=false, не выносим over по стоимости
    r = reconcile(bud, {"calls": 20, "cost_usd_est": None})
    expect("cost не измерен -> measured=false, verdict не over по стоимости",
           r["dimensions"]["max_cost_usd"]["measured"] is False and r["verdict"] == "within_budget")

    # loop budget (max_tokens=200000): токены = input+output
    lp = yaml.safe_load((PKG / "examples" / "budget-demo" / "BUD-001.yaml").read_text(encoding="utf-8"))
    r = reconcile(lp, {"input_tokens": 150000, "output_tokens": 60000}, iterations=1)
    expect("max_tokens по сумме input+output -> over при 210k>200k",
           r["dimensions"]["max_tokens"]["spent"] == 210000 and r["verdict"] == "over")
    r = reconcile(lp, {"input_tokens": 100000, "output_tokens": 50000}, iterations=1)
    expect("iterations сверяется с max_iterations",
           r["dimensions"]["max_iterations"]["spent"] == 1
           and r["dimensions"]["max_iterations"]["exhausted"] is True)

    # null-лимиты пропускаются
    r = reconcile(bud, {"calls": 5})
    expect("null-лимиты (max_tokens/max_wall) не в dimensions",
           "max_tokens" not in r["dimensions"] and "max_wall_seconds" not in r["dimensions"])

    # v3.7 (ADR-004): cost per successful change — «дёшево» бывает дорого
    kimi = cost_per_successful_change({"calls_cost": 0.30, "retry_cost": 0.60, "reviewer_cost": 0.20,
                                       "escalation_cost": 0.90, "manual_interventions": 1, "delivered_verified": True})
    strong = cost_per_successful_change({"calls_cost": 1.20, "reviewer_cost": 0.30, "delivered_verified": True})
    expect("cost_per_change: сумма всех издержек", kimi["cost_per_change"] == 2.0 and strong["cost_per_change"] == 1.5)
    fail = cost_per_successful_change({"calls_cost": 0.30, "delivered_verified": False})
    expect("не доставлено+проверено -> cost_per_change=None (не «дёшево», а потери)",
           fail["cost_per_change"] is None)
    cmp = compare_configs([{"name": "economical-kimi", "attempt": {"calls_cost": 0.30, "retry_cost": 0.60,
                            "escalation_cost": 0.90, "reviewer_cost": 0.20, "delivered_verified": True}},
                           {"name": "reference-strong", "attempt": {"calls_cost": 1.20, "reviewer_cost": 0.30,
                            "delivered_verified": True}},
                           {"name": "cheap-but-failed", "attempt": {"calls_cost": 0.10, "delivered_verified": False}}])
    expect("compare_configs: сильная дешевле на успешное изменение (2.0 vs 1.5) -> cheapest_qualified=reference-strong",
           cmp["cheapest_qualified"] == "reference-strong")
    expect("compare_configs: не-доставившая исключена (не считается дешёвой)",
           "cheap-but-failed" in cmp["excluded_no_verified_change"])

    assert ok, "перенесённый селфтест cost_account: см. строки FAIL в выводе"
