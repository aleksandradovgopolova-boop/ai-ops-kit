"""Гранулярные тесты generate_artifacts (мигрировано из test_generate_artifacts_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import tempfile

import pytest

from ai_ops_kit.shared.generate_artifacts import (
    Path,
    cmd_add,
    cmd_check,
    cmd_new,
    cmd_scaffold,
)


@pytest.fixture
def feature_dir():
    with tempfile.TemporaryDirectory() as td:
        feats = Path(td) / "features"
        cmd_new(feats, "demo-x", "Demo X")
        yield feats / "demo-x"


@pytest.mark.unit
class TestCmdNew:
    def test_creates_blueprint(self, tmp_path):
        feats = tmp_path / "features"
        assert cmd_new(feats, "demo-x", "Demo X") == 0


@pytest.mark.unit
class TestCmdScaffold:
    def test_discovery(self, feature_dir):
        assert cmd_scaffold(feature_dir, "discovery") == 0

    def test_problem_statement_created(self, feature_dir):
        cmd_scaffold(feature_dir, "discovery")
        ps = feature_dir / "discovery" / "problem-statement.md"
        assert ps.exists()


@pytest.mark.unit
class TestCmdCheck:
    def test_empty_skeletons_detected(self, feature_dir):
        cmd_scaffold(feature_dir, "discovery")
        assert cmd_check(feature_dir) == 1

    def test_filled_passes(self, feature_dir):
        cmd_scaffold(feature_dir, "discovery")
        ps = feature_dir / "discovery" / "problem-statement.md"
        ps.write_text(ps.read_text(encoding="utf-8") + "\nНастоящее содержание.\n", encoding="utf-8")
        hyp = feature_dir / "discovery" / "hypotheses.md"
        hyp.write_text(hyp.read_text(encoding="utf-8") + "\nH1.\n", encoding="utf-8")
        assert cmd_check(feature_dir) == 0


@pytest.mark.unit
class TestScaffoldIdempotent:
    def test_does_not_overwrite(self, feature_dir):
        cmd_scaffold(feature_dir, "discovery")
        ps = feature_dir / "discovery" / "problem-statement.md"
        ps.write_text(ps.read_text(encoding="utf-8") + "\nНастоящее содержание.\n", encoding="utf-8")
        cmd_scaffold(feature_dir, "discovery")
        assert "Настоящее содержание." in ps.read_text(encoding="utf-8")


@pytest.mark.unit
class TestCmdAdd:
    def test_add_experiment(self, feature_dir):
        cmd_scaffold(feature_dir, "discovery")
        assert cmd_add(feature_dir, "discovery", "experiments/exp-1.md",
                       "templates/product/Experiment.md") == 0

    def test_experiment_file_created(self, feature_dir):
        cmd_scaffold(feature_dir, "discovery")
        cmd_add(feature_dir, "discovery", "experiments/exp-1.md",
                "templates/product/Experiment.md")
        assert (feature_dir / "experiments" / "exp-1.md").exists()
