"""Проверки прогонщика корпуса gate-евалов (C1, v3.37).

Корпус мерит устойчивость судейского вердикта. Значит, сам прогонщик обязан краснеть там, где
вердикт поплыл, — иначе он был бы ровно тем «зелёным без содержания», против которого заведён.
Поэтому здесь не только «форма разбирается», но и пробы: подмена замороженного вердикта, подмена
ожидаемого, пустой список ответов судьи. Каждая обязана быть поймана.
"""
from __future__ import annotations

import copy

import pytest

from ai_ops_kit.devtools import gate_evals
from ai_ops_kit.gates.gate_executor import load_gates

GATES = load_gates()


def _no_judge_case(**over):
    c = {
        "schema_version": 1, "kind": "gate-evaluation-case", "id": "probe-no-judge",
        "gate": "code_review", "case_kind": "no_judge", "summary": "проба",
        "origin": {"source": "проба", "provenance": "contract_invariant"},
        "signals": {},
        "expected": {"status": "fail", "reason_matches": ["code-reviewer"]},
    }
    c.update(over)
    return c


_JUDGE_FAIL_TEXT = (
    "## Code Review\nНайден фиктивный селфтест.\n\n"
    '{"schema_version":1,"kind":"reviewer-result","gate":"code_review","status":"fail",'
    '"checks":[{"id":"selftest_asserts","status":"fail"}],'
    '"blockers":["ветка --selftest печатает PASSED, не вызвав ни одной проверяемой функции"]}\n'
)


def _judge_case(**over):
    c = {
        "schema_version": 1, "kind": "gate-evaluation-case", "id": "probe-judge",
        "gate": "code_review", "case_kind": "judge_output", "summary": "проба",
        "origin": {"source": "проба", "provenance": "class_repro"},
        "signals": {},
        "expected": {"status": "fail", "reason_matches": ["selftest"]},
        "input": {"task": "ревью", "diff_file": "probe-judge.patch",
                  "diff": "diff --git a/x b/x\n+x\n"},
        # `transcript` — имя файла улики; `text` подставляет загрузчик, здесь он задан напрямую
        "recorded": [{"recorded_at": "2026-08-20T00:00:00+00:00", "provider": "probe",
                      "model": "", "derived_status": "fail", "transcript": "probe-judge-1.md",
                      "text": _JUDGE_FAIL_TEXT}],
    }
    c.update(over)
    return c


# ---------------------------------------------------------------- форма кейса

def test_valid_cases_have_no_form_errors():
    assert gate_evals.case_form_errors(_no_judge_case(), "probe") == []
    assert gate_evals.case_form_errors(_judge_case(), "probe") == []


@pytest.mark.parametrize("mutate, needle", [
    ({"kind": "something-else"}, "kind"),
    ({"schema_version": 2}, "schema_version"),
    ({"case_kind": "guess"}, "case_kind"),
    ({"origin": {"source": "x", "provenance": "invented"}}, "provenance"),
    ({"expected": {"status": "green", "reason_matches": ["x"]}}, "expected.status"),
    ({"expected": {"status": "fail", "reason_matches": []}}, "fail без reason_matches"),
    ({"expected": {"status": "pass", "reason_matches": []}}, "pass без судьи"),
])
def test_form_errors_are_caught(mutate, needle):
    errs = gate_evals.case_form_errors(_no_judge_case(**mutate), "probe")
    assert any(needle in e for e in errs), f"не поймано {needle}: {errs}"


@pytest.mark.parametrize("mutate, needle", [
    ({"input": {"task": "", "diff_file": "x.patch"}}, "input.task"),
    ({"input": {"task": "ревью"}}, "input.diff_file"),
    ({"recorded": [{"recorded_at": "2026-08-20", "provider": "p", "transcript": "t.md"}]},
     "derived_status"),
    ({"recorded": [{"provider": "p", "derived_status": "fail", "transcript": "t.md"}]},
     "recorded_at"),
    ({"recorded": [{"recorded_at": "2026-08-20", "provider": "p", "derived_status": "fail"}]},
     "transcript"),
])
def test_judge_case_form_errors_are_caught(mutate, needle):
    errs = gate_evals.case_form_errors(_judge_case(**mutate), "probe")
    assert any(needle in e for e in errs), f"не поймано {needle}: {errs}"


def test_case_on_a_validator_gate_needs_an_explicit_control_flag():
    """Гейт с валидатором в корпусе мнений — только как объявленный контроль."""
    c = _no_judge_case(gate="intake_completeness",
                       expected={"status": "fail", "reason_matches": ["validate-intake"]})
    assert any("validator_control" in e for e in gate_evals.corpus_registry_errors([c], GATES))
    c["validator_control"] = True
    assert gate_evals.corpus_registry_errors([c], GATES) == []


def test_case_on_an_unknown_gate_is_a_corpus_error():
    c = _no_judge_case(gate="gate_that_does_not_exist")
    assert any("нет в quality/gates.yaml" in e
               for e in gate_evals.corpus_registry_errors([c], GATES))


