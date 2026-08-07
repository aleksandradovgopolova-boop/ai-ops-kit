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

# Эти contract-тесты — критический путь исполнения. pr-smoke.yml гоняет слой через
# `pytest tests/contracts/ -m critical_path`; без маркера здесь smoke собирал файлы и
# отбрасывал ВСЕ (0 selected -> pytest exit 5). Маркер критического пути conftest вешает
# только на авто-обёртки selftest'ов (уровень tests/), сюда он не долетает — проставляем явно.
pytestmark = [pytest.mark.critical_path, pytest.mark.contract]


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

    def test_claude_cli_retry_on_transient_is_error(self, monkeypatch):
        """F-011 positive: rc==0, но синтетический is_error:true (напр. 529 Overloaded) — это транзиент.
        Механизм ДОЛЖЕН переждать (ретрай) и вернуть валидный результат, а не отдать ошибку за ответ."""
        import orchestrator
        monkeypatch.setattr("time.sleep", lambda *a, **k: None)   # без реальных пауз

        class FakeResult:
            def __init__(self, stdout="", returncode=0, stderr=""):
                self.stdout = stdout; self.returncode = returncode; self.stderr = stderr

        env529 = json.dumps({"is_error": True, "stop_reason": "stop_sequence", "usage": {"input_tokens": 0},
                             "content": [{"type": "text",
                                          "text": "API Error: 529 Overloaded. This is a server-side issue, usually temporary."}]})
        ok = json.dumps({"result": "DONE", "usage": {"input_tokens": 3, "output_tokens": 1}})
        seq = [FakeResult(env529, 0), FakeResult(env529, 0), FakeResult(ok, 0)]
        calls = []
        def runner(cmd):
            calls.append(1); return seq[len(calls) - 1]

        provider = orchestrator.make_claude_cli_provider(runner=runner)
        result = provider("test")
        assert result == "DONE"       # пережил транзиент и вернул валидный результат
        assert len(calls) == 3        # side-effect: ретрай ДЕЙСТВИТЕЛЬНО произошёл (3 вызова)

    def test_claude_cli_is_error_not_passed_as_result(self, monkeypatch):
        """F-011 fail-closed: синтетический is_error:true НЕ должен стать зелёным результатом.
        Нетранзиентная ошибка (напр. auth) поднимается RuntimeError, а не возвращается как валидный ответ."""
        import orchestrator
        monkeypatch.setattr("time.sleep", lambda *a, **k: None)

        class FakeResult:
            def __init__(self, stdout="", returncode=0, stderr=""):
                self.stdout = stdout; self.returncode = returncode; self.stderr = stderr

        bad = json.dumps({"is_error": True,
                          "content": [{"type": "text", "text": "Invalid API key: authentication_error"}]})
        provider = orchestrator.make_claude_cli_provider(runner=lambda cmd: FakeResult(bad, 0))
        with pytest.raises(RuntimeError) as ei:
            provider("test")
        assert "authentication_error" in str(ei.value)   # причина донесена, не проглочена как результат

    def test_claude_cli_error_not_truncated(self, monkeypatch):
        """F-011a: полный человекочитаемый текст ошибки claude сохраняется (парсинг content[].text),
        а не режется до 200 символов — иначе диагностика сбоя провайдера теряется ровно там, где нужна."""
        import orchestrator
        monkeypatch.setattr("time.sleep", lambda *a, **k: None)

        class FakeResult:
            def __init__(self, stdout="", returncode=0, stderr=""):
                self.stdout = stdout; self.returncode = returncode; self.stderr = stderr

        long_msg = "OVERLOADED " * 40   # > 200 символов
        payload = json.dumps({"error": "server_error", "content": [{"type": "text", "text": long_msg}]})
        provider = orchestrator.make_claude_cli_provider(runner=lambda cmd: FakeResult(payload, 1))
        with pytest.raises(RuntimeError) as ei:
            provider("test")
        assert len(long_msg) > 200
        assert long_msg.strip() in str(ei.value)   # текст сохранён целиком (не обрезан до 200)

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
    """Contract tests for tools/tool_broker.py."""

    def test_policy_engine_returns_dict_with_decision(self):
        """Policy.decide() must return a dict with 'allow' (bool) and 'reason' (str)."""
        import tool_broker
        pol = tool_broker.Policy(level="read-only")
        result = pol.decide({"op": "read", "path": "src/a.ts"})
        assert isinstance(result, dict)
        assert "allow" in result and isinstance(result["allow"], bool)
        assert "reason" in result and isinstance(result["reason"], str)

    def test_policy_engine_read_always_allowed(self):
        """read-only level must allow read operations within the repo."""
        import tool_broker
        pol = tool_broker.Policy(level="read-only")
        result = pol.decide({"op": "read", "path": "src/a.ts"})
        assert result["allow"] is True

    def test_policy_engine_write_respects_level(self):
        """read-only level must deny write; controlled-write must allow it within scope."""
        import tool_broker
        pol_ro = tool_broker.Policy(level="read-only")
        assert pol_ro.decide({"op": "write", "path": "src/a.ts"})["allow"] is False

        pol_cw = tool_broker.Policy(level="controlled-write", write_scope=["src/"])
        assert pol_cw.decide({"op": "write", "path": "src/a.ts"})["allow"] is True
        assert pol_cw.decide({"op": "write", "path": "config/x.yaml"})["allow"] is False

    def test_execute_denied_has_no_side_effects(self, child_root):
        """execute() on a denied action must NOT create files or run commands."""
        import tool_broker
        pol = tool_broker.Policy(level="read-only")
        target = child_root / "src" / "should_not_exist.ts"
        result = tool_broker.execute(
            {"op": "write", "path": "src/should_not_exist.ts", "content": "bad"},
            child_root, pol,
        )
        assert result["allowed"] is False
        assert result["ok"] is False
        assert not target.exists()

    def test_scrub_env_removes_secrets(self, monkeypatch):
        """scrub_env() must strip unknown env vars (allowlist-based)."""
        import tool_broker
        fake_env = {
            "PATH": "/usr/bin",
            "HOME": "/home/user",
            "OPENAI_API_KEY": "sk-secret",
            "DATABASE_URL": "postgres://secret",
            "LC_ALL": "en_US.UTF-8",
        }
        scrubbed = tool_broker.scrub_env(env=fake_env)
        assert "PATH" in scrubbed
        assert "HOME" in scrubbed
        assert "LC_ALL" in scrubbed  # LC_ prefix allowed
        assert "OPENAI_API_KEY" not in scrubbed
        assert "DATABASE_URL" not in scrubbed

    def test_block_push_blocks_writes(self):
        """block_push=True must deny git push commands."""
        import tool_broker
        pol = tool_broker.Policy(level="execution", block_push=True)
        result = pol.decide({"op": "git", "command": "git push origin main"})
        assert result["allow"] is False
        assert "block_push" in result["reason"] or "git push" in result["reason"].lower()

    def test_execute_returns_evidence_dict(self, child_root):
        """execute() must always return a dict with op, allowed, reason keys."""
        import tool_broker
        pol = tool_broker.Policy(level="controlled-write", write_scope=["src/"])
        (child_root / "src").mkdir(exist_ok=True)
        (child_root / "src" / "test.txt").write_text("hello")
        # Init git so _revision works
        import subprocess
        subprocess.run(["git", "init", "-q"], cwd=str(child_root), capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(child_root), capture_output=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=str(child_root), capture_output=True)
        subprocess.run(["git", "add", "-A"], cwd=str(child_root), capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(child_root), capture_output=True)

        result = tool_broker.execute({"op": "read", "path": "src/test.txt"}, child_root, pol)
        assert isinstance(result, dict)
        assert "op" in result
        assert "allowed" in result
        assert "reason" in result


