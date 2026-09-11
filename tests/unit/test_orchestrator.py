"""Unit tests for tools/orchestrator.py — workflow orchestration.

Tests the core orchestration logic: state persistence, role-prompt isolation,
workflow execution with mock provider, gate evaluation, budget enforcement,
and audit logging. Complements the selftest wrapper with granular assertions.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

PKG_ROOT = Path(__file__).resolve().parents[2]

from ai_ops_kit.providers import orchestrator
from ai_ops_kit.providers import orchestrator_usage

# Полное evidence блокирующих гейтов QUICK — доводит workflow до done. В реальном прогоне его
# дают reviewer-стадии/валидаторы; здесь подаём явно, как в исходном селфтесте, чтобы дойти до done.
QUICK_EVIDENCE = {
    "intake_completeness": {"status": "pass", "provided": ["classified_type", "size", "risk"]},
    "implementation_verification": {"status": "pass", "provided": [
        "build_passed", "lint_passed", "typecheck_passed", "tests_passed", "tested_revision"
    ]},
}


@pytest.mark.critical_path
@pytest.mark.unit
class TestStatePersistence:
    """Tests for load_state / save_state round-trip."""

    def test_save_and_load_state(self, child_root):
        """save_state writes valid YAML that load_state can read back."""
        run_dir = child_root / ".ai" / "runtime" / "test-run"
        run_dir.mkdir(parents=True)
        state = {
            "schema_version": 1,
            "status": "in-progress",
            "workflow": "QUICK",
            "goal": "fix a typo",
            "completed_checks": ["stage-1"],
            "artifacts": [],
        }
        orchestrator.save_state(run_dir, state)
        loaded = orchestrator.load_state(run_dir)
        assert loaded is not None
        assert loaded["status"] == "in-progress"
        assert loaded["workflow"] == "QUICK"
        assert loaded["completed_checks"] == ["stage-1"]

    def test_load_state_returns_none_when_missing(self, tmp_path):
        """load_state returns None if TaskState.yaml doesn't exist."""
        result = orchestrator.load_state(tmp_path / "nonexistent")
        assert result is None

    def test_save_state_creates_file(self, child_root):
        """save_state creates TaskState.yaml in the run directory."""
        run_dir = child_root / ".ai" / "runtime" / "run-x"
        run_dir.mkdir(parents=True)
        orchestrator.save_state(run_dir, {"status": "done"})
        assert (run_dir / "TaskState.yaml").is_file()


@pytest.mark.critical_path
@pytest.mark.unit
class TestBuildRolePrompt:
    """Tests for prompt isolation — judge stages must be read-only."""

    def test_judge_prompt_contains_read_only_guard(self, child_root):
        """Judge stage prompts must carry the read-only isolation guard verbatim.

        Не просто «есть слово read-only», а точная фраза изоляции judge: предыдущие рассуждения
        ему не передаются (иначе writer≠judge протекает — судья видел бы reasoning автора)."""
        prompt = orchestrator.build_role_prompt(
            stage={"id": "review", "review_mode": "read-only"},
            agent_id="judge",
            agents_index={},
            task_text="fix the bug",
            published={},
        )
        assert "read-only" in prompt
        assert "рассуждения предыдущих ролей тебе не передаются" in prompt

    def test_prompt_includes_task_text(self, child_root):
        """The task text must appear in the generated prompt."""
        prompt = orchestrator.build_role_prompt(
            stage={"id": "implement"},
            agent_id="worker",
            agents_index={},
            task_text="implement feature X",
            published={},
        )
        assert "implement feature X" in prompt

    def test_prompt_includes_published_artifacts_only(self, child_root):
        """Only published artifact paths should appear, not internal reasoning."""
        prompt = orchestrator.build_role_prompt(
            stage={"id": "review"},
            agent_id="reviewer",
            agents_index={},
            task_text="task",
            published={"stage-1.md": "content1", "stage-2.md": "content2"},
        )
        assert "stage-1.md" in prompt
        assert "stage-2.md" in prompt


