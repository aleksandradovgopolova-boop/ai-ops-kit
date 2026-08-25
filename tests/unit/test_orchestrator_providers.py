"""Гранулярные тесты orchestrator_providers (мигрировано из test_orchestrator_providers_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import json as _test_json
import os as _os

import pytest

from orchestrator_providers import (
    PROVIDER_AUTORESOLVE_ENV,
    autoresolve_enabled,
    make_claude_cli_provider,
    make_provider,
    mock_provider,
    orchestrator_usage,
    resolve_provider,
)


class _FakeResult:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


@pytest.mark.unit
class TestMockProvider:
    def test_mock_is_default_offline_provider(self):
        assert make_provider("mock") is mock_provider


@pytest.mark.unit
class TestProviderErrors:
    def test_anthropic_without_key_exits(self):
        saved = _os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            with pytest.raises(SystemExit):
                make_provider("anthropic")("тест")
        finally:
            if saved is not None:
                _os.environ["ANTHROPIC_API_KEY"] = saved

    def test_unknown_provider_exits(self):
        with pytest.raises(SystemExit):
            make_provider("bogus")


@pytest.mark.unit
class TestOpenAICompatible:
    def test_without_base_url_exits(self):
        saved = _os.environ.pop("OPENAI_COMPATIBLE_BASE_URL", None)
        try:
            with pytest.raises(SystemExit):
                make_provider("openai-compatible", "deepseek-chat")
        finally:
            if saved is not None:
                _os.environ["OPENAI_COMPATIBLE_BASE_URL"] = saved

    def test_without_model_exits(self):
        saved_b = _os.environ.pop("OPENAI_COMPATIBLE_BASE_URL", None)
        _os.environ["OPENAI_COMPATIBLE_BASE_URL"] = "https://api.deepseek.com/chat/completions"
        try:
            with pytest.raises(SystemExit):
                make_provider("openai-compatible")
        finally:
            if saved_b is None:
                _os.environ.pop("OPENAI_COMPATIBLE_BASE_URL", None)
            else:
                _os.environ["OPENAI_COMPATIBLE_BASE_URL"] = saved_b

    def test_with_base_url_but_no_key_exits(self):
        saved_b = _os.environ.pop("OPENAI_COMPATIBLE_BASE_URL", None)
        saved_k = _os.environ.pop("OPENAI_COMPATIBLE_API_KEY", None)
        _os.environ["OPENAI_COMPATIBLE_BASE_URL"] = "https://api.deepseek.com/chat/completions"
        try:
            with pytest.raises(SystemExit):
                make_provider("openai-compatible", "deepseek-chat")("тест")
        finally:
            if saved_b is None:
                _os.environ.pop("OPENAI_COMPATIBLE_BASE_URL", None)
            else:
                _os.environ["OPENAI_COMPATIBLE_BASE_URL"] = saved_b
            if saved_k is not None:
                _os.environ["OPENAI_COMPATIBLE_API_KEY"] = saved_k


@pytest.mark.unit
class TestClaudeCliProvider:
    @pytest.fixture(autouse=True)
    def setup_claude_cli(self):
        self.seen = {}
        self.call_stats_before = len(orchestrator_usage._CALL_STATS)

        def fake_runner(cmd):
            self.seen["cmd"] = cmd
            return _FakeResult(stdout=_test_json.dumps({
                "result": "PROPOSED-ACTIONS-JSON",
                "usage": {"input_tokens": 100, "output_tokens": 50},
                "model": "claude-opus",
                "total_cost_usd": 0.01,
            }))

        self.prov = make_claude_cli_provider(model="claude-opus", runner=fake_runner)
        self.out = self.prov("сгенерируй tool-loop действия")

    def test_returns_model_proposal_text(self):
        assert self.out == "PROPOSED-ACTIONS-JSON"

    def test_production_path_records_usage(self):
        call_stats_after = len(orchestrator_usage._CALL_STATS)
        assert call_stats_after > self.call_stats_before
        last = orchestrator_usage._CALL_STATS[-1]
        assert last.get("input_tokens") == 100
        assert last.get("output_tokens") == 50
        assert last.get("cost_usd_est") is not None
        assert last.get("latency") is not None
        assert last["latency"] >= 0

    def test_read_only_tools(self):
        cmd = self.seen.get("cmd") or []
        allowed = []
        if "--allowedTools" in cmd:
            i = cmd.index("--allowedTools") + 1
            while i < len(cmd) and not cmd[i].startswith("--"):
                allowed.append(cmd[i])
                i += 1
        assert bool(allowed)
        assert set(allowed) <= {"Read", "Grep", "Glob"}
        assert "Read" in allowed
        assert not any(t in cmd for t in ("Write", "Edit", "Bash"))
        assert "-p" in cmd


@pytest.mark.unit
class TestClaudeCliYamlFrontmatter:
    def test_prompt_with_frontmatter_goes_after_separator(self):
        """Промпт с YAML-фронтматтером уходит после `--` (не разбирается как опция)."""
        prompt = "---\nid: intake-classifier\ntype: agent\n---\n\n## Задача\nОписать контур"
        seen = {}

        def runner(cmd):
            seen["cmd"] = cmd
            return _FakeResult(stdout=_test_json.dumps({"result": "VERDICT", "usage": {}}))

        out = make_claude_cli_provider(runner=runner)(prompt)
        cmd = seen.get("cmd") or []
        sep = cmd.index("--") if "--" in cmd else -1
        assert sep >= 0
        assert prompt in cmd[sep + 1:]
        assert prompt not in cmd[:sep]
        assert out == "VERDICT"

    def test_flags_before_separator(self):
        """Ключи стоят до разделителя (read-only политика применяется)."""
        prompt = "---\nid: intake-classifier\ntype: agent\n---\n\n## Задача\nОписать контур"
        seen = {}

        def runner(cmd):
            seen["cmd"] = cmd
            return _FakeResult(stdout=_test_json.dumps({"result": "VERDICT", "usage": {}}))

        make_claude_cli_provider(runner=runner)(prompt)
        cmd = seen.get("cmd") or []
        sep = cmd.index("--") if "--" in cmd else -1
        assert sep >= 0
        assert all(f in cmd[:sep] for f in ("--output-format", "--allowedTools"))


@pytest.mark.unit
class TestClaudeCliRegistration:
    def test_registered_as_first_class_provider(self):
        assert callable(make_provider("claude-cli"))


@pytest.mark.unit
class TestClaudeCliRetry:
    def test_retry_loop_succeeds_after_transient_failures(self):
        """retry-loop + sleep работают (3 попытки)."""
        calls = []

        def flaky_runner(cmd):
            calls.append(1)
            if len(calls) < 3:
                return _FakeResult(returncode=1, stderr="transient error")
            return _FakeResult(stdout=_test_json.dumps({"result": "ok", "usage": {}}))

        prov = make_claude_cli_provider(runner=flaky_runner)
        out = prov("тест retry")
        assert out == "ok"
        assert len(calls) == 3


@pytest.mark.unit
class TestVendorProviders:
    def test_qwen_without_key_exits_with_key_message(self):
        saved = _os.environ.pop("QWEN_API_KEY", None)
        try:
            with pytest.raises(SystemExit) as exc_info:
                make_provider("qwen")("тест")
            assert "QWEN_API_KEY" in str(exc_info.value)
        finally:
            if saved is not None:
                _os.environ["QWEN_API_KEY"] = saved

    def test_unimplemented_registry_provider_exits(self):
        with pytest.raises(SystemExit) as exc_info:
            make_provider("gigachat")
        assert "registry" in str(exc_info.value)


@pytest.mark.unit
class TestResolveProvider:
    def test_explicit_wins(self):
        r = resolve_provider(explicit="mock", root=None, env={}, which=lambda n: "/usr/bin/claude")
        assert r["provider"] == "mock"
        assert r["source"] == "explicit"

    def test_claude_in_path_gives_claude_cli(self):
        env = {PROVIDER_AUTORESOLVE_ENV: "1"}
        r = resolve_provider(env=env, which=lambda n: "/usr/bin/claude" if n == "claude" else None)
        assert r["provider"] == "claude-cli"

    def test_no_keys_no_cli_gives_mock_with_warning(self):
        env = {PROVIDER_AUTORESOLVE_ENV: "1"}
        r = resolve_provider(env=env, which=lambda n: None)
        assert r["provider"] == "mock"
        assert r.get("warning")

    def test_autoresolve_disabled_gives_mock(self):
        env = {PROVIDER_AUTORESOLVE_ENV: "0"}
        r = resolve_provider(env=env, which=lambda n: "/usr/bin/claude")
        assert r["provider"] == "mock"
        assert r["source"] == "autoresolve-disabled"


@pytest.mark.unit
class TestAutoresolveEnabled:
    def test_disabled_under_pytest_and_ci(self):
        assert autoresolve_enabled({"PYTEST_CURRENT_TEST": "x"}) is False
        assert autoresolve_enabled({"CI": "true"}) is False
