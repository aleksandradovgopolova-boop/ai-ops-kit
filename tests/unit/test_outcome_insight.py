#!/usr/bin/env python3
"""Тесты обратной петли Outcome → Insight → кандидат-работа (#567).

Доказываем ровно три инварианта петли:
  1. Инсайт рождается ТОЛЬКО на реальном вердикте (met/failed). На `unknown` — None, и причина названа.
  2. Эпистемика разделена (наблюдал/вывел/не знаю), уверенность падает с пробелами.
  3. Writer ≠ judge: кандидат — DRAFT, не активен, требует решения человека; рекомендация несёт
     evidence ДО предложения. Вся петля read-only — в дочку ничего не пишется.
Плюс проводка: `post_release_loop.run_post_release` замыкает петлю на реальном замере и молчит на unknown.
"""
from __future__ import annotations

from ai_ops_kit.cli import post_release_loop as prl
from ai_ops_kit.intelligence import outcome_insight as oi
from ai_ops_kit.validation import validate_product_objects as vpo

CONTRACT = {
    "schema_version": 1, "kind": "OutcomeContract", "decision": "ускорить онбординг",
    "evaluation_period": "30 дней",
    "primary_metric": {"name": "activation_rate", "source": "posthog"},
    "baseline": {"value": 20, "measured_at": "2026-09-01", "source": "posthog"},
    "target": {"value": 35, "by": "2026-10-01"},
    "guardrails": [{"name": "error_rate", "must_not_exceed": 2},
                   {"name": "latency", "must_not_exceed": 90}],
    "events": ["task.completed"],
    "decision_rules": {"continue": "target достигнут", "change": "ниже baseline",
                       "stop": "guardrail пробит"},
}


def _readout(value, *, measured_at="2026-09-16", target_met="no", hypothesis="inconclusive",
             guardrails=None, unexpected=None, next_decision="по правилу решения"):
    return {"schema_version": 1, "kind": "OutcomeReadout",
            "contract": "features/x/outcome-contract.yaml",
            "measured": {"metric": "activation_rate", "value": value, "measured_at": measured_at},
            "target_met": target_met, "hypothesis": hypothesis,
            "guardrails_observed": guardrails if guardrails is not None else [],
            "unexpected_effects": unexpected or [], "next_decision": next_decision,
            "back_to_discovery": "—"}


def _eval(readout):
    return vpo.evaluate_outcome(CONTRACT, readout)


# ── (1) инсайт только на реальном вердикте ────────────────────────────────────────────────────────
def test_no_insight_on_unknown_verdict_without_measurement():
    """Замера нет -> evaluate_outcome=unknown -> инсайт НЕ фабрикуется (None), причина названа."""
    ev = vpo.evaluate_outcome(CONTRACT, None)
    assert ev["verdict"] == "unknown"
    assert oi.derive_insight(CONTRACT, None, ev) is None
    assert oi.from_outcome(CONTRACT, None, ev) is None
    reason = oi.no_insight_reason(ev)
    assert reason and "измер" in reason.lower() or "флип" in (reason or "")


def test_no_insight_when_measurement_has_no_date():
    """Замер без даты — не измерение (число из головы): вердикт unknown -> инсайта нет."""
    ev = _eval(_readout(21, measured_at=""))
    assert ev["verdict"] == "unknown"
    assert oi.from_outcome(CONTRACT, _readout(21, measured_at=""), ev) is None


def test_insight_born_from_failed_verdict():
    """Реальный замер ниже цели -> failed -> рождается Insight с вердиктом failed."""
    ev = _eval(_readout(21))
    ins = oi.derive_insight(CONTRACT, _readout(21), ev)
    assert ins is not None and ins["kind"] == "Insight" and ins["verdict"] == "failed"


def test_insight_born_from_met_verdict():
    """Замер взял цель, guardrails в норме -> met -> Insight с вердиктом met."""
    r = _readout(40, target_met="yes",
                 guardrails=[{"name": "error_rate", "value": "1%", "within": True},
                             {"name": "latency", "value": "80", "within": True}])
    ev = _eval(r)
    assert ev["verdict"] == "met"
    ins = oi.derive_insight(CONTRACT, r, ev)
    assert ins["verdict"] == "met"


