"""Гранулярные тесты session_guardrails (мигрировано из test_session_guardrails_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import pytest

from session_guardrails import (
    SESSION_ECONOMY_DEFAULTS,
    check,
    classify_context,
    completion_ritual,
    recommend,
    render_block,
)


@pytest.fixture
def defaults():
    return SESSION_ECONOMY_DEFAULTS


@pytest.fixture
def snap_factory():
    def _snap(ctx, wid="WI-1"):
        return {
            "kind": "SessionTelemetry",
            "context_current": ctx,
            "context_status": "estimated",
            "workitem_id": wid,
            "input_tokens": 1,
            "output_tokens": 1,
            "estimated_cost": 1.0,
            "cost_complete": True,
            "turns": 5,
        }
    return _snap


@pytest.mark.unit
class TestClassifyContext:
    def test_100k_normal(self, defaults):
        assert classify_context(100_000, defaults) == "normal"

    def test_180k_attention(self, defaults):
        assert classify_context(180_000, defaults) == "attention"

    def test_300k_compact_recommended(self, defaults):
        assert classify_context(300_000, defaults) == "compact_recommended"

    def test_450k_new_session_recommended(self, defaults):
        assert classify_context(450_000, defaults) == "new_session_recommended"

    def test_none_unknown(self, defaults):
        assert classify_context(None, defaults) == "unknown"


@pytest.mark.unit
class TestRecommend:
    def test_same_wi_light_context_not_done_continue(self, defaults, snap_factory):
        r = recommend(snap_factory(92_000), defaults, next_relation="continuation", task_done=False)
        assert r["outcome"] == "continue"
        assert r["command"] is None

    def test_same_wi_expensive_context_not_done_compact(self, defaults, snap_factory):
        r = recommend(snap_factory(271_000), defaults, next_relation="same_task", task_done=False)
        assert r["outcome"] == "compact"
        assert "/compact" in r["command"]

    def test_new_independent_task_done_clear(self, defaults, snap_factory):
        r = recommend(snap_factory(318_000), defaults, next_relation="new_independent_task", task_done=True, repo_path="/x")
        assert r["outcome"] == "clear"
        assert "/clear" in r["command"]

    def test_context_over_400k_new_session(self, defaults, snap_factory):
        r = recommend(snap_factory(450_000), defaults, next_relation="new_independent_task", task_done=True, repo_path="/x")
        assert r["outcome"] == "new_session"
        assert "claude" in r["command"]

    def test_context_over_400k_continuation_not_done_compact(self, defaults, snap_factory):
        r = recommend(snap_factory(450_000), defaults, next_relation="continuation", task_done=False)
        assert r["outcome"] == "compact"

    def test_unsafe_boundary_defer(self, defaults, snap_factory):
        r = recommend(snap_factory(300_000), defaults, next_relation="new_independent_task", task_done=True, at_safe_boundary=False)
        assert r["outcome"] == "defer"
        assert r["command"] is None


@pytest.mark.unit
class TestCompletionRitual:
    def test_ritual_clear_and_next_command(self, defaults, snap_factory, tmp_path):
        from ai_ops_kit.engops import session_handoff as _sh
        _sh.write(tmp_path, _sh.build(tmp_path, snap_factory(318_000), goal="тест"))

        rit = completion_ritual(
            snap_factory(318_000), defaults, workitem_id="WI-1", pr="PR#48",
            checks="183/183", next_relation="new_independent_task",
            next_task="Environment Discovery", repo_path=str(tmp_path),
        )
        assert rit["session_recommendation"]["outcome"] == "clear"
        assert rit["next_command"]
        assert check(rit) == []

    def test_ritual_complete_all_checks(self, defaults, snap_factory, tmp_path):
        from ai_ops_kit.engops import session_handoff as _sh
        _sh.write(tmp_path, _sh.build(tmp_path, snap_factory(318_000), goal="тест"))

        rit = completion_ritual(
            snap_factory(318_000), defaults, workitem_id="WI-1", pr="PR#48",
            checks="183/183", next_relation="new_independent_task",
            next_task="Environment Discovery", repo_path=str(tmp_path),
        )
        assert rit["complete"] is True

    def test_no_handoff_ritual_not_complete(self, defaults, snap_factory, tmp_path):
        rit = completion_ritual(
            snap_factory(318_000), defaults, workitem_id="WI-1", pr="PR#48",
            checks="183/183", next_relation="new_independent_task",
            repo_path=str(tmp_path / "нет"),
        )
        assert rit["complete"] is False

    def test_render_block_contains_pr_cost_recommendation_command(self, defaults, snap_factory, tmp_path):
        from ai_ops_kit.engops import session_handoff as _sh
        _sh.write(tmp_path, _sh.build(tmp_path, snap_factory(318_000), goal="тест"))

        rit = completion_ritual(
            snap_factory(318_000), defaults, workitem_id="WI-1", pr="PR#48",
            checks="183/183", next_relation="new_independent_task",
            next_task="Environment Discovery", repo_path=str(tmp_path),
        )
        block = render_block(rit)
        assert "PR#48" in block
        assert "Рекомендация" in block
        assert "/clear" in block

    def test_no_pr_commit_checks_ritual_not_complete(self, defaults, snap_factory):
        rit2 = completion_ritual(
            snap_factory(92_000, wid="WI-1"), defaults, workitem_id="WI-1",
            pr=None, checks=None, next_relation="continuation", committed=False,
        )
        assert rit2["complete"] is False
