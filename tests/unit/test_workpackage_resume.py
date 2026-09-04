"""Гранулярные тесты workpackage_executor: resume (checkpoint, skip, битый отчёт).

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
)

from ai_ops_kit.engine import atomic_planner

from _workpackage_helpers import (
    _author,
    _mkrepo,
    _pass_reviewer,
    _prop_for,
)


# ─── Resume ────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestResume:
    def test_head_not_at_checkpoint_error(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seq", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                execute_sequence("x", three_area_sig, root, pkgs, _prop_for, feature="seq",
                                       base=cur, author=True, author_proposer=_author,
                                       review=True, reviewer_proposer=_pass_reviewer)
            seq_drift = execute_sequence("x", three_area_sig, root, pkgs, _prop_for, feature="seq",
                                         base=cur, author=True, author_proposer=_author,
                                         review=True, reviewer_proposer=_pass_reviewer,
                                         resume_from=pkgs[1]["id"])
            assert "error" in seq_drift
            assert "checkpoint" in (seq_drift.get("error") or "").lower()

    def test_valid_checkpoint_resumed_skip(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seq", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                seq = execute_sequence("большой рефактор", three_area_sig, root, pkgs, _prop_for,
                                       feature="seq", base=cur, author=True, author_proposer=_author,
                                       review=True, reviewer_proposer=_pass_reviewer)
            _git(root / ".ai" / "worktrees" / "seq", "reset", "--hard", seq["packages"][0]["sha"])
            buf2 = io.StringIO()
            with contextlib.redirect_stderr(buf2):
                seq_r = execute_sequence("большой рефактор", three_area_sig, root, pkgs, _prop_for,
                                         feature="seq", base=cur, author=True, author_proposer=_author,
                                         review=True, reviewer_proposer=_pass_reviewer,
                                         resume_from=pkgs[1]["id"])
            skipped = [p for p in seq_r["packages"] if p.get("status") == "resumed-skip"]
            assert "error" not in seq_r
            assert seq_r.get("resumed_from") == pkgs[1]["id"]
            assert len(skipped) == 1
            assert skipped[0]["id"] == pkgs[0]["id"]
            assert skipped[0].get("sha")

    def test_unknown_resume_from_error(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seq", child_root=root)["work_packages"]
            seq_bad = execute_sequence("x", three_area_sig, root, pkgs, _prop_for, feature="seq",
                                       base=cur, resume_from="pkg-НЕТ-ТАКОГО")
            assert "error" in seq_bad
            assert seq_bad["executed_all"] is False
            assert not seq_bad["packages"]

    def test_corrupt_prior_report_on_resume_error(self, three_area_sig):
        # K6-характеристика: пакет ДО resume_from с БИТЫМ report.json (невалидный JSON) не
        # подтверждается — resume честно ошибается, пакет НЕ попадает в completed. Фиксирует ветку
        # `_verify_skipped`/`_verify_resumed_package` «битый отчёт» перед выносом её из execute_sequence.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seqc", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                execute_sequence("x", three_area_sig, root, pkgs, _prop_for, feature="seqc",
                                 base=cur, author=True, author_proposer=_author,
                                 review=True, reviewer_proposer=_pass_reviewer)
            _rep = (root / "features" / "seqc" / "work-packages" / pkgs[0]["id"] / "report.json")
            _rep.write_text("{ это не JSON", encoding="utf-8")
            seq_c = execute_sequence("x", three_area_sig, root, pkgs, _prop_for, feature="seqc",
                                     base=cur, resume_from=pkgs[1]["id"])
            assert "error" in seq_c
            assert "битый отчёт" in (seq_c.get("error") or "")
            assert pkgs[0]["id"] not in seq_c.get("completed", [])

    def test_unconfirmed_skipped_package_error(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seqe", child_root=root)["work_packages"]
            seq_e = execute_sequence("x", three_area_sig, root, pkgs, _prop_for, feature="seqe",
                                     base=cur, resume_from=pkgs[1]["id"])
            assert "error" in seq_e
            assert pkgs[0]["id"] not in seq_e.get("completed", [])
