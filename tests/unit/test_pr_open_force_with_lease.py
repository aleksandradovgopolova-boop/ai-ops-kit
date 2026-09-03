"""#401: delivery-ветку кит считает своей — при non-fast-forward пере-пушит --force-with-lease,
а не роняет прогон сырым rc=1. Прочие ошибки push (сеть/права) НЕ форсит."""
from __future__ import annotations

import pytest

import pr_open
from pr_open import open_draft_pr, _is_non_fast_forward


@pytest.fixture
def stash_gh():
    orig_gh, orig_cp, orig_git = pr_open._gh_request, pr_open._cp, pr_open._git
    # _wire мутирует АТРИБУТ модуля (_cp._github_token), а не привязку pr_open._cp —
    # восстановления самой ссылки мало, иначе заглушка "tok" утекает в другие файлы
    # на том же xdist-воркере (ловилось в test_github_token_fallback.py под --dist loadfile).
    orig_token = pr_open._cp._github_token
    yield
    pr_open._gh_request, pr_open._cp, pr_open._git = orig_gh, orig_cp, orig_git
    pr_open._cp._github_token = orig_token


@pytest.mark.unit
class TestIsNonFastForward:
    def test_detects_rejected(self):
        assert _is_non_fast_forward("! [rejected] main -> main (non-fast-forward)") is True

    def test_detects_fetch_first(self):
        assert _is_non_fast_forward("Updates were rejected; fetch first") is True

    def test_auth_error_is_not_nff(self):
        assert _is_non_fast_forward("fatal: Authentication failed") is False


@pytest.mark.unit
class TestForceWithLeaseOwnBranch:
    def _wire(self, first_push_err, force_ok=True):
        calls = []

        def fake_git(root, *args):
            calls.append(args)
            if args[:1] == ("remote",):
                return (0, "https://github.com/o/r.git", "")
            if args and args[0] == "push":
                if "--force-with-lease" in args:
                    return (0, "", "") if force_ok else (1, "", "! [rejected] (still behind)")
                return (1, "", first_push_err)
            if args and args[0] == "rev-parse":
                return (0, "abc123\n", "")
            return (0, "", "")

        def fake_gh(url, token, data=None, method="GET"):
            if "pulls?head=" in url:
                return ([], None)
            if method == "POST":
                return ({"html_url": "u", "number": 1, "draft": True, "head": {"sha": "abc123"}}, None)
            return ({"default_branch": "main"}, None)

        pr_open._cp._github_token = lambda: "tok"
        pr_open._git = fake_git
        pr_open._gh_request = fake_gh
        return calls

    def _pushed_force(self, calls):
        return any(a and a[0] == "push" and "--force-with-lease" in a for a in calls)

    def test_non_fast_forward_retried_with_force_with_lease(self, stash_gh):
        calls = self._wire("! [rejected] main -> main (non-fast-forward)")
        r = open_draft_pr("/root", "ai-ops/x", "T", "B", base="main", push=True)
        assert r["status"] == "opened"
        assert self._pushed_force(calls)   # разошедшуюся свою ветку форсим

    def test_auth_error_not_forced(self, stash_gh):
        calls = self._wire("fatal: Authentication failed")
        r = open_draft_pr("/root", "ai-ops/x", "T", "B", base="main", push=True)
        assert r["status"] == "error"
        assert not self._pushed_force(calls)   # не non-fast-forward -> НЕ форсим
