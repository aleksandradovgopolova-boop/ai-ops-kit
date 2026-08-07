"""Селфтест model_router, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from model_router import (  # noqa: F401 — имена, которые использует тело
    ALL_ROLES,
    _load,
    escalation_decision,
    plan_run,
    resolve,
    writer_tier,
)


@pytest.mark.slow
def test_model_router_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    roles_cfg, quals, models = _load()

    # измеренный реестр (N6, 2026-07-28): три conditional вендора, ВСЕ priced -> MONEY-MODE. По деньгам/
    # изменение: deepseek-v4-flash $0.0115 < qwen $0.072 < kimi $0.467 -> preferred deepseek, fallback qwen.
    r_impl = resolve("implementation", roles_cfg, quals, models)
    expect("implementation -> resolved (writer допускает conditional)",
           r_impl["resolved"] and r_impl.get("model_id") and r_impl["reason"].startswith("cheapest-eligible"))
    expect("implementation cost_basis=money (все кандидаты с ценой) + без warning",
           r_impl["cost_basis"] == "money" and "cost_warning" not in r_impl)
    expect("implementation cheapest по ДЕНЬГАМ -> deepseek-v4-flash ($0.0115)",
           r_impl["model_id"] == "deepseek-v4-flash" and r_impl["provider"] == "deepseek")
    expect("implementation fallback -> qwen3-coder-plus (2-й по деньгам, $0.072)",
           (r_impl.get("fallback") or {}).get("model_id") == "qwen3-coder-plus")
    # v3.8.3 quality-escalation ladder: сильнее top по success_rate, сильнейший первым. top=deepseek
    # (success 0.667). Ладдер: kimi (1.0) > qwen (0.833). Оба сильнее -> оба в ладдере, kimi первым.
    _lad = r_impl.get("escalation_ladder") or []
    expect("escalation_ladder: выше observed success rate первым (kimi)",
           bool(_lad) and _lad[0]["model_id"] == "kimi-k2.7-code-highspeed"
           and _lad[0]["basis"] == "higher_observed_success_rate")
    expect("escalation_ladder: отсортирован по observed_success_rate DESC + несёт corpus_version",
           [x["observed_success_rate"] for x in _lad] == sorted([x["observed_success_rate"] for x in _lad], reverse=True)
           and all("corpus_version" in x for x in _lad))
    expect("escalation_ladder: только выше top (deepseek 0.667 не в ладдере)",
           all(x["model_id"] != "deepseek-v4-flash" for x in _lad)
           and all(x["observed_success_rate"] > 0.667 for x in _lad))

    # money-mode: у ВСЕХ кандидатов есть деньги -> сортировка по ДЕНЬГАМ, не токенам (доказ. тезиса)
    ms2 = {"a": {"classes": ["balanced"], "cost_class": "low"}, "b": {"classes": ["balanced"], "cost_class": "low"}}
    q_money = [
        {"role": "implementation", "status": "conditional", "model_id": "a", "provider": "pa", "revision": "a",
         "corpus_version": "t", "metrics": {"false_green": 0},
         "economics": {"tokens_per_verified_change": 50000, "total_cost_per_verified_change": 0.90}},   # мало токенов, ДОРОГО
        {"role": "implementation", "status": "conditional", "model_id": "b", "provider": "pb", "revision": "b",
         "corpus_version": "t", "metrics": {"false_green": 0},
         "economics": {"tokens_per_verified_change": 150000, "total_cost_per_verified_change": 0.07}}]  # много токенов, ДЁШЕВО
    rm = resolve("implementation", {"roles": {"implementation": {"preferred_class": "balanced"}}}, q_money, ms2)
    expect("money-mode: выбран дешёвый по ДЕНЬГАМ (b $0.07), а НЕ по токенам (a 50k)",
           rm["cost_basis"] == "money" and rm["model_id"] == "b" and "cost_warning" not in rm)

    r_sec = resolve("security_review", roles_cfg, quals, models)
    expect("security_review -> НЕ resolved (строгий судья требует qualified; conditional/пусто не годится)",
           r_sec["resolved"] is False and "escalation" in r_sec)

    # синтетика: строгий судья vs писатель при одном и том же conditional-кандидате в нужном классе
    ms = {"m-cond": {"classes": ["high-reasoning"], "cost_class": "low"}}
    q_cond = lambda role: [{"role": role, "status": "conditional", "model_id": "m-cond", "provider": "x",
                            "revision": "r", "corpus_version": "t", "metrics": {"false_green": 0, "cost_per_change": 1}}]
    rc_hr = lambda role: {"roles": {role: {"preferred_class": "high-reasoning", "fallback_class": "high-reasoning"}}}
    expect("строгий судья + conditional-в-классе -> всё равно НЕ resolved (qualified обязателен)",
           resolve("security_review", rc_hr("security_review"), q_cond("security_review"), ms)["resolved"] is False)
    expect("эконом-ревью (code_review) + conditional -> resolved",
           resolve("code_review", rc_hr("code_review"), q_cond("code_review"), ms)["resolved"] is True)
    q_fg = [{"role": "implementation", "status": "conditional", "model_id": "m-cond", "provider": "x",
             "revision": "r", "corpus_version": "t", "metrics": {"false_green": 1, "cost_per_change": 1}}]
    expect("false_green>0 -> НЕ resolved даже для writer (safety-first)",
           resolve("implementation", rc_hr("implementation"), q_fg, ms)["resolved"] is False)

    # синтетика: две qualified модели -> берётся дешевле + вторая в fallback
    q2 = [{"role": "implementation", "status": "qualified", "model_id": "kimi-k3", "provider": "kimi",
           "revision": "kimi-k3", "corpus_version": "t", "metrics": {"false_green": 0, "cost_per_change": 1.4}},
          {"role": "implementation", "status": "qualified", "model_id": "kimi-k2.7-code-highspeed",
           "provider": "kimi", "revision": "hs", "corpus_version": "t", "metrics": {"false_green": 0, "cost_per_change": 0.9}}]
    rc = {"roles": {"implementation": {"preferred_class": "balanced", "fallback_class": "high-reasoning"}},
          "escalation_policy": {"triggers": ["reviewer_abstain"], "max_targeted_retries": 1, "escalate_scope": "review_only"}}
    r = resolve("implementation", rc, q2, models)
    expect("две qualified -> cheapest + fallback вторая",
           r["model_id"] == "kimi-k2.7-code-highspeed" and r["fallback"]["model_id"] == "kimi-k3")

    # escalation: abstain -> retry -> escalate review_only
    expect("abstain, attempt0, max1 -> retry", escalation_decision("code_review", 0, "reviewer_abstain", roles_cfg)["action"] == "retry")
    d = escalation_decision("code_review", 1, "reviewer_abstain", roles_cfg)
    expect("abstain после ретраев -> escalate review_only (не вся задача)",
           d["action"] == "escalate" and d["scope"] == "review_only")
    expect("ok -> proceed", escalation_decision("code_review", 0, "ok", roles_cfg)["action"] == "proceed")

    # plan_run: bundle всех ролей для RunReport
    plan = plan_run(roles_cfg, quals, models)
    expect("plan_run несёт все 4 роли", all(r in plan for r in ALL_ROLES))
    expect("plan_run: implementation resolved, security_review НЕ resolved",
           plan["implementation"]["resolved"] is True and plan["security_review"]["resolved"] is False)

    # v3.8.3 CONFLICT-AWARE writer≠judge: судья и writer сошлись -> writer перерезолвлен без модели судьи
    _rc = {"roles": {"implementation": {"preferred_class": "balanced"}, "security_review": {"preferred_class": "balanced"}},
           "role_constraints": {"security_review": {"must_differ_from": "implementation"}}}
    _ms = {"J": {"classes": ["balanced"], "cost_class": "low"}, "W": {"classes": ["balanced"], "cost_class": "mid"}}
    _ec = lambda c: {"input_tokens_per_change": 1, "output_tokens_per_change": 1, "tokens_per_verified_change": 1,
                     "input_price_per_mtok": c, "output_price_per_mtok": c, "currency": "USD",
                     "price_snapshot_at": "2026-07-30", "price_source": "test", "total_cost_per_verified_change": 2 * c / 1e6}
    _q = [  # J дешевле и qualified и для security_review, и для implementation -> конфликт
        {"role": "security_review", "status": "qualified", "model_id": "J", "provider": "p", "revision": "J",
         "corpus_version": "c", "metrics": {"false_green": 0}, "economics": _ec(0.1)},
        {"role": "implementation", "status": "qualified", "model_id": "J", "provider": "p", "revision": "J",
         "corpus_version": "c", "metrics": {"false_green": 0, "success_rate": 0.9}, "economics": _ec(0.1)},
        {"role": "implementation", "status": "conditional", "model_id": "W", "provider": "p", "revision": "W",
         "corpus_version": "c", "metrics": {"false_green": 0, "success_rate": 0.6}, "economics": _ec(1.0)},
    ]
    _p2 = plan_run(_rc, _q, _ms)
    expect("conflict-aware: security_review судья фиксирован = J",
           _p2["security_review"]["resolved"] and _p2["security_review"]["model_id"] == "J")
    expect("conflict-aware: implementation перерезолвлен НЕ в J (writer≠judge) -> W",
           _p2["implementation"]["resolved"] and _p2["implementation"]["model_id"] == "W")
    expect("conflict-aware: применение записано + writer_ne_judge",
           bool(_p2.get("role_constraints_applied")) and _p2["implementation"]["model_id"] != _p2["security_review"]["model_id"])

    # v3.9.0 complexity-aware routing: тир writer'а по классу задачи
    expect("writer_tier QUICK -> cheap-api (money-mode)",
           writer_tier({"task_type": "QUICK"})["tier"] == "cheap-api")
    expect("writer_tier ENGINEERING -> strong-executor (claude-cli) сразу",
           writer_tier({"task_type": "ENGINEERING"})["tier"] == "strong-executor"
           and writer_tier({"task_type": "ENGINEERING"})["provider_hint"] == "claude-cli")
    expect("writer_tier PRODUCT -> strong-executor",
           writer_tier({"task_type": "PRODUCT"})["tier"] == "strong-executor")
    expect("writer_tier QUICK+risk critical -> strong-executor (risk override)",
           writer_tier({"task_type": "QUICK", "risk": "critical"})["tier"] == "strong-executor")
    expect("plan_run со signals несёт preferred_writer_tier",
           isinstance(plan_run(roles_cfg, quals, models, signals={"task_type": "ENGINEERING"}).get("preferred_writer_tier"), dict)
           and plan_run(roles_cfg, quals, models, signals={"task_type": "ENGINEERING"})["preferred_writer_tier"]["tier"] == "strong-executor")

    assert ok, "перенесённый селфтест model_router: см. строки FAIL в выводе"
