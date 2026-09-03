"""Гранулярные тесты workpackage_executor: декомпозиция, happy-path execute_sequence, иммутабельный SequencePlan, sandbox.

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import contextlib
import io
import tempfile

import pytest

from workpackage_executor import (
    Path,
    execute_sequence,
    json,
)

import atomic_planner

from _workpackage_helpers import (
    _author,
    _mkrepo,
    _pass_reviewer,
    _prop_for,
    three_area_sig,
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


# ─── v2.124: immutable SequencePlan + lifecycle ────────────────────────────────

@pytest.mark.unit
class TestSequencePlanImmutable:
    def test_sequence_plan_yaml_written(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seq", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                execute_sequence("большой рефактор", three_area_sig, root, pkgs, _prop_for,
                                 feature="seq", base=cur, author=True, author_proposer=_author,
                                 review=True, reviewer_proposer=_pass_reviewer)
            assert (root / "features" / "seq" / "sequence-plan.yaml").is_file()

    def test_sequence_base_sha_durable(self, three_area_sig):
        import yaml as _yy
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seq", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                execute_sequence("большой рефактор", three_area_sig, root, pkgs, _prop_for,
                                 feature="seq", base=cur, author=True, author_proposer=_author,
                                 review=True, reviewer_proposer=_pass_reviewer)
            plan = _yy.safe_load((root / "features" / "seq" / "sequence-plan.yaml").read_text(encoding="utf-8"))
            assert bool(plan.get("sequence_base_sha")) and bool(plan.get("base_ref"))

    def test_corrupt_plan_lifecycle_corrupted(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            rc = Path(td)
            cur_c = _mkrepo(td)
            pk = atomic_planner.decompose(three_area_sig, wid="seqc", child_root=rc)["work_packages"]
            (rc / "features" / "seqc").mkdir(parents=True, exist_ok=True)
            (rc / "features" / "seqc" / "sequence-plan.yaml").write_text("{ это: [не, валидный, yaml", encoding="utf-8")
            before = (rc / "features" / "seqc" / "sequence-plan.yaml").read_text(encoding="utf-8")
            seq_c = execute_sequence("x", three_area_sig, rc, pk, _prop_for, feature="seqc", base=cur_c,
                                     author=True, author_proposer=_author, review=True, reviewer_proposer=_pass_reviewer)
            after = (rc / "features" / "seqc" / "sequence-plan.yaml").read_text(encoding="utf-8")
            assert "lifecycle-corrupted" in (seq_c.get("error") or "")
            assert not seq_c.get("packages")
            assert after == before
            assert seq_c.get("corrupt_sha256")

    def test_per_package_lifecycle_snapshot(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seq", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                seq = execute_sequence("большой рефактор", three_area_sig, root, pkgs, _prop_for,
                                       feature="seq", base=cur, author=True, author_proposer=_author,
                                       review=True, reviewer_proposer=_pass_reviewer)
            assert all((root / "features" / "seq" / "work-packages" / p["id"] / "run-plan.yaml").is_file()
                       for p in seq["packages"])

    def test_aggregate_ready_in_report(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seq", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                seq = execute_sequence("большой рефактор", three_area_sig, root, pkgs, _prop_for,
                                       feature="seq", base=cur, author=True, author_proposer=_author,
                                       review=True, reviewer_proposer=_pass_reviewer)
            assert "aggregate_ready" in seq

    def test_aggregate_verify_on_final_sha(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seq", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                seq = execute_sequence("большой рефактор", three_area_sig, root, pkgs, _prop_for,
                                       feature="seq", base=cur, author=True, author_proposer=_author,
                                       review=True, reviewer_proposer=_pass_reviewer)
            assert (seq.get("aggregate") or {}).get("verified") is True
            assert (seq.get("aggregate") or {}).get("final_sha") == seq["final_sha"]


# ─── sandbox inheritance ──────────────────────────────────────────────────────

@pytest.mark.unit
class TestSandboxInheritance:
    def test_sandbox_true_inherited(self):
        sig = {"task_type": "QUICK", "size": "large", "risk": "low",
               "affected_areas": ["catalog", "orders", "billing"]}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(sig, wid="seqs", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                execute_sequence("рефактор в sandbox", sig, root, pkgs, _prop_for, feature="seqs",
                                 base=cur, sandbox=True, baseline_diff=False)
            rep0 = json.loads((root / "features" / "seqs" / "work-packages" / pkgs[0]["id"] / "report.json").read_text())
            assert (rep0.get("containment") or {}).get("sandbox") is True
            assert (rep0.get("containment") or {}).get("shell_mode") == "allowlist"