# ---------------------------------------------------------------- производная цепочка

def test_derive_verdict_uses_the_production_chain():
    """Без судьи блокирующий судейский гейт красный, и роль названа — это `evaluate_gate`,
    а не своя копия решения."""
    r = gate_evals.derive_verdict(_no_judge_case(), None, GATES)
    assert r["status"] == "fail" and r["blocking"] is True
    assert any("code-reviewer" in b for b in r["blockers"])


def test_derive_verdict_reads_the_structural_reviewer_result():
    r = gate_evals.derive_verdict(_judge_case(), _JUDGE_FAIL_TEXT, GATES)
    assert r["status"] == "fail"
    assert any("selftest" in b for b in r["blockers"])


def test_signals_switch_applicability_and_the_reason_is_named():
    """Третье состояние: без сигнала гейт неприменим и ГОВОРИТ об этом; с сигналом — блокирует."""
    off = gate_evals.derive_verdict(
        _no_judge_case(gate="architecture_review",
                       expected={"status": "pass", "reason_matches": ["неприменим"]}), None, GATES)
    assert off["status"] == "pass" and off["blocking"] is False
    assert any("неприменим" in w for w in off["warnings"])

    on = gate_evals.derive_verdict(
        _no_judge_case(gate="architecture_review", signals={"architecture_change": True}),
        None, GATES)
    assert on["status"] == "fail" and on["blocking"] is True


# ---------------------------------------------------------------- пробы: прогонщик обязан краснеть

def test_replay_reports_ok_on_an_intact_case():
    assert gate_evals.replay_case(_no_judge_case(), GATES)["outcome"] == "ok"
    assert gate_evals.replay_case(_judge_case(), GATES)["outcome"] == "ok"


def test_replay_goes_red_when_the_frozen_verdict_no_longer_matches():
    """ПРОБА: если разбор ответа судьи однажды даст другой вердикт при том же тексте — красное."""
    c = copy.deepcopy(_judge_case())
    c["recorded"][0]["derived_status"] = "pass"
    r = gate_evals.replay_case(c, GATES)
    assert r["outcome"] == "drift"
    assert any("изменился РАЗБОР" in d for d in r["detail"])


def test_replay_goes_red_when_the_verdict_differs_from_expected():
    c = copy.deepcopy(_judge_case())
    c["expected"] = {"status": "pass", "reason_matches": []}
    c["recorded"][0]["derived_status"] = "pass"
    r = gate_evals.replay_case(c, GATES)
    assert r["outcome"] == "drift"


def test_replay_goes_red_when_the_reason_is_not_named():
    """Красное без названной причины неотличимо от красного по другому поводу."""
    c = copy.deepcopy(_judge_case())
    c["expected"]["reason_matches"] = ["совершенно другая причина"]
    r = gate_evals.replay_case(c, GATES)
    assert r["outcome"] == "drift"
    assert any("причина не названа" in d for d in r["detail"])


def test_replay_goes_red_when_measured_agreement_drops():
    """Ратчет устойчивости: замеренное согласие не должно молча становиться хуже."""
    c = copy.deepcopy(_judge_case())
    c["stability"] = {"measured_at": "2026-08-20", "runs": 3, "agreement": "3/3",
                      "verdicts": ["fail", "fail", "fail"]}
    r = gate_evals.replay_case(c, GATES)
    assert r["outcome"] == "drift"
    assert any("согласие вердиктов" in d for d in r["detail"])


def test_a_case_without_recorded_answers_is_unavailable_not_ok():
    """Третье состояние не сворачивается во второе."""
    c = _judge_case(recorded=[])
    r = gate_evals.replay_case(c, GATES)
    assert r["outcome"] == "unavailable"
    assert r["outcome"] != "ok"
    rep = gate_evals.run_corpus([c], GATES)
    assert rep["counts"]["unavailable"] == 1
    assert "НЕ ИЗМЕРЕНО" in gate_evals.format_report(rep)


def test_unavailable_is_visible_in_the_report_and_not_counted_as_ok():
    rep = gate_evals.run_corpus([_judge_case(recorded=[]), _no_judge_case()], GATES)
    assert rep["counts"] == {"ok": 1, "drift": 0, "unavailable": 1}
    assert "не измерено 1" in gate_evals.format_report(rep)


# ---------------------------------------------------------------- отчёт и охват

def test_report_names_coverage_as_a_number_over_all_judged_gates():
    rep = gate_evals.run_corpus([_no_judge_case()], GATES)
    cov = rep["coverage"]
    judged = [g for g, v in GATES.items() if v.get("closed_by") in ("judge", "writer")]
    assert cov["judged_gates_total"] == len(judged) <= 19
    assert cov["judged_gates_with_cases"] == 1
    assert "code_review" in cov["gates_with_cases"]
    assert "security" in cov["gates_without_cases"]


def test_corpus_is_not_clean_when_a_case_drifts():
    c = copy.deepcopy(_judge_case())
    c["recorded"][0]["derived_status"] = "pass"
    assert gate_evals.run_corpus([c], GATES)["clean"] is False
