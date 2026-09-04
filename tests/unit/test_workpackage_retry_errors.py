"""Гранулярные тесты workpackage_executor: retry_package — ветки ошибок (неизвестный пакет, дрейф базы).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import contextlib
import io
import tempfile

import pytest

from ai_ops_kit.engine.workpackage_executor import (
    Path,
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


# ─── retry_package: ветки ошибок ─────────────────────────────────────────────────

@pytest.mark.unit
class TestRetryPackageErrors:
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
