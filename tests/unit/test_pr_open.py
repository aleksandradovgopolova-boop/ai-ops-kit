"""Гранулярные тесты pr_open (мигрировано из test_pr_open_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import os
import subprocess
import tempfile

import pytest

from ai_ops_kit.delivery import pr_open

from ai_ops_kit.delivery.pr_open import (
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
        real_token = pr_open._cp._github_token
        pr_open._cp._github_token = lambda: None   # #402: и gh-fallback пуст -> токена нет нигде
        try:
            r = open_draft_pr(git_repo, "ai-ops/y", "T", "B")
            assert r["status"] == "unavailable"
            assert "GITHUB_TOKEN" in r["note"]
        finally:
            pr_open._cp._github_token = real_token
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v

    def test_unavailable_carries_payload(self, git_repo, stash_gh):
        saved = {k: os.environ.pop(k, None) for k in ("GITHUB_TOKEN", "GH_TOKEN")}
        real_token = pr_open._cp._github_token
        pr_open._cp._github_token = lambda: None   # #402: и gh-fallback пуст -> токена нет нигде
        try:
            r = open_draft_pr(git_repo, "ai-ops/y", "T", "B")
            assert r.get("payload", {}).get("draft") is True
        finally:
            pr_open._cp._github_token = real_token
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


@pytest.mark.unit
class TestP0AuthoritativePushedSha:
    """#399: после УСПЕШНОГО push head_sha берётся из локально запушенного коммита (git-факт), а не
    из ответа GitHub API про head PR — тот отстаёт на секунды и давал ложный sha_verified=false на
    реально успешной доставке. Мокаем git (push ok + rev-parse=LOCAL) и API (отставший STALE)."""

    LOCAL = "a6d2176f00000000000000000000000000000abc"
    STALE = "0000000000000000000000000000000000stale0"

    def _mock(self, existing_pr):
        def fake_git(root, *args):
            if args[:1] == ("remote",):
                return (0, "https://github.com/o/r.git", "")
            if args and args[0] == "push":
                return (0, "", "")               # push успешен
            if args and args[0] == "rev-parse":
                return (0, self.LOCAL + "\n", "")  # локальный запушенный sha — авторитет
            return (0, "", "")

        def fake_gh(url, token, data=None, method="GET"):
            if "pulls?head=" in url:
                return (list(existing_pr), None)
            if method == "POST":
                return ({"html_url": "x", "number": 9, "draft": True,
                         "head": {"sha": self.STALE}}, None)   # POST-ответ тоже отстаёт
            return ({"default_branch": "main"}, None)
        return fake_git, fake_gh

    def test_updated_path_uses_pushed_sha_not_stale_api(self, stash_gh):
        real_gh, real_git, real_tok = pr_open._gh_request, pr_open._git, pr_open._cp._github_token
        try:
            pr_open._cp._github_token = lambda: "tok"
            existing = [{"html_url": "u", "number": 3, "draft": True,
                         "head": {"sha": self.STALE}, "base": {"ref": "main"}}]
            pr_open._git, pr_open._gh_request = self._mock(existing)
            r = open_draft_pr("/no/such/root", "ai-ops/z", "T", "B", base="main", push=True)
            assert r["status"] == "updated"
            assert r["head_sha"] == self.LOCAL     # git-факт
            assert r["head_sha"] != self.STALE     # НЕ отставший ответ API (регрессия P0)
        finally:
            pr_open._gh_request, pr_open._git, pr_open._cp._github_token = real_gh, real_git, real_tok

    def test_opened_path_uses_pushed_sha(self, stash_gh):
        real_gh, real_git, real_tok = pr_open._gh_request, pr_open._git, pr_open._cp._github_token
        try:
            pr_open._cp._github_token = lambda: "tok"
            pr_open._git, pr_open._gh_request = self._mock([])   # PR ещё нет -> POST -> opened
            r = open_draft_pr("/no/such/root", "ai-ops/z", "T", "B", base="main", push=True)
            assert r["status"] == "opened"
            assert r["head_sha"] == self.LOCAL     # и на пути opened — git-факт, не отставший POST-ответ
        finally:
            pr_open._gh_request, pr_open._git, pr_open._cp._github_token = real_gh, real_git, real_tok

    def test_no_push_falls_back_to_api_sha(self, stash_gh):
        """push=False -> локального факта нет -> честный fallback на sha из API (ветвь `pushed_sha or`)."""
        real_gh, real_git, real_tok = pr_open._gh_request, pr_open._git, pr_open._cp._github_token
        try:
            pr_open._cp._github_token = lambda: "tok"
            existing = [{"html_url": "u", "number": 3, "draft": True,
                         "head": {"sha": self.STALE}, "base": {"ref": "main"}}]
            pr_open._git, pr_open._gh_request = self._mock(existing)
            r = open_draft_pr("/no/such/root", "ai-ops/z", "T", "B", base="main", push=False)
            assert r["status"] == "updated"
            assert r["head_sha"] == self.STALE     # без push авторитета нет — берём, что даёт API
        finally:
            pr_open._gh_request, pr_open._git, pr_open._cp._github_token = real_gh, real_git, real_tok


@pytest.mark.unit
class TestStatusDocsInPrBody:
    """#404: тело сгенерированного PR явно сообщает, как прогон обошёлся со статус-доками —
    обновил их или назвал причину-исключение. Так PR не упирается молча в собственный гейт свежести."""

    def test_note_reports_update_when_doc_fresh(self):
        note = pr_open._status_docs_note(
            {"managed": True, "doc": "context/product/ProductStatus.md",
             "reviewed_at": "2026-09-04", "fresh_today": True})
        assert "обновлён этой доставкой" in note
        assert "context/product/ProductStatus.md" in note

    def test_note_names_exception_when_no_managed_doc(self):
        note = pr_open._status_docs_note(
            {"managed": False, "reason": "в репозитории нет статус-дока (living-status) — обновлять нечего"})
        assert "причина-исключение" in note and "нет статус-дока" in note

    def test_note_flags_stale_managed_doc(self):
        note = pr_open._status_docs_note(
            {"managed": True, "doc": "PROJECT_STATUS.md", "reviewed_at": "2026-01-01", "fresh_today": False})
        assert "не обновлён этой доставкой" in note

    def test_note_handles_missing_outcome(self):
        """Отсутствующий исход (None) не роняет сборку — читается как «обновлять нечего»."""
        assert "причина-исключение" in pr_open._status_docs_note(None)

    def test_pr_body_embeds_status_note(self):
        """Проба «краснеет на дефекте»: если сборка тела перестанет вкладывать строку про статус-доки,
        причина-исключение исчезнет из тела PR и этот assert покраснеет."""
        status = {"managed": False, "reason": "нет статус-дока"}
        body = pr_open.pr_body("W-1", "main", "abcdef123456", "cafe4567", status)
        assert "W-1" in body and "main" in body and "cafe4567" in body
        assert "причина-исключение: нет статус-дока" in body
