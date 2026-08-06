"""Unit tests for tools/tool_loop.py — action parsing and loop mechanics."""
from __future__ import annotations

import pytest

import tool_loop


@pytest.mark.unit
@pytest.mark.critical_path
class TestParseAction:
    """Tests for parse_action(): extracting JSON action proposals from model output."""

    def test_parse_action_valid_json(self):
        """Valid JSON embedded in text must be extracted."""
        result = tool_loop.parse_action('blah {"op":"read","path":"a.py"} blah')
        assert result["op"] == "read"
        assert result["path"] == "a.py"

    def test_parse_action_no_json(self):
        """Text with no JSON must return error."""
        result = tool_loop.parse_action("no json here at all")
        assert result.get("error") == "no-json"

    def test_parse_action_bad_json(self):
        """Malformed JSON (has braces but invalid content) must return bad-json error."""
        result = tool_loop.parse_action('{broken json "no colon"}')
        assert result.get("error") == "bad-json"

    def test_parse_action_dict_passthrough(self):
        """Dict input must be returned as-is (no parsing needed)."""
        action = {"op": "write", "path": "x.py", "content": "hello"}
        result = tool_loop.parse_action(action)
        assert result is action

    def test_parse_action_done(self):
        """Done action must be parsed correctly."""
        result = tool_loop.parse_action('{"done": true, "summary": "all done"}')
        assert result["done"] is True
        assert result["summary"] == "all done"

    def test_parse_action_empty_string(self):
        """Empty string must return no-json error."""
        result = tool_loop.parse_action("")
        assert result.get("error") == "no-json"

    def test_parse_action_none(self):
        """None input must return no-json error."""
        result = tool_loop.parse_action(None)
        assert result.get("error") == "no-json"


@pytest.mark.unit
@pytest.mark.critical_path
class TestRunLoop:
    """Tests for run_loop(): tool-calling loop mechanics with mock proposers."""

    @pytest.fixture
    def loop_deps(self, tmp_path):
        """Minimal setup: import tool_broker, create a policy and a temp root."""
        import tool_broker
        import budget as budget_mod

        root = tmp_path / "loop-root"
        root.mkdir()
        (root / "src").mkdir()
        (root / "f.txt").write_text("content", encoding="utf-8")
        policy = tool_broker.Policy(level="execution", write_scope=["src/"])
        return policy, root, budget_mod

    def test_run_loop_done_immediate(self, loop_deps):
        """Proposer returns done on first step -> loop stops immediately."""
        policy, root, budget_mod = loop_deps
        proposer = lambda ctx: {"done": True, "summary": "instant done"}
        report = tool_loop.run_loop(proposer, root, policy, budget={"max_model_calls": 5})
        assert report["stopped"] == "done"
        assert report["steps"] == 1
        assert report["model_calls"] == 1

    def test_run_loop_budget_exceeded(self, loop_deps):
        """Budget limit stops the loop."""
        policy, root, budget_mod = loop_deps
        # Proposer always returns a read action (never done)
        proposer = lambda ctx: {"op": "read", "path": "f.txt"}
        report = tool_loop.run_loop(proposer, root, policy, budget={"max_model_calls": 2})
        assert report["stopped"].startswith("budget")
        assert report["model_calls"] == 2

    def test_run_loop_max_steps(self, loop_deps):
        """max_steps acts as a safety limit."""
        policy, root, budget_mod = loop_deps
        proposer = lambda ctx: {"op": "read", "path": "f.txt"}
        report = tool_loop.run_loop(proposer, root, policy,
                                    budget={"max_model_calls": 100}, max_steps=3)
        assert report["stopped"] == "max_steps"
        assert report["steps"] == 3

    def test_run_loop_bad_proposals_stop(self, loop_deps):
        """N consecutive bad proposals stop the loop."""
        policy, root, budget_mod = loop_deps
        proposer = lambda ctx: {"error": "bad-json"}
        report = tool_loop.run_loop(proposer, root, policy,
                                    budget={"max_model_calls": 10},
                                    max_bad_proposals=3)
        assert report["stopped"].startswith("bad-proposal")

    def test_run_loop_write_outside_scope_denied(self, loop_deps):
        """Write outside write_scope must be denied by policy."""
        policy, root, budget_mod = loop_deps
        steps = iter([
            {"op": "write", "path": "outside/a.py", "content": "x"},
            {"done": True, "summary": "done"},
        ])
        proposer = lambda ctx: next(steps)
        report = tool_loop.run_loop(proposer, root, policy, budget={"max_model_calls": 5})
        assert report["stopped"] == "done"
        assert any(e["op"] == "write" for e in report["denied"])
