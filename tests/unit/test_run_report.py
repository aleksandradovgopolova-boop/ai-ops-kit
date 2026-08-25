"""Гранулярные тесты run_report (мигрировано из test_run_report_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import tempfile

import pytest

from run_report import (
    Path,
    build_report,
    ga,
    json,
    record_report,
    yaml,
)


@pytest.fixture
def feature_dir():
    with tempfile.TemporaryDirectory() as td:
        feats = Path(td) / "features"
        ga.cmd_new(feats, "demo-r", "Demo R")
        fdir = feats / "demo-r"
        ga.cmd_scaffold(fdir, "discovery")
        yield fdir, Path(td)


@pytest.mark.unit
class TestBuildReport:
    def test_unfilled_skeleton_is_problem(self, feature_dir):
        fdir, td = feature_dir
        r = build_report(fdir, None)
        assert r["verdict"] == "PROBLEM"

    def test_honest_discovery_not_problem(self, feature_dir):
        fdir, td = feature_dir
        for f in ("problem-statement", "hypotheses"):
            p = fdir / "discovery" / f"{f}.md"
            p.write_text(p.read_text(encoding="utf-8") + "\nсодержание\n", encoding="utf-8")
        r = build_report(fdir, None)
        assert r["verdict"] in ("OK", "WARN")

    def test_retro_not_filled_warns(self, feature_dir):
        fdir, td = feature_dir
        for f in ("problem-statement", "hypotheses"):
            p = fdir / "discovery" / f"{f}.md"
            p.write_text(p.read_text(encoding="utf-8") + "\nсодержание\n", encoding="utf-8")
        r = build_report(fdir, None)
        assert any("retrospective" in f for _, f in r["findings"])

    def test_done_skeleton_still_problem(self, feature_dir):
        fdir, td = feature_dir
        bp = yaml.safe_load((fdir / "blueprint.yaml").read_text(encoding="utf-8"))
        ga.cmd_scaffold(fdir, "definition")
        for e in bp["artifacts"]["definition"]:
            e["status"] = "done"
        bp["feature"]["current_stage"] = "definition"
        (fdir / "blueprint.yaml").write_text(yaml.safe_dump(bp, allow_unicode=True, sort_keys=False),
                                             encoding="utf-8")
        r = build_report(fdir, None)
        assert r["verdict"] == "PROBLEM"

    def test_reality_outpaced_blueprint(self, feature_dir):
        fdir, td = feature_dir
        graph = td / "knowledge" / "graph.yaml"
        graph.parent.mkdir()
        graph.write_text(yaml.safe_dump({
            "schema_version": 1, "kind": "knowledge-graph",
            "nodes": [{"id": "f1", "type": "feature",
                       "blueprint": "../features/demo-r/blueprint.yaml"},
                      {"id": "r1", "type": "release"}],
            "edges": [{"from": "f1", "type": "delivered-by", "to": "r1"}],
        }, allow_unicode=True), encoding="utf-8")
        r = build_report(fdir, graph)
        assert any("обогнала" in f for _, f in r["findings"])


@pytest.mark.unit
class TestRecordReport:
    def test_history_records(self, feature_dir):
        fdir, td = feature_dir
        r = build_report(fdir, None)
        hist = td / "hist"
        record_report(r, fdir, hist)
        record_report(r, fdir, hist)
        lines = (hist / "demo-r.jsonl").read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        assert "verdict" in json.loads(lines[0])
