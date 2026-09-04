"""Юнит-тесты ai_ops_run: провайдеры и маршрутизация — fallback, trust, route, KLP."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]

from ai_ops_kit.engine import ai_ops_run


@pytest.mark.critical_path
@pytest.mark.unit
class TestProviderFallback:
    """Tests for _with_provider_fallback — retryable infra failure handling."""

    def test_fallback_on_timeout(self):
        """Retryable infra failure should trigger fallback provider."""
        def primary(prompt):
            raise TimeoutError("connection timeout")

        def secondary(prompt):
            return "fallback response"

        wrapped = ai_ops_run._with_provider_fallback(primary, secondary)
        result = wrapped("test prompt")
        assert result == "fallback response"

    def test_non_retryable_not_caught(self):
        """Non-retryable errors should propagate, not trigger fallback."""
        def primary(prompt):
            raise ValueError("invalid input")

        def secondary(prompt):
            return "fallback"

        wrapped = ai_ops_run._with_provider_fallback(primary, secondary)
        with pytest.raises(ValueError):
            wrapped("test")

    def test_no_secondary_returns_primary(self):
        """secondary=None should return primary unwrapped."""
        def primary(prompt):
            return "primary"

        wrapped = ai_ops_run._with_provider_fallback(primary, None)
        assert wrapped is primary


# Здесь стояло ПЕРВОЕ объявление `TestPrintHuman` (ревизия 2026-08-11). Ниже в файле есть второе
# с тем же именем — Python оставляет последнее, и это первое не исполнялось никогда. Второе его
# полностью содержит (тот же `test_print_human_no_crash` плюс два), так что удаление — снятие
# затенённого дубля, а не потеря проверки.


@pytest.mark.critical_path
@pytest.mark.unit
class TestRouteSelection:
    """Tests for task routing — QUICK vs ENGINEERING."""

    def _init_repo(self, child_root):
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=child_root, capture_output=True)
        (child_root / "dummy.txt").write_text("init")
        subprocess.run(["git", "add", "."], cwd=child_root, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=child_root, capture_output=True)

    def test_quick_route_returns_planned(self, child_root):
        """QUICK task with controller engine -> planned status."""
        self._init_repo(child_root)
        report = ai_ops_run.run(
            task_text="fix typo",
            signals={"task_type": "QUICK", "size": "small", "risk": "low"},
            child_root=child_root,
            feature="quick-test",
            engine="controller",
        )
        assert report["status"] == "planned"

    def test_engineering_route_returns_planned(self, child_root):
        """ENGINEERING task with controller engine -> planned status."""
        self._init_repo(child_root)
        report = ai_ops_run.run(
            task_text="refactor module",
            signals={"task_type": "ENGINEERING", "size": "medium", "risk": "medium"},
            child_root=child_root,
            feature="eng-test",
            engine="controller",
        )
        assert report["status"] == "planned"


@pytest.mark.critical_path
@pytest.mark.unit
class TestLoadKlpByEnv:
    """Tests for _load_klp_by_env — KLP entries by env_ref."""

    def test_no_policy_file(self, tmp_path):
        """No key-lifecycle.yaml -> empty dict."""
        result = ai_ops_run._load_klp_by_env(tmp_path)
        assert result == {}

    def test_with_policy_file(self, tmp_path):
        """Valid key-lifecycle.yaml -> dict keyed by env_ref."""
        pdir = tmp_path / ".ai" / "policies"
        pdir.mkdir(parents=True)
        import yaml
        data = {
            "keys": [
                {"env_ref": "OPENAI_API_KEY", "ttl_days": 90},
                {"env_ref": "ANTHROPIC_API_KEY", "ttl_days": 30},
            ]
        }
        (pdir / "key-lifecycle.yaml").write_text(
            yaml.safe_dump(data), encoding="utf-8")
        result = ai_ops_run._load_klp_by_env(tmp_path)
        assert "OPENAI_API_KEY" in result
        assert "ANTHROPIC_API_KEY" in result
        assert result["OPENAI_API_KEY"]["ttl_days"] == 90

    def test_empty_keys(self, tmp_path):
        """Empty keys list -> empty dict."""
        pdir = tmp_path / ".ai" / "policies"
        pdir.mkdir(parents=True)
        import yaml
        (pdir / "key-lifecycle.yaml").write_text(
            yaml.safe_dump({"keys": []}), encoding="utf-8")
        result = ai_ops_run._load_klp_by_env(tmp_path)
        assert result == {}


@pytest.mark.critical_path
@pytest.mark.unit
class TestProviderTrust:
    """Tests for _provider_trust — JIT provider trust checking."""

    def test_key_present_no_klp(self):
        """Key in env, no KLP entry -> ready."""
        import datetime
        now = datetime.date.today().isoformat()
        result = ai_ops_run._provider_trust("deepseek", "K1", {}, {"K1": "x"}, now, {})
        assert result["ready"] is True

    def test_key_missing(self):
        """Key NOT in env -> not ready."""
        import datetime
        now = datetime.date.today().isoformat()
        result = ai_ops_run._provider_trust("qwen", "MISSING_KEY", {}, {}, now, {})
        assert result["ready"] is False
        assert result["reason"] is not None

    def test_klp_expired(self):
        """Key present but KLP rotation expired -> not ready."""
        import datetime
        now = datetime.date.today().isoformat()
        klp = {"K2": {"env_ref": "K2", "next_rotation_at": "2000-01-01"}}
        result = ai_ops_run._provider_trust("kimi", "K2", klp, {"K2": "x"}, now, {})
        assert result["ready"] is False

    def test_caching(self):
        """Same provider -> cached result (identity check)."""
        import datetime
        now = datetime.date.today().isoformat()
        cache = {}
        r1 = ai_ops_run._provider_trust("p", "K1", {}, {"K1": "x"}, now, cache)
        r2 = ai_ops_run._provider_trust("p", "K1", {}, {"K1": "x"}, now, cache)
        assert r1 is r2


@pytest.mark.critical_path
@pytest.mark.unit
class TestProviderFallbackExtended:
    """Extended tests for _with_provider_fallback."""

    def test_fallback_stays_on_secondary(self):
        """After switch, subsequent calls go to secondary directly."""
        call_log = []

        def primary(prompt):
            call_log.append("primary")
            raise TimeoutError("timeout")

        def secondary(prompt):
            call_log.append("secondary")
            return f"result-{prompt}"

        wrapped = ai_ops_run._with_provider_fallback(primary, secondary)
        r1 = wrapped("first")
        r2 = wrapped("second")
        assert r1 == "result-first"
        assert r2 == "result-second"
        # After first switch, primary should NOT be called again
        assert call_log == ["primary", "secondary", "secondary"]

    def test_on_switch_callback(self):
        """on_switch callback is called when switching to fallback."""
        switched = {"called": False, "error": None}

        def primary(prompt):
            raise TimeoutError("timeout")

        def secondary(prompt):
            return "ok"

        def on_sw(e):
            switched["called"] = True
            switched["error"] = e

        wrapped = ai_ops_run._with_provider_fallback(primary, secondary, on_switch=on_sw)
        wrapped("test")
        assert switched["called"] is True
        assert isinstance(switched["error"], TimeoutError)


@pytest.mark.critical_path
@pytest.mark.unit
class TestProviderTrustRotationReason:
    """Просроченная KLP-ротация несёт человекочитаемую причину (не только ready=False)."""

    def test_expired_rotation_reason_mentions_rotation(self):
        """rc3 trust: KLP-ротация просрочена -> reason содержит 'ротация'."""
        import datetime
        now = datetime.date.today().isoformat()
        klp = {"K2": {"env_ref": "K2", "next_rotation_at": "2000-01-01"}}
        result = ai_ops_run._provider_trust("kimi", "K2", klp, {"K2": "x"}, now, {})
        assert result["ready"] is False
        assert "ротация" in (result.get("reason") or "")


@pytest.fixture(scope="module")
def boom_run(tmp_path_factory):
    """Pipeline-прогон, где провайдер бросает ConnectionResetError. Один раз на модуль."""
    root = tmp_path_factory.mktemp("boom")
    subprocess.run(["git", "-C", str(root), "init", "-q"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], capture_output=True)
    (root / "f").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "i"], capture_output=True)

    def _boom(c):
        raise ConnectionResetError("[Errno 54] Connection reset by peer")

    rep = ai_ops_run.run(
        task_text="задача с падающим провайдером",
        signals={"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]},
        child_root=root, engine="pipeline", execute=True, proposer=_boom, feature="boomwi",
    )
    return root, rep


@pytest.mark.critical_path
@pytest.mark.unit
class TestProviderFailureTyped:
    """v3.0-rc17: исключение провайдера -> честный типизированный error-отчёт."""

    def test_failure_class_network_retryable(self, boom_run):
        """ConnectionResetError -> failure_class=='network', retryable True."""
        _, rep = boom_run
        assert rep.get("status") == "error"
        assert (rep.get("failure") or {}).get("failure_class") == "network"
        assert (rep.get("failure") or {}).get("retryable") is True

    def test_exit_code_two(self, boom_run):
        """exit_code(provider-error) == 2."""
        _, rep = boom_run
        assert ai_ops_run.exit_code(rep) == 2

    def test_active_work_blocked_with_reason(self, boom_run):
        """Падение провайдера -> active-work снята как blocked, ConnectionResetError в status_reason."""
        from ai_ops_kit.lifecycle import active_work
        root, _ = boom_run
        awd = active_work.load(root / ".ai" / "runtime" / "active-work.yaml")
        entry = next((w for w in awd.get("active", []) if w.get("id") == "boomwi"), None)
        assert entry is not None
        assert entry.get("status") == "blocked"
        assert "ConnectionResetError" in (entry.get("status_reason") or "")
