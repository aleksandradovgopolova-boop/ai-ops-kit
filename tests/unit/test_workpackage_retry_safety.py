"""Гранулярные тесты workpackage_executor: retry-safety — fail-closed без рабочего дерева.

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import contextlib
import io
import shutil
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


# ─── retry safety ──────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestRetrySafety:
    def test_no_worktree_fail_closed(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seqsafe", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                execute_sequence("рефактор safe-retry", three_area_sig, root, pkgs, _prop_for,
                                 feature="seqsafe", base=cur, author=True, author_proposer=_author,
                                 review=True, reviewer_proposer=_pass_reviewer)
            main_head_before = _git(root, "rev-parse", "HEAD")[1]
            main_status_before = _git(root, "status", "--porcelain")[1]

            wt = root / ".ai" / "worktrees" / "seqsafe"
            _git(root, "worktree", "remove", "--force", str(wt))
            shutil.rmtree(wt, ignore_errors=True)

            rt_unsafe = retry_package(root, "seqsafe", pkgs[1]["id"])
            main_head_after = _git(root, "rev-parse", "HEAD")[1]
            main_status_after = _git(root, "status", "--porcelain")[1]

            assert rt_unsafe.get("ok") is False
            assert "fail-closed" in (rt_unsafe.get("error") or "")
            assert main_head_after == main_head_before
            assert main_status_after == main_status_before