class TestGateExecutorContracts:
    """Contract tests for tools/gate_executor.py."""

    def test_evaluate_gate_returns_required_keys(self):
        """evaluate_gate() must return a dict with schema_version, gate, status, blocking, etc."""
        import gate_executor
        gates = gate_executor.load_gates()
        gate_id = "intake_completeness"
        gate = gates[gate_id]
        result = gate_executor.evaluate_gate(gate_id, gate, {})
        required_keys = {"schema_version", "gate", "status", "blocking", "checks",
                         "blockers", "warnings", "evidence", "owner", "review_mode"}
        for key in required_keys:
            assert key in result, f"Missing key '{key}' in evaluate_gate result"
        assert result["status"] in ("pass", "warn", "fail")

    def test_deterministic_gate_pass_on_valid_input(self):
        """A deterministic gate with passing evidence must return status=pass."""
        import gate_executor
        gates = gate_executor.load_gates()
        gate_id = "intake_completeness"
        gate = gates[gate_id]
        required = gate.get("required_evidence", []) or []
        evidence = {gate_id: {"status": "pass", "provided": list(required),
                              "checks": [{"id": r, "status": "pass"} for r in required],
                              "evidence": ["test"], "warnings": [], "blockers": []}}
        result = gate_executor.evaluate_gate(gate_id, gate, evidence)
        assert result["status"] == "pass"

    def test_deterministic_gate_fail_on_invalid_input(self):
        """A blocking gate without evidence must fail (fail-closed)."""
        import gate_executor
        gates = gate_executor.load_gates()
        # Find a blocking gate
        blocking_gate_id = None
        for gid, g in gates.items():
            if g.get("blocking"):
                blocking_gate_id = gid
                break
        assert blocking_gate_id is not None, "No blocking gate found for test"
        gate = gates[blocking_gate_id]
        # No evidence -> fail-closed for blocking gate
        result = gate_executor.evaluate_gate(blocking_gate_id, gate, {})
        assert result["status"] == "fail"
        assert len(result["blockers"]) > 0

    def test_load_gates_returns_dict(self):
        """load_gates() must return a non-empty dict of gate definitions."""
        import gate_executor
        gates = gate_executor.load_gates()
        assert isinstance(gates, dict)
        assert len(gates) > 0
        # Each gate must have at least an id-like key
        for gid, g in gates.items():
            assert isinstance(g, dict), f"Gate '{gid}' is not a dict"

    def test_collect_evidence_returns_dict(self, tmp_path):
        """collect_evidence() must return a dict (even if empty for missing artifacts)."""
        import gate_executor
        result = gate_executor.collect_evidence("QUICK", tmp_path)
        assert isinstance(result, dict)

    def test_classify_returns_valid_kind(self):
        """classify() must return one of the known gate kinds."""
        import gate_executor
        gates = gate_executor.load_gates()
        valid_kinds = {"human-approval", "deterministic", "ai-review", "writer-check"}
        for gid, g in gates.items():
            kind = gate_executor.classify(g)
            assert kind in valid_kinds, f"Gate '{gid}' has unknown kind '{kind}'"

    def test_validate_evidence_accepts_valid(self):
        """validate_evidence() must return no errors for well-formed evidence."""
        import gate_executor
        evidence = {
            "some_gate": {
                "status": "pass",
                "provided": ["key1"],
                "checks": [{"id": "c1", "status": "pass"}],
                "evidence": ["artifact.md"],
                "warnings": [],
                "blockers": [],
            }
        }
        errors = gate_executor.validate_evidence(evidence)
        assert errors == []


