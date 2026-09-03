"""#402: токен для доставки берётся из env, а при его отсутствии — из `gh auth token`.

Раньше кит читал только GITHUB_TOKEN/GH_TOKEN и молча деградировал доставку до «нет токена»,
хотя gh на машине авторизован. gh — и так зависимость кита.
"""
from __future__ import annotations

import types

import pytest

from ai_ops_kit.gates import concurrency_preflight as cp


@pytest.mark.unit
class TestGithubTokenFallback:
    def test_env_token_wins(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "env-tok")
        # gh не должен даже зваться при наличии env-токена
        monkeypatch.setattr(cp.subprocess, "run",
                            lambda *a, **k: pytest.fail("gh вызван при наличии env-токена"))
        assert cp._github_token() == "env-tok"

    def test_fallback_to_gh_auth_token(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)

        def fake_run(cmd, **kw):
            assert cmd == ["gh", "auth", "token"]
            return types.SimpleNamespace(returncode=0, stdout="gh-tok\n", stderr="")

        monkeypatch.setattr(cp.subprocess, "run", fake_run)
        assert cp._github_token() == "gh-tok"

    def test_none_when_no_env_and_gh_unauthed(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.setattr(cp.subprocess, "run",
                            lambda *a, **k: types.SimpleNamespace(returncode=1, stdout="", stderr="no auth"))
        assert cp._github_token() is None

    def test_none_when_gh_missing(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)

        def boom(*a, **k):
            raise FileNotFoundError("gh not installed")

        monkeypatch.setattr(cp.subprocess, "run", boom)
        assert cp._github_token() is None   # не падаем, если gh нет
