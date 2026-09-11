"""Гранулярные тесты run_report (мигрировано из test_run_report_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import tempfile

import pytest

from ai_ops_kit.lifecycle.run_report import (
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
    def test_run_is_written_as_its_own_shard(self, feature_dir):
        """Прогон = отдельный файл report-history/<feature>/<run-id>.jsonl, одна строка."""
        fdir, td = feature_dir
        r = build_report(fdir, None)
        hist = td / "hist"
        out = record_report(r, fdir, hist)
        assert out.parent == hist / "demo-r", out
        assert out.suffix == ".jsonl"
        lines = out.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        assert "verdict" in json.loads(lines[0])

    def test_parallel_runs_write_different_files(self, feature_dir):
        """#148: два прогона пишут в РАЗНЫЕ шарды (нет общего append-файла -> нет merge-конфликта)."""
        fdir, td = feature_dir
        r = build_report(fdir, None)
        hist = td / "hist"
        a = record_report(r, fdir, hist)
        b = record_report(r, fdir, hist)
        assert a != b, "два прогона писали в один файл — вернулся known-conflict #148"
        shards = sorted((hist / "demo-r").glob("*.jsonl"))
        assert len(shards) == 2

    def test_effect_metrics_aggregates_shards(self, feature_dir):
        """Читатель агрегирует все шарды каталога фичи в одну историю."""
        from ai_ops_kit.intelligence import effect_metrics

        fdir, td = feature_dir
        r = build_report(fdir, None)
        hist = td / "hist"
        record_report(r, fdir, hist)
        record_report(r, fdir, hist)
        record_report(r, fdir, hist)
        metrics = effect_metrics.build(hist)
        assert metrics["per_feature"]["demo-r"]["runs"] == 3

    def test_legacy_flat_file_and_shards_read_together(self, feature_dir):
        """Обратная совместимость: старый плоский <feature>.jsonl читается вместе с шардами."""
        from ai_ops_kit.intelligence import effect_metrics

        fdir, td = feature_dir
        r = build_report(fdir, None)
        hist = td / "hist"
        hist.mkdir(parents=True, exist_ok=True)
        # старый плоский append-файл дочки (два среза)
        legacy = {"schema_version": 1, "ts": "2026-08-01T10:00:00+00:00", "feature": "demo-r",
                  "verdict": "OK", "current_stage": "discovery",
                  "coverage": {"filled": 1}, "problems": 0, "warns": 0}
        legacy2 = {**legacy, "ts": "2026-08-01T11:00:00+00:00", "verdict": "PROBLEM"}
        (hist / "demo-r.jsonl").write_text(
            json.dumps(legacy, ensure_ascii=False) + "\n"
            + json.dumps(legacy2, ensure_ascii=False) + "\n", encoding="utf-8")
        # плюс один новый шард
        record_report(r, fdir, hist)
        metrics = effect_metrics.build(hist)
        assert metrics["per_feature"]["demo-r"]["runs"] == 3, "плоский файл или шард потерян при чтении"
