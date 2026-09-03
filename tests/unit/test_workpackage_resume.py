"""Гранулярные тесты workpackage_executor: resume, retry_package, retry-safety.

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import contextlib
import io
import shutil
import tempfile

import pytest

from workpackage_executor import (
    Path,
    _git,
    execute_sequence,
    retry_package,
)

import atomic_planner

from _workpackage_helpers import (
    _author,
    _mkrepo,
    _pass_reviewer,
    _prop_for,
    three_area_sig,
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

    def test_plan_drift_error(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seq", child_root=root)["work_packages"]
            # Сначала исполняем, чтобы sequence-plan.yaml появился на диске
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                execute_sequence("x", three_area_sig, root, pkgs, _prop_for, feature="seq",
                                 base=cur, author=True, author_proposer=_author,
                                 review=True, reviewer_proposer=_pass_reviewer)
            pkgs_drift = [dict(p) for p in pkgs]
            pkgs_drift[0] = {**pkgs_drift[0], "scope": ["ДРУГАЯ-ПОДСИСТЕМА"]}
            seq_pd = execute_sequence("x", three_area_sig, root, pkgs_drift, _prop_for, feature="seq",
                                      base=cur, resume_from=pkgs[1]["id"])
            assert "error" in seq_pd
            assert "дрейф" in (seq_pd.get("error") or "").lower()

    def test_plan_drift_without_resume_error(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seq", child_root=root)["work_packages"]
            # Сначала исполняем, чтобы sequence-plan.yaml появился на диске
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                execute_sequence("x", three_area_sig, root, pkgs, _prop_for, feature="seq",
                                 base=cur, author=True, author_proposer=_author,
                                 review=True, reviewer_proposer=_pass_reviewer)
            pkgs_drift = [dict(p) for p in pkgs]
            pkgs_drift[0] = {**pkgs_drift[0], "scope": ["ДРУГАЯ-ПОДСИСТЕМА"]}
            seq_pd2 = execute_sequence("x", three_area_sig, root, pkgs_drift, _prop_for, feature="seq", base=cur)
            assert "error" in seq_pd2
            assert "дрейф" in (seq_pd2.get("error") or "").lower()

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

    def test_retry_unknown_package_error(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seqrt", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                execute_sequence("рефактор для retry", three_area_sig, root, pkgs, _prop_for,
                                 feature="seqrt", base=cur, author=True, author_proposer=_author,
                                 review=True, reviewer_proposer=_pass_reviewer)
            assert retry_package(root, "seqrt", "НЕТ-ТАКОГО").get("ok") is False

    def test_base_contract_drift_error(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seqrt", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                execute_sequence("рефактор для retry", three_area_sig, root, pkgs, _prop_for,
                                 feature="seqrt", base=cur, author=True, author_proposer=_author,
                                 review=True, reviewer_proposer=_pass_reviewer)
            seq_bd = execute_sequence("другая база", three_area_sig, root, pkgs, _prop_for, feature="seqrt",
                                      base="release-xyz", author=True, author_proposer=_author,
                                      review=True, reviewer_proposer=_pass_reviewer,
                                      resume_from=pkgs[1]["id"])
            assert "error" in seq_bd
            assert "base-contract-drift" in (seq_bd.get("error") or "")


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
