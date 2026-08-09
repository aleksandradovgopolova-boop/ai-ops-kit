"""Селфтест gate_policy, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from gate_policy import (  # noqa: F401 — имена, которые использует тело
    SAFETY_UI_GATES,
    UI_GATES,
    _effective,
    candidate_blocking_gates,
    candidate_policy,
    current_policy,
    derive_ui_impact,
    effective_review_outcome,
    shadow_diff,
)


@pytest.mark.slow
def test_gate_policy_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + name)
        ok = ok and bool(cond)

    # --- таксономия / обратная совместимость -----------------------------------------------------
    expect("derive: явный ui_impact уважается",
           derive_ui_impact({"ui_impact": "internal"}) == "internal")
    expect("derive: legacy ui_changed=true -> user_facing (консервативно, == текущему поведению)",
           derive_ui_impact({"ui_changed": True}) == "user_facing")
    expect("derive: нет UI -> none", derive_ui_impact({"task_type": "QUICK"}) == "none")
    expect("derive: мусорный ui_impact игнорируется, падаем на legacy",
           derive_ui_impact({"ui_impact": "bogus", "ui_changed": True}) == "user_facing")

    # --- current policy: сегодня ui_changed -> все 4 blocking ------------------------------------
    cur = current_policy({"ui_changed": True})
    expect("current: ui_changed -> все 4 UI-гейта applicable+blocking",
           all(d["applicability"] == "applicable" and d["enforcement"] == "blocking" for d in cur)
           and {d["gate"] for d in cur} == set(UI_GATES))
    cur_none = current_policy({"task_type": "QUICK"})
    expect("current: нет UI -> все 4 not_applicable",
           all(d["applicability"] == "not_applicable" for d in cur_none))

    # --- candidate: none -> ничего не применяется ------------------------------------------------
    cand_none = candidate_policy({"ui_impact": "none"})
    expect("candidate none: все 4 not_applicable",
           all(d["applicability"] == "not_applicable" for d in cand_none))

    # --- candidate: internal -> 3 не-safety гейта advisory, a11y остаётся blocking ---------------
    cand_int = {d["gate"]: d for d in candidate_policy({"ui_changed": True, "ui_impact": "internal"})}
    expect("candidate internal: ux/visual/design_system -> advisory (ослаблено)",
           all(cand_int[g]["enforcement"] == "advisory"
               for g in ("ux_review", "visual_regression", "design_system_usage")))
    expect("candidate internal: accessibility остаётся blocking (safety не ослабляем)",
           cand_int["accessibility_review"]["enforcement"] == "blocking")

    # --- candidate: user_facing == current (никакого ослабления там, где риск высок) --------------
    cand_uf = candidate_policy({"ui_changed": True, "ui_impact": "user_facing"})
    expect("candidate user_facing: все 4 остаются blocking (== current, ноль ослабления)",
           all(d["enforcement"] == "blocking" and d["applicability"] == "applicable" for d in cand_uf))

    # --- candidate: critical -> blocking + human на ux и accessibility ---------------------------
    cand_cr = {d["gate"]: d for d in candidate_policy({"ui_changed": True, "ui_impact": "critical"})}
    expect("candidate critical: все 4 blocking",
           all(d["enforcement"] == "blocking" for d in cand_cr.values()))
    expect("candidate critical: ux + accessibility требуют human_signoff",
           cand_cr["ux_review"]["human_signoff"] and cand_cr["accessibility_review"]["human_signoff"])

    # --- ИНВАРИАНТ безопасности: candidate НЕ мягче current вне internal --------------------------
    def _softer(a, b):  # a мягче b?  blocks > advises > skipped
        rank = {"blocks": 2, "advises": 1, "skipped": 0}
        return rank[a] < rank[b]
    for impact in ("user_facing", "critical"):
        sig = {"ui_changed": True, "ui_impact": impact}
        cur_m = {d["gate"]: _effective(d) for d in current_policy(sig)}
        cand_m = {d["gate"]: _effective(d) for d in candidate_policy(sig)}
        expect(f"safety: candidate НЕ мягче current ни на одном гейте при impact={impact}",
               not any(_softer(cand_m[g], cur_m[g]) for g in UI_GATES))
    # в internal ослабление допускается ТОЛЬКО для не-safety гейтов
    sig_i = {"ui_changed": True, "ui_impact": "internal"}
    cur_i = {d["gate"]: _effective(d) for d in current_policy(sig_i)}
    cand_i = {d["gate"]: _effective(d) for d in candidate_policy(sig_i)}
    softened = {g for g in UI_GATES if _softer(cand_i[g], cur_i[g])}
    expect("safety: в internal ослаблены только не-safety гейты (accessibility НЕ ослаблен)",
           softened and not (softened & set(SAFETY_UI_GATES)))

    # --- shadow_diff: internal -> есть would_unblock; user_facing -> нет ослабляющих diff ---------
    sh_int = shadow_diff({"ui_changed": True, "ui_impact": "internal", "ui_change_kind": "component"})
    expect("shadow internal: есть would_unblock и ровно на 3 не-safety гейтах",
           {d["gate"] for d in sh_int["differences"] if d["effect"] == "would_unblock"}
           == {"ux_review", "visual_regression", "design_system_usage"})
    sh_uf = shadow_diff({"ui_changed": True, "ui_impact": "user_facing"})
    expect("shadow user_facing: ноль ослабляющих отличий (безопасность сохранена)",
           not [d for d in sh_uf["differences"] if d["effect"] in ("would_unblock", "would_skip")])
    sh_none = shadow_diff({"ui_impact": "none"})
    expect("shadow none: current и candidate совпадают (оба не применяют UI-гейты)",
           not sh_none["differences"])

    # --- candidate_blocking_gates для проекции bench ---------------------------------------------
    expect("blocking-set internal: accessibility остаётся, остальные ушли",
           candidate_blocking_gates(sig_i) == {"accessibility_review"})
    expect("blocking-set user_facing: все 4 остаются",
           candidate_blocking_gates({"ui_changed": True, "ui_impact": "user_facing"}) == set(UI_GATES))

    # --- effective_review_outcome (v3.1.8 калиброванное enforcement) -----------------------------
    uf = {"ui_changed": True, "ui_impact": "user_facing"}
    intn = {"ui_changed": True, "ui_impact": "internal"}
    # SAFETY: evidence fail всегда блокирует, даже если ревьюер молчал бы (warn)
    expect("eff: evidence=fail -> block (реальная регрессия), даже на internal",
           effective_review_outcome("visual_regression", intn, "warn", "fail")[0] == "block")
    # reviewer fail всегда блокирует
    expect("eff: reviewer=fail -> block (жёсткий вердикт)",
           effective_review_outcome("ux_review", uf, "fail", "not_run")[0] == "block")
    # internal не-safety + warn + нет evidence -> advisory (ослабление)
    expect("eff: internal ux + warn + no-evidence -> advisory",
           effective_review_outcome("ux_review", intn, "warn", "not_run")[0] == "advisory")
    # internal accessibility остаётся blocking (safety) -> warn без evidence блокирует
    expect("eff: internal accessibility + warn + no-evidence -> block (safety не ослаблен)",
           effective_review_outcome("accessibility_review", intn, "warn", "not_run")[0] == "block")
    # user_facing + warn + evidence pass -> advisory (механика подтверждена)
    expect("eff: user_facing + warn + evidence=pass -> advisory (evidence сильнее мнения)",
           effective_review_outcome("visual_regression", uf, "warn", "pass")[0] == "advisory")
    # user_facing + warn + нет evidence -> block (fail-closed, == сегодня)
    expect("eff: user_facing + warn + no-evidence -> block (fail-closed)",
           effective_review_outcome("ux_review", uf, "warn", "not_run")[0] == "block")
    # legacy: ui_changed без ui_impact -> user_facing -> block (no-op относительно сегодня)
    expect("eff: legacy ui_changed + warn + no-evidence -> block (no-op)",
           effective_review_outcome("ux_review", {"ui_changed": True}, "warn", "not_run")[0] == "block")
    # accessibility user_facing + warn + evidence pass -> advisory (авто-часть подтверждена)
    expect("eff: user_facing accessibility + warn + evidence=pass -> advisory",
           effective_review_outcome("accessibility_review", uf, "warn", "pass")[0] == "advisory")
    # но accessibility user_facing + warn + evidence=fail -> block (реальный дефект)
    expect("eff: user_facing accessibility + evidence=fail -> block (реальный a11y-дефект)",
           effective_review_outcome("accessibility_review", uf, "warn", "fail")[0] == "block")
    # critical ux/accessibility требуют human-signoff -> даже evidence=pass НЕ снимает warn
    crit = {"ui_changed": True, "ui_impact": "critical"}
    expect("eff: critical ux + warn + evidence=pass -> block (human-signoff обязателен)",
           effective_review_outcome("ux_review", crit, "warn", "pass")[0] == "block")
    expect("eff: critical accessibility + warn + evidence=pass -> block (human-signoff)",
           effective_review_outcome("accessibility_review", crit, "warn", "pass")[0] == "block")
    # но critical visual (без human-signoff) + evidence=pass -> advisory (механика подтверждена)
    expect("eff: critical visual + warn + evidence=pass -> advisory (нет human-signoff у visual)",
           effective_review_outcome("visual_regression", crit, "warn", "pass")[0] == "advisory")

    assert ok, "перенесённый селфтест gate_policy: см. строки FAIL в выводе"
