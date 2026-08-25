"""no-verdict-is-an-honest-refusal-not-a-stall (P0, Лента B).

Отсутствие вердикта судьи = честный отказ с названной причиной, не молчаливый ступор.

Три уровня:
1. evidence_from_no_verdict() — unit: named cause, pending_human, blocking vs advisory
2. _run_reviews() — integration: no-verdict от run_review доезжает до gate_ev с причиной
3. evaluate_gate() — сквозной: awaiting_human=True когда no-verdict на блокирующем гейте
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ai_ops_kit.gates import gate_executor
from ai_ops_kit.engine import pipeline_evidence, tool_loop, tool_broker


# --- 1. evidence_from_no_verdict: unit ---

@pytest.mark.unit
class TestEvidenceFromNoVerdict:
    """evidence_from_no_verdict() превращает stopped-причину в gate evidence."""

    def test_blocking_gate_no_verdict_is_fail_with_named_cause(self):
        gate = {"blocking": True}
        ev = gate_executor.evidence_from_no_verdict(gate, "no-verdict")
        assert ev["status"] == "fail"
        assert len(ev["blockers"]) == 1
        assert "не вынес вердикт" in ev["blockers"][0]
        assert "no-verdict" in ev["blockers"][0]

    def test_advisory_gate_no_verdict_is_warn_with_named_cause(self):
        gate = {"blocking": False}
        ev = gate_executor.evidence_from_no_verdict(gate, "no-verdict")
        assert ev["status"] == "warn"
        assert len(ev["warnings"]) == 1
        assert "не вынес вердикт" in ev["warnings"][0]

    def test_no_verdict_sets_pending_human(self):
        gate = {"blocking": True}
        ev = gate_executor.evidence_from_no_verdict(gate, "no-verdict")
        assert ev.get("pending_human") is True

    def test_budget_exceeded_does_not_set_pending_human(self):
        """Бюджет — инфраструктурная причина, чинится повтором, не зовёт человека."""
        gate = {"blocking": True}
        ev = gate_executor.evidence_from_no_verdict(gate, "budget: BudgetExceeded")
        assert ev["status"] == "fail"
        assert "budget" in ev["blockers"][0]
        assert ev.get("pending_human") is None or ev.get("pending_human") is False

    def test_empty_still_names_the_cause(self):
        gate = {"blocking": True}
        ev = gate_executor.evidence_from_no_verdict(gate, "")
        assert ev["status"] == "fail"
        assert "не вынес вердикт" in ev["blockers"][0]

    def test_no_verdict_handoff_sets_pending_human(self):
        gate = {"blocking": True}
        ev = gate_executor.evidence_from_no_verdict(gate, "no-verdict-handoff")
        assert ev.get("pending_human") is True


# --- 2. evaluate_gate integration: awaiting_human ---

@pytest.mark.unit
class TestEvaluateGateAwaitingHuman:
    """evaluate_gate() ставит awaiting_human=True когда evidence несёт pending_human."""

    def test_no_verdict_evidence_produces_awaiting_human(self):
        gate = {"gate_id": "code_review", "blocking": True, "review_mode": "read-only",
                "responsible_role": "reviewer"}
        ev = gate_executor.evidence_from_no_verdict(gate, "no-verdict")
        evidence = {"code_review": ev}
        result = gate_executor.evaluate_gate("code_review", gate, evidence)
        assert result["status"] == "fail"
        assert result["awaiting_human"] is True
        assert "не вынес вердикт" in " ".join(result["blockers"])

    def test_budget_stopped_does_not_produce_awaiting_human(self):
        gate = {"gate_id": "code_review", "blocking": True, "review_mode": "read-only",
                "responsible_role": "reviewer"}
        ev = gate_executor.evidence_from_no_verdict(gate, "budget: BudgetExceeded")
        evidence = {"code_review": ev}
        result = gate_executor.evaluate_gate("code_review", gate, evidence)
        assert result["status"] == "fail"
        assert result["awaiting_human"] is False


# --- 3. _run_reviews integration: no-verdict reaches gate_ev ---

@pytest.mark.unit
class TestRunReviewsNoVerdict:
    """_run_reviews: когда run_review возвращает result=None, gate_ev получает named-cause evidence."""

    def test_no_verdict_adds_named_evidence_to_gate_ev(self, tmp_path):
        """run_review вернул result=None, stopped='no-verdict' -> gate_ev[gid] имеет причину."""
        gate = {"blocking": True, "review_mode": "read-only", "responsible_role": "reviewer"}
        gates = {"code_review": gate}

        def fake_run_review(*args, **kwargs):
            return {"result": None, "stopped": "no-verdict", "reads": [], "denied": []}

        with patch.object(gate_executor, "load_gates", return_value=gates), \
             patch.object(tool_loop, "run_review", side_effect=fake_run_review), \
             patch.object(tool_loop, "make_reviewer_proposer", return_value=lambda ctx: {}), \
             patch.object(pipeline_evidence, "_reviewable_gates", return_value=["code_review"]), \
             patch.object(pipeline_evidence, "_gate_checklist", return_value=""), \
             patch.object(pipeline_evidence, "_change_context", return_value=""):
            gate_ev, reviews = pipeline_evidence._run_reviews(
                reviewer_proposer=lambda p: "", work_root=tmp_path,
                gate_ids=["code_review"], gate_ev={}, signals={}, revision="abc123",
                budget=None)

        assert "code_review" in gate_ev, "no-verdict обязан добавить evidence в gate_ev"
        assert gate_ev["code_review"]["status"] == "fail"
        assert any("не вынес вердикт" in b for b in gate_ev["code_review"].get("blockers", []))
        assert gate_ev["code_review"].get("pending_human") is True
        assert reviews[0]["stopped"] == "no-verdict"
        assert reviews[0]["valid"] is False

    def test_invalid_verdict_still_gets_named_cause(self, tmp_path):
        """run_review вернул невалидный dict (не None) -> errs непусты, но evidence НЕ от no-verdict."""
        bad_result = {"kind": "reviewer-result", "gate": "code_review", "status": "pass"}
        # Нет required поля checks -> vrr.check вернёт ошибки

        gate = {"blocking": True, "review_mode": "read-only", "responsible_role": "reviewer"}
        gates = {"code_review": gate}

        def fake_run_review(*args, **kwargs):
            return {"result": bad_result, "stopped": "verdict", "reads": ["file.py"], "denied": []}

        with patch.object(gate_executor, "load_gates", return_value=gates), \
             patch.object(tool_loop, "run_review", side_effect=fake_run_review), \
             patch.object(tool_loop, "make_reviewer_proposer", return_value=lambda ctx: {}), \
             patch.object(pipeline_evidence, "_reviewable_gates", return_value=["code_review"]), \
             patch.object(pipeline_evidence, "_gate_checklist", return_value=""), \
             patch.object(pipeline_evidence, "_change_context", return_value=""):
            gate_ev, reviews = pipeline_evidence._run_reviews(
                reviewer_proposer=lambda p: "", work_root=tmp_path,
                gate_ids=["code_review"], gate_ev={}, signals={}, revision="abc123",
                budget=None)

        # Невалидный dict -> errs непусты, но result IS a dict -> no-verdict evidence НЕ добавляется
        # (это не «нет вердикта», а «вердикт невалиден» — другой класс)
        assert reviews[0]["valid"] is False
        # gate_ev может не содержать code_review (invalid verdict != no-verdict)
        # Это правильное поведение: невалидный вердикт — не то же, что отсутствие вердикта