# ── (2) эпистемика разделена, уверенность падает с пробелами ─────────────────────────────────────
def test_epistemics_are_separated_observed_inferred_unknown():
    """Три раздела не свалены в один: факт замера — в observed, толкование — в inferred."""
    ev = _eval(_readout(21))
    epi = oi.derive_insight(CONTRACT, _readout(21), ev)["epistemics"]
    assert any("activation_rate" in x for x in epi["observed"])   # факт замера
    assert epi["inferred"]                                        # есть толкование
    assert set(epi) == {"observed", "inferred", "unknown"}


def test_unreported_guardrail_is_a_critical_unknown_and_lowers_confidence():
    """Guardrail объявлен в контракте, но не отчитан в readout -> критически неизвестное + уверенность ниже."""
    r_gap = _readout(21)                                    # guardrails_observed пуст: 2 не отчитаны
    ins_gap = oi.derive_insight(CONTRACT, r_gap, _eval(r_gap))
    assert any("error_rate" in u for u in ins_gap["epistemics"]["unknown"])
    assert ins_gap["confidence"] == "low"                   # несколько пробелов -> low

    r_full = _readout(40, target_met="yes", hypothesis="confirmed",
                      guardrails=[{"name": "error_rate", "value": "1%", "within": True},
                                  {"name": "latency", "value": "80", "within": True}])
    ins_full = oi.derive_insight(CONTRACT, r_full, _eval(r_full))
    assert ins_full["epistemics"]["unknown"] == []
    assert ins_full["confidence"] == "high"                 # пробелов нет -> high


# ── (3) writer ≠ judge: кандидат DRAFT, не активен; рекомендация несёт evidence ──────────────────
def test_candidate_work_is_draft_and_not_active():
    """Кандидат-работа — черновик: status draft, active False, требует решения человека."""
    ev = _eval(_readout(21))
    bundle = oi.from_outcome(CONTRACT, _readout(21), ev)
    cand = bundle["candidate_work"]
    assert cand["kind"] == "CandidateWork"
    assert cand["status"] == "draft"
    assert cand["active"] is False
    assert cand["requires_human_decision"] is True
    assert cand["source_insight"] == bundle["insight"]["id"]


def test_recommendation_carries_evidence_before_proposal():
    """Рекомендация: сколько источников, факты, допущения, критично неизвестное — потом «предлагаю»."""
    ev = _eval(_readout(21))
    rec = oi.from_outcome(CONTRACT, _readout(21), ev)["recommendation"]
    assert rec["sources"] == len(rec["facts"]) + len(rec["critical_unknowns"])
    assert rec["facts"]                          # факт есть
    assert rec["proposal"].startswith("поэтому предлагаю")
    assert "решени" in rec["note"]               # явно: решает человек


# ── проводка: post_release_loop замыкает петлю на реальном замере и молчит на unknown ────────────
def _prr_ok_result(readout):
    """run_post_release без дочки-каталога: аналитика unknown, но outcome-петля не зависит от неё."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        return prl.run_post_release(None, d, contract=CONTRACT, readout=readout)


def test_run_post_release_closes_loop_on_real_measurement():
    """На реальном замере результат несёт insight + candidate_work (draft) + recommendation."""
    res = _prr_ok_result(_readout(21))
    assert res["insight"] is not None
    assert res["candidate_work"]["status"] == "draft"
    assert res["candidate_work"]["active"] is False
    assert res["recommendation"]["proposed_work"] == res["candidate_work"]["id"]
    assert res["insight_gap"] is None
    # человекочитаемый разбор показывает и инсайт, и кандидата
    text = prl.render(res)
    assert "инсайт" in text and "кандидат-работа" in text


def test_run_post_release_says_no_data_on_unknown():
    """Без замера петля молчит: insight None, insight_gap назван, кандидата нет — не выдумываем."""
    res = _prr_ok_result(None)
    assert res["insight"] is None
    assert res["candidate_work"] is None
    assert res["insight_gap"]                      # причина названа


def test_loop_writes_nothing_to_child(tmp_path):
    """Петля read-only: после прогона в дочке не появилось ни одного файла (writer ≠ judge)."""
    root = tmp_path / "product"
    root.mkdir()
    before = set(root.rglob("*"))
    prl.run_post_release(None, root, contract=CONTRACT, readout=_readout(21))
    assert set(root.rglob("*")) == before
