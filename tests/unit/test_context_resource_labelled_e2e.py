"""#1403: source-разметка fixture, реальные hybrid additions и writer-вход."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from qualification.context_resource.run import SCENARIOS, scenario

pytestmark = [pytest.mark.unit, pytest.mark.slow]


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    root = tmp_path_factory.mktemp("labelled-hybrid-e2e")
    return {mode: scenario(root / mode, mode) for mode in SCENARIOS}


def test_labelled_hybrid_metrics_cover_the_actual_v2_addition(runs):
    result = runs["hybrid-labelled"]
    artifact = result["context"]
    items = artifact["included_items"]
    assert {i["source"] for i in items} == {"task", "docs/needed.md", "docs/noise.md", "src/hybrid.py"}
    assert [i["source"] for i in items if i["kind"] == "hybrid"] == ["src/hybrid.py"]
    assert result["context_hybrid"]["fed_additions"] == ["src/hybrid.py"]
    metrics = artifact["metrics"]
    assert metrics["status"] == "measured"
    assert metrics["precision"] == 0.75 and metrics["miss"] == 0.25
    assert metrics["missing_relevant"] == ["docs/not-selected.md"]
    noise = next(i["tokens"] for i in items if i["source"] == "docs/noise.md")
    assert noise > 0
    assert metrics["waste"] == pytest.approx(noise / sum(i["tokens"] for i in items))
    assert 0 < metrics["waste"] < 1
    assert metrics["time_to_context_ms"] >= 0
    assert metrics["timing_scope"] == "compile_bundle + build_payload + hybrid"
    assert result["report_context_payload"]["metrics"] == metrics


def test_missing_v2_label_does_not_become_measured(runs):
    result = runs["hybrid-incomplete"]
    assert result["context_hybrid"]["fed_additions"] == ["src/hybrid.py"]
    assert result["output"] == "LOCAL_CONTEXT_1403\nHYBRID_ALLOWED_1403\n"
    metrics = result["context"]["metrics"]
    assert metrics["status"] == "incomplete_labels"
    assert metrics["unlabelled_sources"] == ["src/hybrid.py"]
    assert all(metrics[k] is None for k in ("precision", "waste", "miss"))
    assert result["report_context_payload"]["metrics"] == metrics
    assert result["compiled_payload_sha256"] == runs["hybrid-labelled"]["compiled_payload_sha256"]


def test_unlabelled_hybrid_remains_unknown(runs):
    result = runs["hybrid"]
    assert result["source_labels"] is None
    assert result["context_hybrid"]["fed_additions"] == ["src/hybrid.py"]
    assert result["context"]["metrics"]["status"] == "unknown"
    assert all(result["context"]["metrics"][k] is None for k in ("precision", "waste", "miss"))


@pytest.mark.parametrize("mode", ["hybrid-labelled", "hybrid-incomplete"])
def test_labels_are_committed_before_run_and_not_derived_from_payload(runs, mode):
    result = runs[mode]
    root = Path(result["writer_contexts_file"]).parent
    committed = subprocess.check_output(["git", "-C", str(root), "show",
        f"{result['source_revision']}:labels.json"], text=True)
    assert hashlib.sha256(committed.encode()).hexdigest() == result["labels_sha256_before_run"]
    assert committed == (root / "labels.json").read_text()
    labels = json.loads(committed)
    expected = ["task", "docs/needed.md", "docs/not-selected.md"]
    if mode == "hybrid-labelled":
        expected.append("src/hybrid.py")
    assert labels["relevant"] == expected and labels["irrelevant"] == ["docs/noise.md"]
    assert labels == result["source_labels"]
    assert "не полевая" in labels["evidence"]


@pytest.mark.parametrize("mode", ["hybrid", "hybrid-labelled", "hybrid-incomplete"])
def test_actual_writer_input_and_write_exist_without_forbidden_reads(runs, mode):
    result = runs[mode]
    contexts_file = Path(result["writer_contexts_file"])
    root = contexts_file.parent
    contexts = json.loads(contexts_file.read_text())
    assert len(contexts) == 2
    compiled = Path(result["compiled_payload_file"]).read_text()
    assert compiled.strip()
    assert compiled in contexts[0]
    assert hashlib.sha256(compiled.encode()).hexdigest() == result["compiled_payload_sha256"]
    assert "LOCAL_CONTEXT_1403" in contexts[0] and "HYBRID_ALLOWED_1403" in contexts[0]
    assert "FORBIDDEN_1403_MUST_NOT_REACH_WRITER" not in contexts[0]
    assert "Запиши ответ из docs/needed.md в src/result.txt" in compiled
    for item in result["context"]["included_items"]:
        if item["source"] != "task":
            text = (root / item["source"]).read_text()
            assert item["truncated"] is False and text in compiled
            assert item["hash"] == hashlib.sha256(text.encode()).hexdigest()[:12]
    assert hashlib.sha256(contexts_file.read_bytes()).hexdigest() == result["writer_contexts_sha256"]
    written = root / ".ai/worktrees/context-resource/src/result.txt"
    assert written.read_text() == "LOCAL_CONTEXT_1403\nHYBRID_ALLOWED_1403\n"
    assert result["loop"]["applied_writes"] == 1
    assert result["commit"]["changed_files"] == ["src/result.txt"]
    assert result["observed_source_reads"]["docs/needed.md"] > 0
    assert result["observed_source_reads"]["src/hybrid.py"] > 0
    for source in ("docs/forbidden.md", "src/denied.py", "src/sécret.py"):
        assert "FORBIDDEN_1403_MUST_NOT_REACH_WRITER" in (root / source).read_text()
    assert result["forbidden_read_calls"] == []


def test_budget_stops_the_real_pipeline_before_writer(runs):
    result = runs["over-budget"]
    assert result["overall_status"] == "blocked-preflight"
    assert result["writer_calls"] == [] and result["output"] is None
    assert not result["context"]["resource_check"]["ok"]
    root = Path(result["writer_contexts_file"]).parent
    assert json.loads((root / "writer-contexts.json").read_text()) == []
    assert not (root / ".ai/worktrees/context-resource/src/result.txt").exists()