@pytest.mark.critical_path
@pytest.mark.unit
class TestRunWorkflowQuick:
    """Tests for run_workflow with the QUICK workflow."""

    def test_quick_without_evidence_is_blocked(self, child_root):
        """QUICK без evidence: все 4 стадии проходят, но статус blocked с ИМЕННО этими гейтами.

        Точные значения (не просто «есть unmet_gates»): стадии выполняются полностью
        (completed_checks==4), а нечем закрыть ровно два блокирующих гейта."""
        state, run_dir = orchestrator.run_workflow(
            workflow_id="QUICK",
            task_text="fix a typo in README",
            child_root=child_root,
            provider=orchestrator.mock_provider,
            verbose=False,
            fresh=True,
        )
        assert state["status"] == "blocked"
        assert set(state.get("unmet_gates", [])) == {
            "intake_completeness", "implementation_verification"}
        assert len(state["completed_checks"]) == 4

    def test_quick_with_evidence_is_done(self, child_root):
        """QUICK с полным evidence доходит до done ровно за 4 стадии."""
        state, run_dir = orchestrator.run_workflow(
            workflow_id="QUICK",
            task_text="fix a typo in README",
            child_root=child_root,
            provider=orchestrator.mock_provider,
            verbose=False,
            gate_evidence=QUICK_EVIDENCE,
            fresh=True,
        )
        assert state["status"] == "done"
        assert len(state["completed_checks"]) == 4

    def test_quick_produces_gate_report(self, child_root):
        """run_workflow must write GateReport.json to the run directory."""
        state, run_dir = orchestrator.run_workflow(
            workflow_id="QUICK",
            task_text="fix typo",
            child_root=child_root,
            provider=orchestrator.mock_provider,
            verbose=False,
            fresh=True,
        )
        gate_report = Path(run_dir) / "GateReport.json"
        assert gate_report.is_file()
        report = json.loads(gate_report.read_text())
        assert "blocked" in report


@pytest.mark.critical_path
@pytest.mark.unit
class TestBudgetEnforcement:
    """Tests for execution budget limiting workflow stages."""

    def test_budget_limits_stages(self, child_root):
        """max_model_calls=1 останавливает ровно после одной стадии/вызова модели."""
        state, run_dir = orchestrator.run_workflow(
            workflow_id="QUICK",
            task_text="fix a typo",
            child_root=child_root,
            provider=orchestrator.mock_provider,
            verbose=False,
            budget={"max_model_calls": 1},
            fresh=True,
        )
        assert state["status"] == "blocked"
        assert state.get("budget_exceeded")
        assert state["budget"]["model_calls"] == 1
        assert len(state["completed_checks"]) == 1


@pytest.mark.critical_path
@pytest.mark.unit
class TestAuditLog:
    """Tests for the append-only interaction log."""

    def test_audit_log_appends_per_workflow(self, child_root):
        """Each workflow run appends exactly one JSONL record."""
        orchestrator.run_workflow(
            workflow_id="QUICK",
            task_text="task one",
            child_root=child_root,
            provider=orchestrator.mock_provider,
            verbose=False,
            fresh=True,
        )
        orchestrator.run_workflow(
            workflow_id="QUICK",
            task_text="task two",
            child_root=child_root,
            provider=orchestrator.mock_provider,
            verbose=False,
            fresh=True,
        )
        log_path = child_root / ".ai" / "runtime" / "interaction-log.jsonl"
        assert log_path.is_file()
        lines = [l for l in log_path.read_text().strip().split("\n") if l.strip()]
        assert len(lines) == 2
        record = json.loads(lines[0])
        assert "ts" in record
        assert "workflow" in record
        assert "status" in record
        assert "provider" in record


@pytest.mark.critical_path
@pytest.mark.unit
class TestHandoffIsolation:
    """Tests for TaskHandoff.json — only published artifacts, no leakage."""

    def test_handoff_contains_only_artifact_paths(self, child_root):
        """TaskHandoff.json ссылается ТОЛЬКО на опубликованные stage-артефакты, и список непуст.

        Каждый путь под .ai/runtime/ и содержит stage- (никакого протекания reasoning ролей)."""
        state, run_dir = orchestrator.run_workflow(
            workflow_id="QUICK",
            task_text="fix typo",
            child_root=child_root,
            provider=orchestrator.mock_provider,
            verbose=False,
            fresh=True,
        )
        handoff = json.loads((Path(run_dir) / "TaskHandoff.json").read_text())
        published = handoff["published_artifacts"]
        assert published
        assert all(a.startswith(".ai/runtime/") and "stage-" in a for a in published)


@pytest.mark.critical_path
@pytest.mark.unit
class TestProviderAdapter:
    """Tests for make_provider() — honest errors for missing credentials."""

    def test_mock_provider_resolves(self):
        """make_provider('mock') резолвится РОВНО в mock_provider (офлайн-провайдер по умолчанию)."""
        assert orchestrator.make_provider("mock") is orchestrator.mock_provider

    def test_unknown_provider_exits(self):
        """make_provider('bogus') should raise SystemExit."""
        with pytest.raises(SystemExit):
            orchestrator.make_provider("bogus")


