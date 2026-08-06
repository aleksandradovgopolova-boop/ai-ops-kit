"""Unit tests for tools/bench_lite.py — the offline golden benchmark corpus.

Tests the corpus structure, case classification, scaffold, and report schema.
Avoids running the full bench (slow) — focuses on structural invariants.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT / "tools"))

import bench_lite as bl


@pytest.mark.unit
class TestCorpusStructure:
    """Tests for _cases() — the golden corpus must be well-formed."""

    def test_load_corpus_returns_list(self):
        cases = bl._cases()
        assert isinstance(cases, list)
        assert len(cases) >= 4  # at least quick_clean, review_blocks, fixloop, rubber_stamp

    def test_corpus_entries_have_required_fields(self):
        cases = bl._cases()
        for case in cases:
            assert "id" in case, f"case missing 'id': {case}"
            assert "tags" in case, f"case missing 'tags': {case}"
            assert "build" in case, f"case missing 'build': {case}"
            assert "expected" in case, f"case missing 'expected': {case}"
            assert callable(case["build"]), f"case 'build' not callable: {case['id']}"

    def test_corpus_entries_have_expected_ready_field(self):
        cases = bl._cases()
        for case in cases:
            exp = case["expected"]
            assert "ready" in exp, f"case {case['id']} expected missing 'ready'"
            assert "unmet_includes" in exp, f"case {case['id']} expected missing 'unmet_includes'"

    def test_corpus_ids_are_unique(self):
        cases = bl._cases()
        ids = [c["id"] for c in cases]
        assert len(ids) == len(set(ids)), f"Duplicate case IDs found: {[x for x in ids if ids.count(x) > 1]}"

    def test_corpus_has_safety_cases(self):
        cases = bl._cases()
        safety = [c for c in cases if c.get("category") == "safety"]
        assert len(safety) >= 1, "Corpus must have at least one safety case"

    def test_corpus_has_known_good_cases(self):
        cases = bl._cases()
        kg = [c for c in cases if c.get("category") == "known_good"]
        assert len(kg) >= 5, "Corpus must have multiple known_good cases"


@pytest.mark.unit
class TestClassify:
    """Tests for _classify() — case outcome classification."""

    def test_ok_when_expected_and_actual_match(self):
        expected = {"ready": True, "unmet_includes": []}
        actual = {"ready_for_pr": True, "unmet": []}
        assert bl._classify(expected, actual) == "ok"

    def test_false_fail_when_expected_ready_but_not_actual(self):
        expected = {"ready": True, "unmet_includes": []}
        actual = {"ready_for_pr": False, "unmet": ["ux_review"]}
        assert bl._classify(expected, actual) == "false_fail"

    def test_false_green_when_expected_blocked_but_actual_ready(self):
        expected = {"ready": False, "unmet_includes": ["ux_review"]}
        actual = {"ready_for_pr": True, "unmet": []}
        assert bl._classify(expected, actual) == "false_green"

    def test_mismatch_when_ready_matches_but_gates_differ(self):
        expected = {"ready": False, "unmet_includes": ["ux_review"]}
        actual = {"ready_for_pr": False, "unmet": ["visual_regression"]}
        assert bl._classify(expected, actual) == "mismatch"

    def test_ok_when_both_blocked_same_gate(self):
        expected = {"ready": False, "unmet_includes": ["ux_review"]}
        actual = {"ready_for_pr": False, "unmet": ["ux_review"]}
        assert bl._classify(expected, actual) == "ok"


@pytest.mark.unit
class TestScaffold:
    """Tests for _scaffold() — minimal git repo creation."""

    def test_scaffold_creates_git_repo(self, tmp_path):
        branch = bl._scaffold(tmp_path)
        assert (tmp_path / ".git").is_dir()
        assert (tmp_path / "pyproject.toml").is_file()
        assert (tmp_path / "seed").is_file()
        assert branch  # non-empty branch name

    def test_scaffold_has_clean_status(self, tmp_path):
        bl._scaffold(tmp_path)
        result = subprocess.run(
            ["git", "-C", str(tmp_path), "status", "--porcelain"],
            capture_output=True, text=True)
        assert result.stdout.strip() == ""


@pytest.mark.unit
class TestBenchVersion:
    """Tests for bench version constant."""

    def test_bench_version_is_string(self):
        assert isinstance(bl.BENCH_VERSION, str)
        assert bl.BENCH_VERSION


@pytest.mark.unit
class TestReviewers:
    """Tests for the scripted reviewer factories."""

    def test_pass_reviewer_reads_then_passes(self):
        rev = bl._pass_reviewer("src/foo.py")
        # First call: should request read
        result1 = rev("some prompt without marker")
        assert '"op": "read"' in result1 or '"op":"read"' in result1
        # Second call with marker: should pass
        result2 = rev("prompt --- src/foo.py ---")
        assert '"status":"pass"' in result2 or '"status": "pass"' in result2

    def test_rubber_reviewer_passes_without_reading(self):
        rev = bl._rubber_reviewer()
        result = rev("any prompt")
        assert '"status":"pass"' in result or '"status": "pass"' in result

    def test_fail_reviewer_fails_after_reading(self):
        rev = bl._fail_reviewer("src/bar.py", ["missing tests"])
        result = rev("prompt --- src/bar.py ---")
        assert '"status":"fail"' in result or '"status": "fail"' in result
