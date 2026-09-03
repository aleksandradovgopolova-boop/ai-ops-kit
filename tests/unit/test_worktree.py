"""Гранулярные тесты worktree (мигрировано из test_worktree_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import tempfile

import pytest

from ai_ops_kit.engine.worktree import (
    Path,
    _branch_exists,
    _git,
    add,
    remove,
)


@pytest.fixture
def git_repo():
    """Инициализированный git-репо с одним коммитом."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _git(root, "init", "-q")
        _git(root, "config", "user.email", "t@t")
        _git(root, "config", "user.name", "t")
        (root / "f.txt").write_text("x", encoding="utf-8")
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "init")
        yield root


@pytest.mark.unit
class TestAdd:
    def test_add_main_returns_error(self, git_repo):
        assert add(git_repo, "wi-1", "main") == 1

    def test_add_empty_branch_returns_error(self, git_repo):
        assert add(git_repo, "wi-1", "") == 1

    def test_add_creates_worktree(self, git_repo):
        rc = add(git_repo, "wi-1", "feature/wi-1")
        assert rc == 0
        assert (git_repo / ".ai/worktrees/wi-1").is_dir()

    def test_add_list_contains_new_worktree(self, git_repo):
        add(git_repo, "wi-1", "feature/wi-1")
        rc, out, _ = _git(git_repo, "worktree", "list", "--porcelain")
        assert "wi-1" in out
        assert "feature/wi-1" in out

    def test_add_duplicate_returns_error(self, git_repo):
        add(git_repo, "wi-1", "feature/wi-1")
        assert add(git_repo, "wi-1", "feature/wi-1b") == 1

    def test_add_traversal_id_rejected(self, git_repo):
        assert add(git_repo, "../escape", "feature/x") == 1
        assert not (git_repo.parent / "escape").exists()

    def test_add_absolute_id_rejected(self, git_repo):
        assert add(git_repo, "/tmp/evil", "feature/y") == 1


@pytest.mark.unit
class TestRemove:
    def test_remove_deletes_worktree(self, git_repo):
        add(git_repo, "wi-1", "feature/wi-1")
        assert remove(git_repo, "wi-1") == 0
        assert not (git_repo / ".ai/worktrees/wi-1").exists()

    def test_remove_preserves_branch(self, git_repo):
        add(git_repo, "wi-1", "feature/wi-1")
        remove(git_repo, "wi-1")
        assert _branch_exists(git_repo, "feature/wi-1")

    def test_remove_traversal_id_rejected(self, git_repo):
        assert remove(git_repo, "../escape") == 1