@pytest.mark.critical_path
@pytest.mark.unit
class TestResume:
    """Перезапуск workflow с прерванной стадии продолжает, а не начинает заново."""

    def test_resume_continues_from_interrupted_stage(self, child_root):
        """Обрубленное состояние (2 из 4 стадий, in-progress) при повторном прогоне доходит до done."""
        # 1) довести до done, чтобы получить run_dir и полное состояние
        _, run_dir = orchestrator.run_workflow(
            "QUICK", "fix a typo in README", child_root,
            provider=orchestrator.mock_provider, verbose=False, gate_evidence=QUICK_EVIDENCE)
        # 2) сымитировать прерывание: оставить 2 стадии, статус in-progress
        st = orchestrator.load_state(run_dir)
        st["completed_checks"] = st["completed_checks"][:2]
        st["status"] = "in-progress"
        st["next_action"] = "local-verify"
        orchestrator.save_state(run_dir, st)
        # 3) повторный прогон БЕЗ fresh -> resume того же run_dir (id из хэша задачи)
        state2, _ = orchestrator.run_workflow(
            "QUICK", "fix a typo in README", child_root,
            provider=orchestrator.mock_provider, verbose=False, gate_evidence=QUICK_EVIDENCE)
        assert state2["status"] == "done"
        assert len(state2["completed_checks"]) == 4


@pytest.mark.critical_path
@pytest.mark.unit
class TestJudgeStructuredResult:
    """Judge, вернувший JSON reviewer-result, пишет структурный stage-*.reviewer.json (не regex-проза)."""

    def test_json_verdict_writes_reviewer_json(self, child_root):
        def json_judge(prompt):
            if "read-only" in prompt:   # judge-стадия
                return ('Заключение.\n{"schema_version":1,"kind":"reviewer-result",'
                        '"gate":"code_review","status":"pass",'
                        '"checks":[{"id":"style","status":"pass"}]}')
            return "готово"
        _, run_dir = orchestrator.run_workflow(
            "QUICK", "структурный вердикт judge", child_root,
            provider=json_judge, verbose=False, fresh=True)
        assert list(Path(run_dir).glob("stage-*.reviewer.json"))


@pytest.mark.critical_path
@pytest.mark.unit
class TestCollectEvidence:
    """collect-evidence НЕ закрывает детерминированные гейты словом ревьюера (дисциплина evidence)."""

    def test_reviewer_word_does_not_close_deterministic_gates(self, child_root):
        """Ревьюер говорит «passed», но build/lint/typecheck/tests так не закрываются -> blocked."""
        def verdict_provider(role_prompt):
            return "status: passed\nРезультат стадии готов согласно контракту роли."
        state, _ = orchestrator.run_workflow(
            "QUICK", "fix a typo", child_root,
            provider=verdict_provider, verbose=False, collect=True, fresh=True)
        assert state["status"] == "blocked"
        assert "implementation_verification" in state.get("unmet_gates", [])


