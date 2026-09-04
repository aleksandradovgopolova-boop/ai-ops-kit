"""Гранулярные тесты workpackage_executor: resume — обнаружение дрейфа плана.

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
)

from ai_ops_kit.engine import atomic_planner

from _workpackage_helpers import (
    _author,
    _mkrepo,
    _pass_reviewer,
    _prop_for,
)


# ─── Resume: дрейф плана ─────────────────────────────────────────────────────────

@pytest.mark.unit
class TestResumeDrift:
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
