"""Гранулярные тесты lifecycle_intent (мигрировано из test_lifecycle_intent_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.lifecycle.lifecycle_intent import (
    ALL_STATES,
    derive,
    intent_to_lifecycle,
    validate_transition,
)


@pytest.mark.unit
class TestDerive:
    def test_draft_no_evidence(self):
        assert derive("draft") == "discovery"

    def test_draft_with_evidence(self):
        assert derive("draft", has_evidence=True) == "implementation"

    def test_done_no_pr(self):
        assert derive("done") == "implementation"

    def test_done_with_pr(self):
        assert derive("done", has_pr=True) == "review"

    def test_done_with_merged_pr(self):
        assert derive("done", has_pr=True, pr_merged=True) == "delivery"

    def test_done_with_receipt(self):
        assert derive("done", has_receipt=True) == "completed"

    def test_needs_human_decision(self):
        assert derive("needs_human_decision") == "review"

    def test_blocked_no_evidence(self):
        assert derive("blocked") == "discovery"

    def test_blocked_with_evidence(self):
        assert derive("blocked", has_evidence=True) == "implementation"

    def test_terminal_state_priority(self):
        assert derive("done", has_receipt=True, terminal_state="cancelled") == "cancelled"


@pytest.mark.unit
class TestValidateTransition:
    def test_discovery_to_implementation(self):
        assert validate_transition("discovery", "implementation") is True

    def test_implementation_to_review(self):
        assert validate_transition("implementation", "review") is True

    def test_review_to_delivery(self):
        assert validate_transition("review", "delivery") is True

    def test_delivery_to_completed(self):
        assert validate_transition("delivery", "completed") is True

    def test_completed_to_discovery_forbidden(self):
        assert validate_transition("completed", "discovery") is False

    def test_cancelled_to_implementation_forbidden(self):
        assert validate_transition("cancelled", "implementation") is False


@pytest.mark.unit
class TestIntentToLifecycle:
    def test_discuss(self):
        assert intent_to_lifecycle("discuss") == "discovery"

    def test_run(self):
        assert intent_to_lifecycle("run") == "implementation"

    def test_review(self):
        assert intent_to_lifecycle("review") == "review"

    def test_resume_none(self):
        assert intent_to_lifecycle("resume") is None


@pytest.mark.unit
class TestAllStates:
    def test_main_states(self):
        assert all(s in ALL_STATES for s in ("discovery", "implementation", "review", "delivery", "completed"))

    def test_terminal_states(self):
        assert all(s in ALL_STATES for s in ("cancelled", "superseded", "abandoned"))
