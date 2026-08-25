"""Гранулярные тесты gitio (мигрировано из test_gitio_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from gitio import git


@pytest.mark.unit
class TestGit:
    def test_not_a_repo(self, tmp_path):
        rc, out, err = git(tmp_path, "rev-parse", "--is-inside-work-tree")
        assert rc != 0 and isinstance(out, str) and isinstance(err, str)

    def test_init_and_commit(self, tmp_path):
        for a in (("init", "-q"), ("config", "user.email", "t@t"), ("config", "user.name", "t")):
            git(tmp_path, *a)
        (tmp_path / "f").write_text("x", encoding="utf-8")
        git(tmp_path, "add", "-A")
        git(tmp_path, "commit", "-q", "-m", "i")
        rc, out, _ = git(tmp_path, "rev-parse", "--abbrev-ref", "HEAD")
        assert rc == 0 and bool(out)

    def test_timeout_parameter(self, tmp_path):
        for a in (("init", "-q"), ("config", "user.email", "t@t"), ("config", "user.name", "t")):
            git(tmp_path, *a)
        (tmp_path / "f").write_text("x", encoding="utf-8")
        git(tmp_path, "add", "-A")
        git(tmp_path, "commit", "-q", "-m", "i")
        rc, _, _ = git(tmp_path, "status", "--porcelain", timeout=30)
        assert rc == 0
