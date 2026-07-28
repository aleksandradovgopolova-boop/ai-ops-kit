#!/usr/bin/env python3
"""model_router.py (v3.7.5) — provider-neutral runtime resolver (ADR-004).

Делает провайдер-независимость ИСПОЛНЯЕМОЙ: роль -> КОНКРЕТНАЯ самая дешёвая КВАЛИФИЦИРОВАННАЯ модель
(не class×role, не вендор). Соединяет три реестра:
  - model-roles.yaml        — требование роли (preferred/fallback CLASS) + escalation-policy;
  - model-qualification.yaml — допуск model×revision×role (status ИЗ Bench, safety-first);
  - models.yaml             — конкретные модели, классы, cost_class, revision.

resolve(role): среди моделей, КВАЛИФИЦИРОВАННЫХ для роли И входящих в требуемый класс роли — берёт
самую дешёвую (cost_per_change, затем cost_class). Нет qualified -> resolved=false + escalation (НЕ
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

    def cost_key(q):
        cpc = q.get("metrics", {}).get("cost_per_change")
        return (cpc if isinstance(cpc, (int, float)) else 99,
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
    return {"kind": "ModelResolutionResult", "resolved": True, "role": role,
            "model_id": top["model_id"], "provider": top.get("provider"), "revision": top.get("revision"),
            "status": top.get("status"),
            "qualification_evidence": f"{top['model_id']}@{top.get('revision')}/{role}#{top.get('corpus_version')}",
            "estimated_cost": top.get("metrics", {}).get("cost_per_change"),
            "reason": f"cheapest-eligible ({top.get('status')})",
            "fallback": ({"model_id": fb["model_id"], "revision": fb.get("revision")} if fb else None)}


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

    # измеренный реестр (N6, 2026-07-28): implementation — три conditional вендора; по стоимости
    # deepseek(79.5k) < qwen(108.8k) < kimi(139.2k) -> preferred deepseek, fallback qwen.
    r_impl = resolve("implementation", roles_cfg, quals, models)
    expect("implementation -> resolved (writer допускает conditional)",
           r_impl["resolved"] and r_impl.get("model_id") and r_impl["reason"].startswith("cheapest-eligible"))
    expect("implementation cheapest -> deepseek-chat (79.5k), не qwen/kimi",
           r_impl["model_id"] == "deepseek-chat" and r_impl["provider"] == "deepseek")
    expect("implementation fallback -> qwen3-coder-plus (2-й по стоимости, 108.8k)",
           (r_impl.get("fallback") or {}).get("model_id") == "qwen3-coder-plus")

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