@pytest.mark.critical_path
@pytest.mark.unit
class TestProviderFactoryFailClosed:
    """Провайдер-фабрика fail-closed: без ключей/BASE_URL/model — честная ошибка, не тихий mock."""

    def test_anthropic_without_key_exits(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(SystemExit):
            orchestrator.make_provider("anthropic")("тест")

    def test_openai_compatible_without_base_url_exits(self, monkeypatch):
        monkeypatch.delenv("OPENAI_COMPATIBLE_BASE_URL", raising=False)
        with pytest.raises(SystemExit):
            orchestrator.make_provider("openai-compatible", "deepseek-chat")

    def test_openai_compatible_without_model_exits(self, monkeypatch):
        monkeypatch.setenv("OPENAI_COMPATIBLE_BASE_URL", "https://api.deepseek.com/chat/completions")
        with pytest.raises(SystemExit):
            orchestrator.make_provider("openai-compatible")   # без model

    def test_openai_compatible_with_base_url_but_no_key_exits(self, monkeypatch):
        monkeypatch.setenv("OPENAI_COMPATIBLE_BASE_URL", "https://api.deepseek.com/chat/completions")
        monkeypatch.delenv("OPENAI_COMPATIBLE_API_KEY", raising=False)
        with pytest.raises(SystemExit):
            orchestrator.make_provider("openai-compatible", "deepseek-chat")("тест")


class _FakeResult:
    """Замена subprocess.CompletedProcess для runner-инъекции claude-cli (офлайн, без CLI)."""

    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


@pytest.mark.critical_path
@pytest.mark.unit
class TestClaudeCliProvider:
    """claude-cli как first-class provider: текст-предложение, usage, read-only tools, retry."""

    def test_returns_provider_text(self):
        """Runner отдаёт JSON-конверт claude -> провайдер возвращает РОВНО строку предложения."""
        def runner(cmd):
            return _FakeResult(stdout=json.dumps({
                "result": "PROPOSED-ACTIONS-JSON",
                "usage": {"input_tokens": 100, "output_tokens": 50},
                "model": "claude-opus", "total_cost_usd": 0.01}))
        provider = orchestrator.make_claude_cli_provider(model="claude-opus", runner=runner)
        assert provider("сгенерируй tool-loop действия") == "PROPOSED-ACTIONS-JSON"

    def test_production_path_records_usage(self):
        """production-path пройден: _record_call измерил tokens/latency/cost (регрессия NameError('time'))."""
        before = len(orchestrator_usage._CALL_STATS)
        def runner(cmd):
            return _FakeResult(stdout=json.dumps({
                "result": "ok",
                "usage": {"input_tokens": 100, "output_tokens": 50},
                "model": "claude-opus", "total_cost_usd": 0.01}))
        orchestrator.make_claude_cli_provider(model="claude-opus", runner=runner)("тест")
        assert len(orchestrator_usage._CALL_STATS) == before + 1
        last = orchestrator_usage._CALL_STATS[-1]
        assert last["input_tokens"] == 100
        assert last["output_tokens"] == 50
        assert last["cost_usd_est"] is not None
        assert last["latency"] is not None and last["latency"] >= 0

    def test_read_only_allowed_tools(self):
        """cmd содержит -p и ограничивает инструменты Read/Grep/Glob (нет Write/Edit/Bash)."""
        seen = {}
        def runner(cmd):
            seen["cmd"] = cmd
            return _FakeResult(stdout=json.dumps({"result": "ok", "usage": {}}))
        orchestrator.make_claude_cli_provider(runner=runner)("тест")
        cmd = seen["cmd"]
        allowed = []
        if "--allowedTools" in cmd:
            i = cmd.index("--allowedTools") + 1
            while i < len(cmd) and not cmd[i].startswith("--"):
                allowed.append(cmd[i]); i += 1
        assert "-p" in cmd
        assert allowed and set(allowed) <= {"Read", "Grep", "Glob"} and "Read" in allowed
        assert not any(t in cmd for t in ("Write", "Edit", "Bash"))

    def test_registered_first_class(self):
        """claude-cli резолвится через make_provider как callable."""
        assert callable(orchestrator.make_provider("claude-cli"))

    def test_retry_loop_recovers(self):
        """Runner падает дважды (rc=1), успех на 3-й -> 'ok' ровно за 3 вызова (backoff не роняет)."""
        calls = []
        def flaky_runner(cmd):
            calls.append(1)
            if len(calls) < 3:
                return _FakeResult(returncode=1, stderr="transient error")
            return _FakeResult(stdout=json.dumps({"result": "ok", "usage": {}}))
        # sleep замокан, чтобы backoff не тормозил тест
        import time as _t
        orig = _t.sleep
        _t.sleep = lambda *a, **k: None
        try:
            out = orchestrator.make_claude_cli_provider(runner=flaky_runner)("тест retry")
        finally:
            _t.sleep = orig
        assert out == "ok"
        assert len(calls) == 3


@pytest.mark.critical_path
@pytest.mark.unit
class TestHttpRetry:
    """_http_post_json ретраит транзиентные сбои, но НЕ ретраит 4xx."""

    def test_transient_failures_retried(self, monkeypatch):
        """2 сетевых сбоя (URLError) -> успех на 3-й попытке; sleep замокан."""
        import urllib.request as ur
        import urllib.error as ue
        import time as _t

        class _Resp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b'{"ok": true}'

        calls = {"n": 0}
        def flaky(req, timeout=0):
            calls["n"] += 1
            if calls["n"] < 3:
                raise ue.URLError("ssl handshake timed out")
            return _Resp()
        monkeypatch.setattr(_t, "sleep", lambda *a, **k: None)
        monkeypatch.setattr(ur, "urlopen", flaky)
        result = orchestrator._http_post_json("http://x", {}, {}, retries=3)
        assert result == {"ok": True}
        assert calls["n"] == 3

    def test_http_4xx_not_retried(self, monkeypatch):
        """404 пробрасывается сразу, ровно за 1 вызов (4xx — не транзиент)."""
        import urllib.request as ur
        import urllib.error as ue
        import time as _t

        calls = {"n": 0}
        def not_found(req, timeout=0):
            calls["n"] += 1
            raise ue.HTTPError("http://x", 404, "not found", {}, None)
        monkeypatch.setattr(_t, "sleep", lambda *a, **k: None)
        monkeypatch.setattr(ur, "urlopen", not_found)
        with pytest.raises(ue.HTTPError):
            orchestrator._http_post_json("http://x", {}, {}, retries=3)
        assert calls["n"] == 1
