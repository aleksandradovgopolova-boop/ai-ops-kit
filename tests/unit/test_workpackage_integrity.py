"""Гранулярные тесты workpackage_executor: валидация SequencePlan, write_scope, происхождение baseline.

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import contextlib
import io
import tempfile

import pytest

from ai_ops_kit.engine.workpackage_executor import (
    Path,
    _collect_base_checks_at,
    _git,
    _validate_sequence_plan_schema,
    execute_sequence,
)

from ai_ops_kit.engine import atomic_planner

from _workpackage_helpers import (
    _author,
    _mkrepo,
    _pass_reviewer,
    _prop_ws,
    _reseal,
    _valid_plan,
)


# ─── Plan integrity validation ─────────────────────────────────────────────────

@pytest.mark.unit
class TestPlanIntegrity:
    def test_valid_plan_no_error(self):
        assert _validate_sequence_plan_schema(_valid_plan(), expected_wid="seq") is None

    def test_foreign_workitem_error(self):
        result = _validate_sequence_plan_schema(_valid_plan("OTHER"), expected_wid="seq")
        assert "чужой" in (result or "")

    def test_unsupported_schema_version(self):
        result = _validate_sequence_plan_schema({**_valid_plan(), "schema_version": 2}, expected_wid="seq")
        assert "schema_version" in (result or "")

    def test_duplicate_package_id(self):
        dup = _valid_plan()
        dup["packages"][1]["id"] = "WP1"
        _reseal(dup)
        result = _validate_sequence_plan_schema(dup, expected_wid="seq")
        assert "дубли package id" in (result or "")

    def test_duplicate_order(self):
        dupord = _valid_plan()
        dupord["packages"][1]["order"] = 1
        _reseal(dupord)
        result = _validate_sequence_plan_schema(dupord, expected_wid="seq")
        assert "дубли order" in (result or "")

    def test_depends_on_nonexistent(self):
        baddep = _valid_plan()
        baddep["packages"][1]["depends_on"] = ["WP-NONE"]
        _reseal(baddep)
        result = _validate_sequence_plan_schema(baddep, expected_wid="seq")
        assert "несуществующего" in (result or "")

    def test_dependency_cycle(self):
        cyc = _valid_plan()
        cyc["packages"][0]["depends_on"] = ["WP2"]
        _reseal(cyc)
        result = _validate_sequence_plan_schema(cyc, expected_wid="seq")
        assert "цикл" in (result or "")

    def test_tampered_pkg_hash(self):
        badpk = _valid_plan()
        badpk["packages"][0]["pkg_hash"] = "0" * 16
        result = _validate_sequence_plan_schema(badpk, expected_wid="seq")
        assert "pkg_hash не сходится" in (result or "")

    def test_tampered_plan_hash(self):
        badph = _valid_plan()
        badph["plan_hash"] = "0" * 16
        result = _validate_sequence_plan_schema(badph, expected_wid="seq")
        assert "plan_hash не сходится" in (result or "")


# ─── write_scope ───────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestWriteScope:
    def test_authored_artifacts_not_scope_violation(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seq", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                seq_ws = execute_sequence("рефактор со scope", three_area_sig, root, pkgs, _prop_ws,
                                          feature="seqws", base=cur, author=True, author_proposer=_author,
                                          review=True, reviewer_proposer=_pass_reviewer,
                                          write_scope_for=lambda pkg: pkg.get("write_scope"))
            assert not any("scope-violation" in (p.get("stop_reason") or "") for p in seq_ws["packages"])


# ─── baseline provenance ───────────────────────────────────────────────────────

@pytest.mark.unit
class TestBaselineProvenance:
    def test_nonexistent_base_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _mkrepo(td)
            assert _collect_base_checks_at(root, "0" * 40, False) is None

    def test_valid_base_proven_true(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _mkrepo(td)
            res = _collect_base_checks_at(root, _git(root, "rev-parse", "HEAD")[1], False)
            assert isinstance(res, dict)
            assert res.get("proven") is True
