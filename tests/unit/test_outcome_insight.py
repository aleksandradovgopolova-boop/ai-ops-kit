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
    assert res["next_action"] is None             # #987: без замера — «что дальше» из петли НЕТ
    assert res["insight_gap"]                      # причина названа


# ── (P0 №4, #987) последний шаг петли: КОНКРЕТНОЕ действие + «потому что <что произошло с продуктом>» ──
_JARGON = ("baseline", "gate", "write_scope", "tested_revision", "sha", "budget", "verdict",
           "insight", "outcome", "candidate", "guardrail")


def _assert_no_jargon(text: str):
    low = text.lower()
    for term in _JARGON:
        assert term not in low, f"внутренний термин «{term}» в лицо человеку: {text!r}"


def test_next_action_on_failed_grounds_reason_in_the_product():
    """failed -> действие «разобраться/скорректировать», обоснование = метрика НЕ взяла цель (числа)."""
    r = _readout(21)
    bundle = oi.from_outcome(CONTRACT, r, _eval(r))
    na = bundle["next_action"]
    assert na is not None and na["kind"] == "NextAction" and na["verdict"] == "failed"
    assert na["action"] == bundle["candidate_work"]["title"]      # действие — из DRAFT-кандидата
    assert na["candidate_id"] == bundle["candidate_work"]["id"]
    # обоснование от произошедшего с продуктом: имя метрики, замер и цель — реальные числа
    assert "activation_rate" in na["because"]
    assert "21" in na["because"] and "35" in na["because"]
    assert "не взяла" in na["because"]
    _assert_no_jargon(na["because"])                              # (д) без жаргона в лицо product


def test_next_action_on_met_grounds_reason_in_the_product():
    """met -> действие «закрепить и выбрать следующую гипотезу», обоснование = цель взята (числа)."""
    r = _readout(40, target_met="yes", hypothesis="confirmed",
                 guardrails=[{"name": "error_rate", "value": "1%", "within": True},
                             {"name": "latency", "value": "80", "within": True}])
    na = oi.from_outcome(CONTRACT, r, _eval(r))["next_action"]
    assert na["verdict"] == "met"
    assert "дошла до 40" in na["because"] and "цели 35" in na["because"]
    assert "гипотеза подтвердилась" in na["because"]              # разрешённая гипотеза — в обосновании
    _assert_no_jargon(na["because"])


def test_next_action_on_refuted_hypothesis_is_a_valid_revise_input():
    """Гипотеза не подтвердилась — валидный вход: пересмотреть подход, потому что метрика не сдвинулась."""
    r = _readout(20, hypothesis="refuted")               # замер == старт (baseline 20): не сдвинулась
    na = oi.from_outcome(CONTRACT, r, _eval(r))["next_action"]
    assert na["verdict"] == "failed"
    assert "не сдвинулась" in na["because"]
    assert "гипотеза не подтвердилась" in na["because"]
    _assert_no_jargon(na["because"])


def test_next_action_does_not_fabricate_unresolved_hypothesis():
    """inconclusive-гипотеза в обоснование НЕ попадает — причину не сочиняем (no evidence → no claim)."""
    r = _readout(21, hypothesis="inconclusive")
    na = oi.from_outcome(CONTRACT, r, _eval(r))["next_action"]
    assert "гипотеза" not in na["because"]


def test_next_action_absent_on_unknown_verdict():
    """Замера нет -> вердикт unknown -> next_action None: «что дальше» из петли не выдумывается."""
    assert oi.next_action(None, None, vpo.evaluate_outcome(CONTRACT, None)) is None


def test_run_post_release_next_action_reaches_result_on_measurement():
    """Проводка: на реальном замере результат петли несёт next_action с действием и обоснованием."""
    res = _prr_ok_result(_readout(21))
    na = res["next_action"]
    assert na and na["action"] and na["because"]
    text = prl.render(res)
    assert "что делать дальше" in text and "потому что" in text


# ── проводка до `next`: источник, который читает `next` (_inbox_outcome_candidate), несёт действие ──
import yaml as _yaml  # noqa: E402


def _write_outcome(root, *, with_measurement):
    (root / "outcome-contract.yaml").write_text(
        _yaml.safe_dump(CONTRACT, allow_unicode=True), encoding="utf-8")
    if with_measurement:
        (root / "outcome-readout.yaml").write_text(
            _yaml.safe_dump(_readout(21), allow_unicode=True), encoding="utf-8")


def test_next_source_surfaces_action_and_because_on_measurement(tmp_path):
    """`next` берёт кандидата из _inbox_outcome_candidate: на замере тот несёт КОНКРЕТНОЕ действие и
    обоснование «потому что <что произошло с продуктом>» — без внутренних терминов."""
    from ai_ops_kit.cli.ai_ops_cli_report import _inbox_outcome_candidate
    _write_outcome(tmp_path, with_measurement=True)
    cand = _inbox_outcome_candidate(tmp_path)
    assert cand is not None
    assert cand["action"] and cand["because"]
    assert "activation_rate" in cand["because"] and "не взяла" in cand["because"]
    _assert_no_jargon(cand["because"])


def test_next_source_adds_nothing_without_measurement(tmp_path):
    """Нет замера (только контракт) -> кандидата из петли нет: `next` НИЧЕГО не добавляет (no false claim)."""
    from ai_ops_kit.cli.ai_ops_cli_report import _inbox_outcome_candidate
    _write_outcome(tmp_path, with_measurement=False)
    assert _inbox_outcome_candidate(tmp_path) is None


def test_loop_writes_nothing_to_child(tmp_path):
    """Петля read-only: после прогона в дочке не появилось ни одного файла (writer ≠ judge)."""
    root = tmp_path / "product"
    root.mkdir()
    before = set(root.rglob("*"))
    prl.run_post_release(None, root, contract=CONTRACT, readout=_readout(21))
    assert set(root.rglob("*")) == before
