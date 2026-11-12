"""Гранулярные тесты orchestrator_providers (мигрировано из test_orchestrator_providers_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import json as _test_json
import os as _os

import pytest

from ai_ops_kit.providers.orchestrator_providers import (
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

    def test_offline_command_requests_explicit_builtin_set(self):
        # Проверка сборки argv, НЕ proof эффективных permissions реального runtime.
        cmd = self.seen.get("cmd") or []
        assert cmd[cmd.index("--tools") + 1] == "Read,Grep,Glob"
        assert "-p" in cmd
        # #1476: весь профиль стоит подряд и до разделителя промпта, ни один флаг не потерян.
        from ai_ops_kit.providers.provider_calls import CLAUDE_READONLY_PROFILE
        start = cmd.index(CLAUDE_READONLY_PROFILE[0])
        assert cmd[start:start + len(CLAUDE_READONLY_PROFILE)] == list(CLAUDE_READONLY_PROFILE)
        assert start + len(CLAUDE_READONLY_PROFILE) <= cmd.index("--")


@pytest.mark.unit
class TestClaudeReadonlyUnqualified:
    """Пока effective runtime не квалифицирован, доказуемая граница — отсутствие запуска."""

    @pytest.mark.parametrize("provider", ["claude-cli", "claude-code-local"])
    def test_unqualified_runtime_refuses_before_launch_retry_or_usage(self, monkeypatch, provider):
        import subprocess
        from ai_ops_kit.providers import orchestrator_providers as op
        from ai_ops_kit.providers import provider_calls as pc
        from ai_ops_kit.providers.response_contract import ProviderRefusal

        launched, retries = [], []
        monkeypatch.setattr(op, "claude_binary", lambda: "/fixture/claude")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: launched.append(a))
        monkeypatch.setattr(pc, "_backoff", lambda n: retries.append(n))
        before = list(orchestrator_usage._CALL_STATS)
        with pytest.raises(ProviderRefusal) as exc:
            make_provider(provider)("верни предложение")
        assert exc.value.reason == "readonly_runtime_unqualified"
        assert exc.value.provider == "claude-cli"
        assert "до запуска" in exc.value.detail
        assert "mock" in exc.value.detail
        assert launched == []
        assert retries == []
        assert orchestrator_usage._CALL_STATS == before

    def test_permissive_parent_cannot_start_mutating_fixture(self, tmp_path, monkeypatch):
        """Реальный temp subprocess пишет в control; адаптер не запускает его вообще.

        Fixture не моделирует семантику флагов Claude и не квалифицирует Claude CLI.
        """
        import subprocess
        import sys
        from ai_ops_kit.providers import orchestrator_providers as op
        from ai_ops_kit.providers.response_contract import ProviderRefusal

        config = tmp_path / "settings.json"
        config.write_text(_test_json.dumps({
            "permissions": {"defaultMode": "bypassPermissions", "allow": ["Write", "Edit", "Bash"]},
            "mcpServers": {"mutator": {"command": "fixture-only"}},
            "enabledPlugins": {"mutator@fixture": True},
            "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "fixture-only"}]}]},
        }))
        cli = tmp_path / "fixture-claude"
        cli.write_text(f"#!{sys.executable}\n" + '''import json, os
from pathlib import Path
p = Path(os.environ["AIOPS_TEST_PARENT_CONFIG"])
c = json.loads(p.read_text())
effects = {
    "builtin": c["permissions"]["defaultMode"] == "bypassPermissions",
    "mcp": bool(c["mcpServers"]),
    "plugin": any(c["enabledPlugins"].values()),
    "hook": bool(c["hooks"]["SessionStart"]),
}
for name, enabled in effects.items():
    if enabled:
        (p.parent / (name + ".effect")).write_text("mutated")
print(json.dumps({"result": "fixture mutation happened"}))
''')
        cli.chmod(0o700)
        monkeypatch.setenv("AIOPS_TEST_PARENT_CONFIG", str(config))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
        config_before = config.read_bytes()
        # Доказываем, что fixture исполним и permissive config реально имеет эффект.
        control = subprocess.run([str(cli)], capture_output=True, text=True, check=True)
        assert _test_json.loads(control.stdout)["result"] == "fixture mutation happened"
        effects = [tmp_path / (name + ".effect") for name in ("builtin", "mcp", "plugin", "hook")]
        assert all(p.read_text() == "mutated" for p in effects)
        for p in effects:
            p.unlink()
        monkeypatch.setenv(op.CLAUDE_BIN_ENV, str(cli))
        real_run, attempts = subprocess.run, []

        def observe_launch(*args, **kwargs):
            attempts.append(args)
            return real_run(*args, **kwargs)

        monkeypatch.setattr(subprocess, "run", observe_launch)
        with pytest.raises(ProviderRefusal, match="readonly_runtime_unqualified"):
            make_claude_cli_provider()("верни предложение")
        assert attempts == []
        assert all(not p.exists() for p in effects)
        assert config.read_bytes() == config_before


@pytest.mark.unit
class TestClaudeCliEmptyIsRefusal:
    """Пустой result (rc=0) — НАЗВАННЫЙ отказ, а не тихая пустая строка (находка поля obs-2026-08-20).

    Прежде пустой ответ сворачивался в "" и доезжал до разбора куском без вердикта: судья «не
    выносил вердикт», гейт краснел «нет заключения reviewer» — правда по существу, ложь по причине.
    Теперь claude-cli на том же контракте, что API-провайдеры: пусто -> ProviderRefusal(empty_answer).
    """

    def test_empty_result_raises_named_refusal(self):
        from ai_ops_kit.providers.response_contract import ProviderRefusal

        def empty_runner(cmd):
            return _FakeResult(stdout=_test_json.dumps({"result": "", "usage": {}}))

        with pytest.raises(ProviderRefusal) as ei:
            make_claude_cli_provider(model="claude-opus", runner=empty_runner)("верни вердикт")
        assert ei.value.reason == "empty_answer"
        assert ei.value.provider == "claude-cli"

    def test_whitespace_only_result_is_also_empty(self):
        from ai_ops_kit.providers.response_contract import ProviderRefusal

        def blank_runner(cmd):
            return _FakeResult(stdout=_test_json.dumps({"result": "   \n  ", "usage": {}}))

        with pytest.raises(ProviderRefusal):
            make_claude_cli_provider(runner=blank_runner)("верни вердикт")

    def test_non_empty_result_still_returns_unchanged(self):
        """Обратная сторона: нормальный ответ не тронут — путь не сломан."""
        def ok_runner(cmd):
            return _FakeResult(stdout=_test_json.dumps({"result": "ВЕРДИКТ", "usage": {}}))

        assert make_claude_cli_provider(runner=ok_runner)("верни вердикт") == "ВЕРДИКТ"


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
        """Ключи offline argv стоят до разделителя; это не proof effective permissions."""
        prompt = "---\nid: intake-classifier\ntype: agent\n---\n\n## Задача\nОписать контур"
        seen = {}

        def runner(cmd):
            seen["cmd"] = cmd
            return _FakeResult(stdout=_test_json.dumps({"result": "VERDICT", "usage": {}}))

        make_claude_cli_provider(runner=runner)(prompt)
        cmd = seen.get("cmd") or []
        sep = cmd.index("--") if "--" in cmd else -1
        assert sep >= 0
        assert all(f in cmd[:sep] for f in ("--output-format", "--tools", "--allowedTools"))


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
