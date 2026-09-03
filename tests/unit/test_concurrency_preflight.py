"""Гранулярные тесты concurrency_preflight (мигрировано из test_concurrency_preflight_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import os

import pytest

from concurrency_preflight import (
    Path,
    _git,
    _parse_owner_repo,
    _prs_overlap,
    open_prs_via_rest,
    preflight,
)


@pytest.fixture
def git_repo(tmp_path):
    repo = tmp_path
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "f.txt").write_text("v1", encoding="utf-8")
    (repo / "other.txt").write_text("x", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "c1")
    _git(repo, "branch", "-M", "main")
    _git(repo, "checkout", "-q", "-b", "feature")
    _git(repo, "checkout", "-q", "main")
    (repo / "f.txt").write_text("v2", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "parallel: f.txt live actions")
    _git(repo, "checkout", "-q", "feature")
    return repo


@pytest.mark.unit
class TestPreflight:
    def test_collision_base_changed(self, git_repo):
        r = preflight(git_repo, "main", ["f.txt"])
        assert r["verdict"] == "collision"
        assert isinstance(r["base_changes"], list)
        assert any("parallel" in c["subject"] for c in r["base_changes"])

    def test_clean_untouched_path(self, git_repo):
        r = preflight(git_repo, "main", ["other.txt"])
        assert r["verdict"] == "clean"
        assert r["base_changes"] == []

    def test_active_work_overlap(self, git_repo):
        aw = git_repo / "aw.yaml"
        aw.write_text("schema_version: 1\nkind: active-work\nactive:\n"
                      "  - {id: x, branch: feature/x, status: in-progress, "
                      "affected_areas: [materials-page], owner_session: s}\n", encoding="utf-8")
        r = preflight(git_repo, "main", ["other.txt"], areas=["materials-page"],
                      active_work_path=str(aw))
        assert r["verdict"] == "collision"
        assert any(a["id"] == "x" for a in r["active_work_overlap"])

    def test_done_record_no_false_overlap(self, git_repo):
        aw_done = git_repo / "aw_done.yaml"
        aw_done.write_text("schema_version: 1\nkind: active-work\nactive:\n"
                           "  - {id: olddone, branch: feature/old, status: done, "
                           "affected_areas: [materials-page], owner_session: s}\n", encoding="utf-8")
        r = preflight(git_repo, "main", ["other.txt"], areas=["materials-page"],
                      active_work_path=str(aw_done))
        assert all(a.get("id") != "olddone" for a in r["active_work_overlap"])

    def test_no_base_unknown(self, git_repo):
        r = preflight(git_repo, "origin/nonexistent", ["f.txt"])
        assert isinstance(r["base_changes"], str)


@pytest.mark.unit
class TestRestFallback:
    def test_rest_without_token_unavailable(self, git_repo, monkeypatch):
        _saved = {k: os.environ.pop(k, None) for k in ("GITHUB_TOKEN", "GH_TOKEN")}
        # #402: env пуст И gh-fallback пуст -> токена нет нигде
        import ai_ops_kit.gates.concurrency_preflight as _cpmod
        monkeypatch.setattr(_cpmod, "_github_token", lambda: None)
        try:
            rest = open_prs_via_rest(git_repo, ["f.txt"])
            assert rest["status"] == "unavailable" and "GITHUB_TOKEN" in rest["note"]
        finally:
            for k, v in _saved.items():
                if v is not None:
                    os.environ[k] = v


@pytest.mark.unit
class TestParseOwnerRepo:
    def test_https_git(self):
        assert _parse_owner_repo("https://github.com/acme/widget.git") == ("acme", "widget")

    def test_https_no_git(self):
        assert _parse_owner_repo("https://github.com/acme/widget") == ("acme", "widget")

    def test_ssh_scp_style(self):
        assert _parse_owner_repo("git@github.com:acme/widget.git") == ("acme", "widget")

    def test_garbage_none(self):
        assert _parse_owner_repo("не-url") is None


@pytest.mark.unit
class TestPrsOverlap:
    def test_overlap_detected(self):
        recs = [{"number": 7, "title": "A", "files": ["src/a.ts", "src/b.ts"]},
                {"number": 8, "title": "B", "files": ["docs/x.md"]}]
        hits = _prs_overlap(recs, ["src/b.ts"])
        assert len(hits) == 1 and hits[0]["number"] == 7
        assert hits[0]["shared_paths"] == ["src/b.ts"]

    def test_no_overlap(self):
        recs = [{"number": 7, "title": "A", "files": ["src/a.ts", "src/b.ts"]},
                {"number": 8, "title": "B", "files": ["docs/x.md"]}]
        assert _prs_overlap(recs, ["src/c.ts"]) == []
