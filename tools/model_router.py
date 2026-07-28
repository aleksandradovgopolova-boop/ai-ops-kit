#!/usr/bin/env python3
"""model_router.py (v3.7.5) — provider-neutral runtime resolver (ADR-004).

Делает провайдер-независимость ИСПОЛНЯЕМОЙ: роль -> КОНКРЕТНАЯ самая дешёвая КВАЛИФИЦИРОВАННАЯ модель
(не class×role, не вендор). Соединяет три реестра:
  - model-roles.yaml        — требование роли (preferred/fallback CLASS) + escalation-policy;
  - model-qualification.yaml — допуск model×revision×role (status ИЗ Bench, safety-first);
  - models.yaml             — конкретные модели, классы, cost_class, revision.

resolve(role): среди допущенных для роли моделей в требуемом классе — берёт самую дешёвую. Экономика В
ДЕНЬГАХ (v3.7.10): если у ВСЕХ кандидатов есть total_cost_per_verified_change -> сортировка по деньгам
(cost_basis=money); иначе честный tokens-fallback + cost_warning (нет тарифа -> порядок может не совпасть
с деньгами). Нет допущенной модели -> resolved=false + escalation (НЕ
берём неквалифицированную ради дешевизны — safety over economy). Стоимость класса НЕ считается по
неквалифицированной модели. escalation_decision(): abstain/schema_invalid -> targeted retry -> эскалация
ТОЛЬКО review/judge-вызова (escalate_scope=review_only), не всей задачи.

Только stdlib+pyyaml. CLI: model_router.py <role> [--json] | --selftest
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

PKG = Path(__file__).resolve().parents[1]
_COST_RANK = {"low": 0, "medium": 1, "high": 2, None: 1}
# ADR-004 (уточнено измеренной квалификацией 2026-07-28): роль ПИСАТЕЛЯ/эконом-ревью допускает
# conditional-модель (дешёвый пишет, гейты страхуют); строгий СУДЬЯ — только qualified (safety-first,
# судья не может быть «условным»). false_green>0 -> не допускается НИКОГДА и ни к какой роли.
WRITER_ROLES = {"implementation", "code_review"}
STRICT_JUDGE_ROLES = {"security_review", "integration_judge"}


def _eligible(q, role):
    fg = (q.get("metrics") or {}).get("false_green", 1)
    if fg is None or fg > 0:
        return False
    st = q.get("status")
    if role in STRICT_JUDGE_ROLES:
        return st == "qualified"
    return st in ("qualified", "conditional")


def _load():
    r = yaml.safe_load((PKG / "registry" / "model-roles.yaml").read_text(encoding="utf-8"))
    q = yaml.safe_load((PKG / "registry" / "model-qualification.yaml").read_text(encoding="utf-8"))
    m = yaml.safe_load((PKG / "registry" / "models.yaml").read_text(encoding="utf-8"))
    models = {x["id"]: x for x in m.get("models", []) if x.get("id")}
    return r, q.get("qualifications", []), models


def resolve(role, roles_cfg=None, quals=None, models=None):
    if roles_cfg is None:
        roles_cfg, quals, models = _load()
    req = (roles_cfg.get("roles") or {}).get(role, {})
    allowed_classes = {req.get("preferred_class"), req.get("fallback_class")} - {None}

    def m_classes(mid):
        return set((models.get(mid) or {}).get("classes", []) or [])

    # кандидаты: ДОПУЩЕННЫЕ для роли (writer: qualified∨conditional; судья: только qualified; fg=0 всегда)
    # И входящие в требуемый класс роли
    cands = [q for q in quals if q.get("role") == role and _eligible(q, role)
             and (not allowed_classes or (m_classes(q.get("model_id")) & allowed_classes))]

    # v3.7.10 экономика В ДЕНЬГАХ: если у ВСЕХ кандидатов роли есть total_cost_per_verified_change
    # (деньги), сортируем по деньгам; иначе честный tokens-fallback + warning (ранжирование может не
    # совпасть с деньгами). Токен-прокси врёт при разнице тарифов — деньги основной критерий.
    def _money(q):
        v = (q.get("economics") or {}).get("total_cost_per_verified_change")
        return v if isinstance(v, (int, float)) else None

    def _tokens(q):
        t = (q.get("economics") or {}).get("tokens_per_verified_change")
        if isinstance(t, (int, float)):
            return t
        cpc = q.get("metrics", {}).get("cost_per_change")   # legacy-поле (синтетика/старые записи)
        return cpc if isinstance(cpc, (int, float)) else None

    money_mode = bool(cands) and all(_money(q) is not None for q in cands)

    def cost_key(q):
        primary = _money(q) if money_mode else _tokens(q)
        return (primary if isinstance(primary, (int, float)) else 1e18,
                _COST_RANK.get((models.get(q.get("model_id")) or {}).get("cost_class"), 1))

    cands.sort(key=cost_key)
    if not cands:
        strict = role in STRICT_JUDGE_ROLES
        return {"kind": "ModelResolutionResult", "resolved": False, "role": role,
                "reason": ("нет QUALIFIED судьи для роли (строгая роль: conditional НЕ годится, safety over economy)"
                           if strict else
                           "нет допущенной модели для роли (qualified∨conditional при false_green=0)"),
                "required_class": sorted(allowed_classes),
                "escalation": {"needs": ("qualified судья / человек" if strict
                                         else "qualified∨conditional model в требуемом классе / человек"),
                               "escalate_scope": (roles_cfg.get("escalation_policy") or {}).get("escalate_scope")}}
    top = cands[0]
    fb = cands[1] if len(cands) > 1 else None
    cost_basis = "money" if money_mode else "tokens-fallback"
    res = {"kind": "ModelResolutionResult", "resolved": True, "role": role,
           "model_id": top["model_id"], "provider": top.get("provider"), "revision": top.get("revision"),
           "status": top.get("status"), "cost_basis": cost_basis,
           "qualification_evidence": f"{top['model_id']}@{top.get('revision')}/{role}#{top.get('corpus_version')}",
           "estimated_cost": (_money(top) if money_mode else _tokens(top)),
           "cost_currency": ((top.get("economics") or {}).get("currency") if money_mode else None),
           "reason": f"cheapest-eligible ({top.get('status')}, {cost_basis})",
           "fallback": ({"model_id": fb["model_id"], "revision": fb.get("revision"),
                         "provider": fb.get("provider"), "status": fb.get("status")} if fb else None)}
    if not money_mode:
        res["cost_warning"] = ("ранжирование в ТОКЕНАХ, не деньгах: не у всех кандидатов роли задан "
                               "total_cost_per_verified_change (нет тарифа) — порядок может не совпасть с деньгами")
    return res


ALL_ROLES = ("implementation", "code_review", "security_review", "integration_judge")


def plan_run(roles_cfg=None, quals=None, models=None):
    """v3.7.12: резолв ВСЕХ рантайм-ролей одним вызовом -> bundle для RunReport.model_resolution.
    Делает решение роутера ВИДИМЫМ в отчёте прогона (writer/reviewer/security/integration независимо).
    writer≠judge по МОДЕЛИ: если code_review резолвится в модель != implementation — это разные identity."""
    if roles_cfg is None:
        roles_cfg, quals, models = _load()
    plan = {role: resolve(role, roles_cfg, quals, models) for role in ALL_ROLES}
    impl = plan["implementation"]
    rev = plan["code_review"]
    plan["writer_ne_judge_by_model"] = bool(impl.get("resolved") and rev.get("resolved")
                                            and impl.get("model_id") != rev.get("model_id"))
    return plan


def escalation_decision(role, attempt, signal, roles_cfg=None):
    """signal ∈ {ok, reviewer_abstain, schema_invalid, reviewer_uncertain}. -> действие.
    Targeted retry до max; затем эскалация ТОЛЬКО review/judge-вызова (не всей задачи)."""
    if roles_cfg is None:
        roles_cfg, _, _ = _load()
    esc = roles_cfg.get("escalation_policy") or {}
    if signal == "ok" or signal not in (esc.get("triggers") or []):
        return {"action": "proceed"}
    if attempt < int(esc.get("max_targeted_retries", 0)):
        return {"action": "retry", "attempt_next": attempt + 1, "scope": "same_model"}
    return {"action": "escalate", "scope": esc.get("escalate_scope", "review_only"),
            "note": "эскалируется только review/judge-вызов на fallback-класс, НЕ пере-прогон всей задачи"}


def selftest():
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

    print("model_router selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 1
    res = resolve(args[0])
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res.get("resolved") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
