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

    # кандидаты: КВАЛИФИЦИРОВАННЫЕ для роли И входящие в требуемый класс роли
    cands = [q for q in quals if q.get("role") == role and q.get("status") == "qualified"
             and (not allowed_classes or (m_classes(q.get("model_id")) & allowed_classes))]

    def cost_key(q):
        cpc = q.get("metrics", {}).get("cost_per_change")
        return (cpc if isinstance(cpc, (int, float)) else 99,
                _COST_RANK.get((models.get(q.get("model_id")) or {}).get("cost_class"), 1))

    cands.sort(key=cost_key)
    if not cands:
        return {"kind": "ModelResolutionResult", "resolved": False, "role": role,
                "reason": "нет КВАЛИФИЦИРОВАННОЙ модели для роли (safety over economy: неквалифицированную не берём)",
                "required_class": sorted(allowed_classes),
                "escalation": {"needs": "qualified model в требуемом классе / сильный судья / человек",
                               "escalate_scope": (roles_cfg.get("escalation_policy") or {}).get("escalate_scope")}}
    top = cands[0]
    fb = cands[1] if len(cands) > 1 else None
    return {"kind": "ModelResolutionResult", "resolved": True, "role": role,
            "model_id": top["model_id"], "provider": top.get("provider"), "revision": top.get("revision"),
            "qualification_evidence": f"{top['model_id']}@{top.get('revision')}/{role}#{top.get('corpus_version')}",
            "estimated_cost": top.get("metrics", {}).get("cost_per_change"),
            "reason": "cheapest-qualified",
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

    r_impl = resolve("implementation", roles_cfg, quals, models)
    expect("implementation -> resolved конкретной моделью (cheapest-qualified)",
           r_impl["resolved"] and r_impl["reason"] == "cheapest-qualified" and r_impl.get("model_id"))
    expect("implementation -> провайдер kimi (дешёвый исполнитель, не вендор-lock)",
           r_impl["provider"] == "kimi" and r_impl.get("revision"))
    # cheapest: highspeed (cost 0.9) дешевле k3 (1.4) -> выбран highspeed
    expect("cheapest-qualified: выбран highspeed (0.9) а не k3 (1.4)",
           r_impl["model_id"] == "kimi-k2.7-code-highspeed")

    r_sec = resolve("security_review", roles_cfg, quals, models)
    expect("security_review -> НЕ resolved (нет qualified судьи; safety, не берём дешёвую)",
           r_sec["resolved"] is False and "escalation" in r_sec)

    # синтетика: две qualified модели -> берётся дешевле
    q2 = [{"role": "implementation", "status": "qualified", "model_id": "kimi-k3", "provider": "kimi",
           "revision": "kimi-k3", "corpus_version": "t", "metrics": {"cost_per_change": 1.4}},
          {"role": "implementation", "status": "qualified", "model_id": "kimi-k2.7-code-highspeed",
           "provider": "kimi", "revision": "hs", "corpus_version": "t", "metrics": {"cost_per_change": 0.9}}]
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
