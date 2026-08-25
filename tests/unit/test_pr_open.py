"""Гранулярные тесты pr_open (мигрировано из test_pr_open_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import os
import subprocess
import tempfile

import pytest

import pr_open

from pr_open import (
    _pr_payload,
    open_draft_pr,
    reconcile_delivery,
)


@pytest.fixture
def stash_gh():
    """Сохраняет и восстанавливает _gh_request и _cp."""
    orig_gh, orig_cp = pr_open._gh_request, pr_open._cp
    yield
    pr_open._gh_request = orig_gh
    pr_open._cp = orig_cp


@pytest.fixture
def git_repo():
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(["git", "-C", td, "init", "-q"])
        yield td


@pytest.mark.unit
class TestPrPayload:
    def test_draft_true(self):
        p = _pr_payload("ai-ops/x", "Заголовок", "Тело", base="main")
        assert p["draft"] is True

    def test_head_base_title_body(self):
        p = _pr_payload("ai-ops/x", "Заголовок", "Тело", base="main")
        assert p["head"] == "ai-ops/x"
        assert p["base"] == "main"
        assert p["title"] == "Заголовок"
        assert p["body"] == "Тело"


@pytest.mark.unit
class TestNoToken:
    def test_unavailable_without_token(self, git_repo, stash_gh):
        saved = {k: os.environ.pop(k, None) for k in ("GITHUB_TOKEN", "GH_TOKEN")}
        try:
            r = open_draft_pr(git_repo, "ai-ops/y", "T", "B")
            assert r["status"] == "unavailable"
            assert "GITHUB_TOKEN" in r["note"]
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v

    def test_unavailable_carries_payload(self, git_repo, stash_gh):
        saved = {k: os.environ.pop(k, None) for k in ("GITHUB_TOKEN", "GH_TOKEN")}
        try:
            r = open_draft_pr(git_repo, "ai-ops/y", "T", "B")
            assert r.get("payload", {}).get("draft") is True
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v


@pytest.mark.unit
class TestDefaultBranch:
    def test_base_none_resolves_default_branch(self, git_repo, stash_gh):
        subprocess.run(["git", "-C", git_repo, "remote", "add", "origin", "https://github.com/o/r.git"])
        real_gh, real_token = pr_open._gh_request, pr_open._cp._github_token
        try:
            pr_open._cp._github_token = lambda: "tok"

            def fake_gh(url, token, data=None, method="GET"):
                if method == "GET" and url.endswith("/repos/o/r"):
                    return {"default_branch": "develop"}, None
                if "pulls?head=" in url:
                    return [], None
                if method == "POST":
                    return {"html_url": "u", "number": 7, "draft": True}, None
                return {}, None

            pr_open._gh_request = fake_gh
            r = open_draft_pr(git_repo, "ai-ops/z", "T", "B", push=False)
            assert r["status"] == "opened"
            assert r.get("base") == "develop"
        finally:
            pr_open._gh_request = real_gh
            pr_open._cp._github_token = real_token


@pytest.mark.unit
class TestIdempotentPr:
    def test_existing_pr_returns_updated(self, git_repo, stash_gh):
        subprocess.run(["git", "-C", git_repo, "remote", "add", "origin", "https://github.com/o/r.git"])
        real_gh, real_token = pr_open._gh_request, pr_open._cp._github_token
        calls = {"post": 0}
        try:
            pr_open._cp._github_token = lambda: "tok"

            def fake_gh(url, token, data=None, method="GET"):
                if "pulls?head=" in url:
                    return [{"html_url": "u2", "number": 3, "draft": True}], None
                if method == "POST":
                    calls["post"] += 1
                    return {"html_url": "x", "number": 99}, None
                return {"default_branch": "main"}, None

            pr_open._gh_request = fake_gh
            before = calls["post"]
            r = open_draft_pr(git_repo, "ai-ops/z", "T", "B", base="main", push=False)
            assert r["status"] == "updated"
            assert r["number"] == 3
            assert calls["post"] == before
        finally:
            pr_open._gh_request = real_gh
            pr_open._cp._github_token = real_token


@pytest.mark.unit
class TestAmbiguousPost:
    def test_ambiguous_post_outcome_unknown(self, git_repo, stash_gh):
        subprocess.run(["git", "-C", git_repo, "remote", "add", "origin", "https://github.com/o/r.git"])
        real_gh, real_token = pr_open._gh_request, pr_open._cp._github_token
        cap = {}
        try:
            pr_open._cp._github_token = lambda: "tok"

            def fake_gh(url, token, data=None, method="GET"):
                if "pulls?head=" in url:
                    return [], None
                if method == "POST":
                    cap["body"] = (data or {}).get("body")
                    return None, "URLError"
                return {"default_branch": "main"}, None

            pr_open._gh_request = fake_gh
            r = open_draft_pr(git_repo, "ai-ops/z", "T", "B", base="main", push=False, delivery_id="deadbeef")
            assert r["status"] == "outcome_unknown"
            assert r.get("repository") == "o/r"
        finally:
            pr_open._gh_request = real_gh
            pr_open._cp._github_token = real_token

    def test_delivery_id_in_body(self, git_repo, stash_gh):
        subprocess.run(["git", "-C", git_repo, "remote", "add", "origin", "https://github.com/o/r.git"])
        real_gh, real_token = pr_open._gh_request, pr_open._cp._github_token
        cap = {}
        try:
            pr_open._cp._github_token = lambda: "tok"

            def fake_gh(url, token, data=None, method="GET"):
                if "pulls?head=" in url:
                    return [], None
                if method == "POST":
                    cap["body"] = (data or {}).get("body")
                    return None, "URLError"
                return {"default_branch": "main"}, None

            pr_open._gh_request = fake_gh
            open_draft_pr(git_repo, "ai-ops/z", "T", "B", base="main", push=False, delivery_id="deadbeef")
            assert "ai-ops-delivery-id: deadbeef" in (cap.get("body") or "")
        finally:
            pr_open._gh_request = real_gh
            pr_open._cp._github_token = real_token


@pytest.mark.unit
class TestReconcileDelivery:
    def test_reconcile_returns_facts(self, git_repo, stash_gh):
        subprocess.run(["git", "-C", git_repo, "remote", "add", "origin", "https://github.com/o/r.git"])
        real_gh, real_token = pr_open._gh_request, pr_open._cp._github_token
        try:
            pr_open._cp._github_token = lambda: "tok"

            def fake_gh(url, token, data=None, method="GET"):
                if "pulls?head=" in url and "state=all" in url:
                    return [{"html_url": "https://x/pr/9", "number": 9, "state": "open",
                             "head": {"sha": "abc1234"}, "base": {"ref": "main"}}], None
                return {}, None

            pr_open._gh_request = fake_gh
            rc = reconcile_delivery(git_repo, "ai-ops/z")
            assert rc["status"] == "found"
            assert rc["head_sha"] == "abc1234"
            assert rc["base_ref"] == "main"
            assert rc["repository"] == "o/r"
            assert rc["pr_state"] == "open"
        finally:
            pr_open._gh_request = real_gh
            pr_open._cp._github_token = real_token

    def test_absent_pr(self, git_repo, stash_gh):
        subprocess.run(["git", "-C", git_repo, "remote", "add", "origin", "https://github.com/o/r.git"])
        real_gh, real_token = pr_open._gh_request, pr_open._cp._github_token
        try:
            pr_open._cp._github_token = lambda: "tok"
            pr_open._gh_request = lambda url, token, data=None, method="GET": ([], None)
            rc = reconcile_delivery(git_repo, "ai-ops/z")
            assert rc == {"status": "absent", "repository": "o/r"}
        finally:
            pr_open._gh_request = real_gh
            pr_open._cp._github_token = real_token