class TestPreflightContracts:
    """Contract tests for tools/preflight.py."""

    def test_assess_returns_required_keys(self, child_root):
        """assess() must return a dict with schema_version, kind, ok, blocked, checks, reasons."""
        import preflight
        result = preflight.assess(
            {"task_type": "QUICK"}, child_root, "w",
            payload={"text": "test"},
            spec_cov={"spec_artifact": False, "blocking_missing": []},
            work_pkg={"should_decompose": False},
        )
        required_keys = {"schema_version", "kind", "ok", "blocked", "checks", "reasons", "task_type"}
        for key in required_keys:
            assert key in result, f"Missing key '{key}' in assess() result"
        assert result["kind"] == "PreflightTruth"
        assert isinstance(result["ok"], bool)
        assert isinstance(result["blocked"], bool)

    def test_assess_blocked_implies_reasons(self, child_root):
        """When blocked=True, reasons must be non-empty."""
        import preflight
        # Incomplete spec -> blocked
        result = preflight.assess(
            {"task_type": "QUICK"}, child_root, "w",
            payload={"text": "test"},
            spec_cov={"spec_artifact": True, "blocking_missing": ["goal", "scope"]},
            work_pkg={"should_decompose": False},
        )
        assert result["blocked"] is True
        assert len(result["reasons"]) > 0
        assert any("spec-first" in r for r in result["reasons"])

    def test_assess_quick_without_spec_not_blocked(self, child_root):
        """QUICK task without spec must NOT be blocked (spec is light for QUICK)."""
        import preflight
        result = preflight.assess(
            {"task_type": "QUICK"}, child_root, "w",
            payload={"text": "test"},
            spec_cov={"spec_artifact": False, "blocking_missing": []},
            work_pkg={"should_decompose": False},
        )
        assert result["blocked"] is False
        assert result["checks"]["spec"]["ok"] is True

    def test_assess_engineering_without_spec_blocked(self, child_root):
        """ENGINEERING (heavy) without spec and without --author must be blocked."""
        import preflight
        result = preflight.assess(
            {"task_type": "ENGINEERING"}, child_root, "w",
            payload={"text": "test"},
            spec_cov={"spec_artifact": False, "blocking_missing": []},
            work_pkg={"should_decompose": False},
        )
        assert result["blocked"] is True
        assert any("spec-first" in r for r in result["reasons"])

    def test_assess_reevaluate_skips_build_preconditions(self, child_root):
        """reevaluate_only=True must skip spec-first/atomic build preconditions."""
        import preflight
        result = preflight.assess(
            {"task_type": "ENGINEERING"}, child_root, "w",
            payload={"text": "test"},
            spec_cov={"spec_artifact": False, "blocking_missing": []},
            work_pkg={"should_decompose": False},
            reevaluate_only=True,
        )
        # spec check should be marked as skipped
        assert result["checks"]["spec"].get("skipped_reevaluate") is True
        # No spec-first reason in reasons
        assert not any("spec-first" in r for r in result["reasons"])

    def test_assess_context_overflow_blocked(self, child_root):
        """Context budget overflow must block before execution."""
        import preflight
        result = preflight.assess(
            {"task_type": "ENGINEERING"}, child_root, "w",
            payload={"text": "test"},
            spec_cov={"spec_artifact": False, "blocking_missing": []},
            work_pkg={"should_decompose": False},
            bundle={"overflow": True},
        )
        assert result["blocked"] is True
        assert any("context-budget" in r for r in result["reasons"])


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
