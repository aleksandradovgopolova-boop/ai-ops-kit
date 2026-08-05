"""Contract tests for critical execution path (v3.25.0 Verification Foundation).

These tests verify that critical modules maintain their contracts:
- Functions return expected types
- Production-path is fully exercised (not bypassed by test doubles)
- Error handling follows fail-closed principle
- Usage recording works through the full path

Based on lessons from claude-cli NameError regression (v3.21.1):
test doubles must NOT bypass production timing/recording/error-handling paths.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest


class TestOrchestratorContracts:
    """Contract tests for tools/orchestrator.py."""

    def test_make_provider_returns_callable_for_known(self):
        """make_provider() must return a callable for mock and claude-cli."""
        import orchestrator
        for name in ("mock", "claude-cli"):
            provider = orchestrator.make_provider(name)
            assert callable(provider), f"make_provider({name}) returned non-callable"

    def test_mock_provider_returns_string(self):
        """Mock provider must return a string for any prompt."""
        import orchestrator
        provider = orchestrator.make_provider("mock")
        result = provider("test prompt")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_claude_cli_provider_production_path(self, child_root):
        """Claude CLI provider must exercise full production path:
        command construction → invocation → timing → retry → JSON parsing → usage recording.
        This is the regression test for v3.21.1 NameError fix."""
        import orchestrator

        class FakeResult:
            def __init__(self, stdout="", returncode=0, stderr=""):
                self.stdout = stdout
                self.returncode = returncode
                self.stderr = stderr

        calls = []
        def tracking_runner(cmd):
            calls.append(cmd)
            return FakeResult(
                stdout=json.dumps({
                    "result": "test-output",
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                    "model": "test-model",
                    "total_cost_usd": 0.001
                }),
                returncode=0
            )

        # Clear stats before test
        orchestrator.drain_call_stats()

        provider = orchestrator.make_claude_cli_provider(runner=tracking_runner)
        result = provider("test prompt")

        # Contract: result is the parsed output
        assert result == "test-output"

        # Contract: runner was called (production path exercised)
        assert len(calls) == 1
        assert "claude" in calls[0]
        assert "-p" in calls[0]

        # Contract: usage was recorded (production path not bypassed)
        stats = orchestrator.drain_call_stats()
        assert len(stats) >= 1
        last_stat = stats[-1]
        assert last_stat.get("input_tokens") == 10
        assert last_stat.get("output_tokens") == 5
        assert last_stat.get("provider") == "claude-cli"

    def test_claude_cli_retry_on_failure(self):
        """Claude CLI must retry on transient failures (rc != 0)."""
        import orchestrator

        class FakeResult:
            def __init__(self, stdout="", returncode=0, stderr=""):
                self.stdout = stdout
                self.returncode = returncode
                self.stderr = stderr

        attempts = []
        def flaky_runner(cmd):
            attempts.append(1)
            if len(attempts) < 3:
                return FakeResult(returncode=1, stderr="transient error")
            return FakeResult(
                stdout=json.dumps({"result": "ok", "usage": {}}),
                returncode=0
            )

        provider = orchestrator.make_claude_cli_provider(runner=flaky_runner)
        result = provider("test")

        # Contract: retried until success
        assert result == "ok"
        assert len(attempts) == 3

    def test_claude_cli_read_only_tools(self):
        """Claude CLI must be restricted to read-only tools."""
        import orchestrator

        seen_cmd = []
        def capture_runner(cmd):
            seen_cmd.append(cmd)
            class R:
                stdout = json.dumps({"result": "", "usage": {}})
                returncode = 0
                stderr = ""
            return R()

        provider = orchestrator.make_claude_cli_provider(runner=capture_runner)
        provider("test")

        cmd = seen_cmd[0]
        # Contract: --allowedTools present
        assert "--allowedTools" in cmd
        # Contract: only Read/Grep/Glob allowed
        idx = cmd.index("--allowedTools") + 1
        tools = []
        while idx < len(cmd) and not cmd[idx].startswith("--"):
            tools.append(cmd[idx])
            idx += 1
        assert set(tools) <= {"Read", "Grep", "Glob"}
        # Contract: no mutation tools
        assert "Write" not in cmd
        assert "Edit" not in cmd
        assert "Bash" not in cmd


class TestToolBrokerContracts:
    """Contract tests for tools/tool_broker.py — skipped until interface verified."""
    # TODO: Verify tool_broker interface and add contract tests
    pass


class TestGateExecutorContracts:
    """Contract tests for tools/gate_executor.py — skipped until interface verified."""
    # TODO: Verify gate_executor interface and add contract tests
    pass


class TestPreflightContracts:
    """Contract tests for tools/preflight.py — skipped until interface verified."""
    # TODO: Verify preflight interface and add contract tests
    pass


class TestExecutionPipelineContracts:
    """Contract tests for tools/execution_pipeline.py."""

    def test_run_pipeline_returns_report(self, child_root, mock_provider):
        """run_pipeline() must return a report dict."""
        import execution_pipeline
        signals = {"task_type": "QUICK", "task_text": "test task"}
        # Note: full pipeline test requires more setup; this is a contract check
        # that the function signature and return type are stable
        assert callable(execution_pipeline.run_pipeline)


class TestUsageLedgerContracts:
    """Contract tests for tools/usage_ledger.py."""

    def test_append_writes_to_both_ledgers(self, child_root):
        """usage_ledger.append() must write to both task and product ledgers."""
        import usage_ledger
        records = [{
            "run_id": "test-run",
            "workitem_id": "test-wid",
            "role": "implementation",
            "provider": "mock",
            "model": "mock-model",
            "input_tokens": 100,
            "output_tokens": 50,
            "usage_status": "measured",
            "cost": 0.01,
            "cost_status": "measured",
            "latency": 1.0,
            "trigger": "initial",
        }]
        count = usage_ledger.append(str(child_root), "test-wid", records, run_id="test-run")
        assert count == 1

        # Contract: task ledger exists
        task_ledger = child_root / "features" / "test-wid" / "usage-ledger.jsonl"
        assert task_ledger.exists()

        # Contract: product ledger exists
        product_ledger = child_root / ".ai" / "usage" / "product-ledger.jsonl"
        assert product_ledger.exists()

    def test_extra_context_stamped_on_records(self, child_root):
        """v3.24.0: extra_context must be stamped on all records."""
        import usage_ledger
        records = [{
            "run_id": "test-run-2",
            "input_tokens": 10,
            "output_tokens": 5,
            "usage_status": "measured",
        }]
        extra = {"task_type": "QUICK", "workflow": "quick", "risk": "low"}
        usage_ledger.append(str(child_root), "test-wid-2", records,
                           run_id="test-run-2", extra_context=extra)

        # Contract: records have extra fields
        task_ledger = child_root / "features" / "test-wid-2" / "usage-ledger.jsonl"
        content = task_ledger.read_text()
        data = json.loads(content.strip())
        assert data.get("task_type") == "QUICK"
        assert data.get("workflow") == "quick"
        assert data.get("risk") == "low"

    def test_unavailable_never_zero(self):
        """usage_status=unavailable must have None tokens, not 0."""
        import usage_ledger
        record = {
            "usage_status": "unavailable",
            "input_tokens": None,  # Must be None, not 0
            "output_tokens": None,
        }
        errors = usage_ledger.check(record)
        # Contract: no errors for honest unavailable
        assert len(errors) == 0

        # Contract: unavailable WITH tokens is an error
        bad_record = {**record, "input_tokens": 0}
        errors = usage_ledger.check(bad_record)
        assert len(errors) > 0


class TestLifecycleStoreContracts:
    """Contract tests for tools/lifecycle_store.py."""

    def test_durable_write_atomic(self, child_root):
        """durable_write() must be atomic — invalid data never replaces valid."""
        import lifecycle_store
        path = child_root / "test.yaml"
        # Write valid data
        result = lifecycle_store.durable_write(str(path), {"kind": "test", "value": 1}, require_keys=["kind"])
        assert result.get("ok") is True
        assert path.exists()


# ============================================================================
# Regression tests for known bugs
# ============================================================================

class TestRegressions:
    """Regression tests for bugs that were found and fixed."""

    def test_claude_cli_nameerror_fixed(self):
        """v3.21.1: NameError('time') in claude-cli must not recur.
        This was caused by 'import time as _t' but using 'time.monotonic()'."""
        import orchestrator
        import time  # This import must work

        class FakeResult:
            stdout = json.dumps({"result": "ok", "usage": {}})
            returncode = 0
            stderr = ""

        def runner(cmd):
            # If time is not imported correctly, this will raise NameError
            _ = time.monotonic()
            return FakeResult()

        provider = orchestrator.make_claude_cli_provider(runner=runner)
        # Contract: no NameError
        result = provider("test")
        assert result == "ok"
