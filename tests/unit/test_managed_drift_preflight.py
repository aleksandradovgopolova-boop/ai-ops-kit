"""B2-27: managed_drift_preflight detects uncommitted managed files.

update --in-place leaves managed files in the working tree but worktree is created
from HEAD (commit). Uncommitted managed files don't reach the worktree — the run
goes on the old kit while doctor says "versions match". This preflight warns BEFORE
isolation so the human can commit first.

Boundary: does NOT auto-commit (human decides), only warns.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from pipeline_git import managed_drift_preflight


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, capture_output=True, check=True)


@pytest.fixture
def git_repo(tmp_path):
    """Minimal git repo with .ai/managed/ and .ai-ops.yaml committed."""
    repo = tmp_path / "child"
    repo.mkdir()
    (repo / ".ai" / "managed").mkdir(parents=True)
    (repo / ".ai-ops.yaml").write_text("parent:\n  installed_version: 3.36.12\n")
    (repo / ".ai" / "managed" / "VERSION").write_text("3.36.12\n")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    return repo


@pytest.mark.unit
class TestManagedDriftPreflight:
    def test_clean_repo_no_warning(self, git_repo):
        """No uncommitted managed files -> no warning."""
        result = managed_drift_preflight(git_repo)
        assert result is None

    def test_uncommitted_managed_file_warns(self, git_repo):
        """Modified .ai/managed/ file -> warning with file count."""
        (git_repo / ".ai" / "managed" / "VERSION").write_text("3.36.13\n")
        result = managed_drift_preflight(git_repo)
        assert result is not None
        assert "warning" in result
        assert "1 файл(ов)" in result["warning"]
        assert "VERSION" in result["warning"]
        assert "закоммичен" in result["warning"]

    def test_uncommitted_ai_ops_yaml_warns(self, git_repo):
        """Modified .ai-ops.yaml -> warning (installed_version drift)."""
        (git_repo / ".ai-ops.yaml").write_text("parent:\n  installed_version: 3.36.13\n")
        result = managed_drift_preflight(git_repo)
        assert result is not None
        assert "ai-ops.yaml" in result["warning"]  # f[3:] strips " M " prefix

    def test_multiple_files_sample(self, git_repo):
        """Many modified files -> sample shown, count correct."""
        for i in range(7):
            (git_repo / ".ai" / "managed" / f"file{i}.py").write_text(f"v{i}\n")
        result = managed_drift_preflight(git_repo)
        assert result is not None
        assert "7 файл(ов)" in result["warning"]
        assert "и ещё 2" in result["warning"]  # 7 - 5 = 2

    def test_unrelated_changes_no_warning(self, git_repo):
        """Changes outside .ai/managed/ and .ai-ops.yaml -> no warning."""
        (git_repo / "src").mkdir()
        (git_repo / "src" / "main.py").write_text("print('hello')\n")
        result = managed_drift_preflight(git_repo)
        assert result is None
