"""Гранулярные тесты workpackage_executor: retry_package — сброс к чекпойнту и архив попытки.

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import contextlib
import io
import tempfile

import pytest

from ai_ops_kit.engine.workpackage_executor import (
    Path,
    _git,
    execute_sequence,
    retry_package,
)

from ai_ops_kit.engine import atomic_planner

from _workpackage_helpers import (
    _author,
    _mkrepo,
    _pass_reviewer,
    _prop_for,
)


# ─── retry_package ─────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestRetryPackage:
    def test_retry_resets_to_predecessor_checkpoint(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seqrt", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                seqrt = execute_sequence("рефактор для retry", three_area_sig, root, pkgs, _prop_for,
                                         feature="seqrt", base=cur, author=True, author_proposer=_author,
                                         review=True, reviewer_proposer=_pass_reviewer)
            p1_sha = seqrt["packages"][0].get("sha")
            wt = root / ".ai" / "worktrees" / "seqrt"
            assert p1_sha
            assert (root / "features" / "seqrt" / "sequence-plan.yaml").is_file()

            rt = retry_package(root, "seqrt", pkgs[1]["id"])
            head_after = _git(wt if wt.is_dir() else root, "rev-parse", "HEAD")[1]
            assert rt.get("ok") is True
            assert rt.get("checkpoint") == p1_sha
            assert head_after == p1_sha
            assert rt.get("predecessor") == pkgs[0]["id"]

    def test_retry_archives_failed_attempt(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seqrt", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                execute_sequence("рефактор для retry", three_area_sig, root, pkgs, _prop_for,
                                 feature="seqrt", base=cur, author=True, author_proposer=_author,
                                 review=True, reviewer_proposer=_pass_reviewer)
            retry_package(root, "seqrt", pkgs[1]["id"])
            assert (root / "features" / "seqrt" / "work-packages" / pkgs[1]["id"] / "attempts" / "attempt-1" / "report.json").is_file()
