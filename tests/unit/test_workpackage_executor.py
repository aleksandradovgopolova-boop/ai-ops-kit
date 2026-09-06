"""Гранулярные тесты workpackage_executor: декомпозиция и happy-path execute_sequence.

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import contextlib
import io
import tempfile

import pytest

pytestmark = pytest.mark.slow  # #465: тяжёлый интеграционный/мета-тест — в slow (гоняется в selftests, не держит fast-стену)

from ai_ops_kit.engine.workpackage_executor import (
    Path,
    execute_sequence,
)

from ai_ops_kit.engine import atomic_planner

from _workpackage_helpers import (
    _author,
    _mkrepo,
    _pass_reviewer,
    _prop_for,
)


# ─── Plan decomposition ───────────────────────────────────────────────────────

@pytest.mark.unit
class TestPlanDecomposition:
    def test_three_packages_with_deps(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _mkrepo(td)
            wp = atomic_planner.decompose(three_area_sig, wid="seq", child_root=root)
            pkgs = wp["work_packages"]
            assert len(pkgs) == 3
            assert pkgs[1]["depends_on"] == [pkgs[0]["id"]]


# ─── execute_sequence: happy path ──────────────────────────────────────────────

@pytest.mark.unit
class TestExecuteSequenceHappyPath:
    def test_all_three_executed(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seq", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                seq = execute_sequence("большой рефактор", three_area_sig, root, pkgs, _prop_for,
                                       feature="seq", base=cur, author=True, author_proposer=_author,
                                       review=True, reviewer_proposer=_pass_reviewer)
            assert seq["executed_all"] is True

    def test_unique_sha_per_package(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seq", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                seq = execute_sequence("большой рефактор", three_area_sig, root, pkgs, _prop_for,
                                       feature="seq", base=cur, author=True, author_proposer=_author,
                                       review=True, reviewer_proposer=_pass_reviewer)
            shas = [p.get("sha") for p in seq["packages"]]
            assert all(shas) and len(set(shas)) == 3

    def test_sequential_chain(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seq", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                seq = execute_sequence("большой рефактор", three_area_sig, root, pkgs, _prop_for,
                                       feature="seq", base=cur, author=True, author_proposer=_author,
                                       review=True, reviewer_proposer=_pass_reviewer)
            assert seq["sequential_chain"] is True

    def test_per_package_reports_on_disk(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seq", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                seq = execute_sequence("большой рефактор", three_area_sig, root, pkgs, _prop_for,
                                       feature="seq", base=cur, author=True, author_proposer=_author,
                                       review=True, reviewer_proposer=_pass_reviewer)
            assert all((root / "features" / "seq" / "work-packages" / p["id"] / "report.json").is_file()
                       for p in seq["packages"])

    def test_sequence_report_saved(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seq", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                execute_sequence("большой рефактор", three_area_sig, root, pkgs, _prop_for,
                                       feature="seq", base=cur, author=True, author_proposer=_author,
                                       review=True, reviewer_proposer=_pass_reviewer)
            assert (root / "features" / "seq" / "sequence-report.yaml").is_file()

    def test_resume_point_per_package(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seq", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                seq = execute_sequence("большой рефактор", three_area_sig, root, pkgs, _prop_for,
                                       feature="seq", base=cur, author=True, author_proposer=_author,
                                       review=True, reviewer_proposer=_pass_reviewer)
            assert all(p.get("resume_point") for p in seq["packages"])
