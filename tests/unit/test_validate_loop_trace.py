"""Granular tests for validate_loop_trace (migrated from selftest)."""
from __future__ import annotations

import pytest

from validate_loop_trace import (
    DEMO,
    SCHEMA,
    _load,
    analyze,
    check,
    json,
)


@pytest.fixture
def schema_example():
    return json.loads(SCHEMA.read_text(encoding="utf-8"))["examples"][0]


# --- Schema & analysis ---

class TestSchemaAndAnalysis:
    @pytest.mark.unit
    def test_schema_example_is_valid(self, schema_example):
        assert check(schema_example) == []

    @pytest.mark.unit
    def test_analysis_converged(self, schema_example):
        a = analyze(schema_example)
        assert a["verdict"] == "converged"
        assert a["no_progress"] is False

    @pytest.mark.slow
    @pytest.mark.unit
    def test_real_loop_trace_demo_is_consistent(self):
        if DEMO.is_dir():
            assert all(check(_load(f)) == [] for f in sorted(DEMO.glob("LT-*.yaml")))


# --- No-progress ---

class TestNoProgress:
    @pytest.fixture
    def no_progress_trace(self, schema_example):
        return {**schema_example, "id": "LT-009", "stopped_reason": "no_progress",
                "iterations": [
                    {"n": 1, "progress_value": 1, "outcome": "blocked", "signature": "a"},
                    {"n": 2, "progress_value": 1, "outcome": "blocked", "signature": "b"},
                    {"n": 3, "progress_value": 1, "outcome": "blocked", "signature": "c"}]}

    @pytest.mark.unit
    def test_no_progress_detected(self, no_progress_trace):
        a = analyze(no_progress_trace)
        assert a["no_progress"]
        assert a["verdict"] == "no_progress"

    @pytest.mark.unit
    def test_no_progress_trace_is_valid(self, no_progress_trace):
        assert check(no_progress_trace) == []

    @pytest.mark.unit
    def test_no_progress_with_success_reason_is_error(self, no_progress_trace):
        errs = check({**no_progress_trace, "stopped_reason": "success",
                       "iterations": no_progress_trace["iterations"][:-1] + [
                           {"n": 3, "progress_value": 1, "outcome": "success"}]})
        assert any("застрял" in x for x in errs)


# --- Repeated failure ---

class TestRepeatedFailure:
    @pytest.fixture
    def repeated_failure_trace(self, schema_example):
        return {**schema_example, "id": "LT-010", "stopped_reason": "repeated_failure",
                "iterations": [
                    {"n": 1, "progress_value": 2, "outcome": "blocked", "signature": "same"},
                    {"n": 2, "progress_value": 2, "outcome": "blocked", "signature": "same"}]}

    @pytest.mark.unit
    def test_repeated_failure_detected(self, repeated_failure_trace):
        assert analyze(repeated_failure_trace)["repeated_failure"] is True

    @pytest.mark.unit
    def test_repeated_failure_trace_is_valid(self, repeated_failure_trace):
        assert check(repeated_failure_trace) == []


# --- Progressing ---

class TestProgressing:
    @pytest.mark.unit
    def test_progressing_trace(self, schema_example):
        pr = {**schema_example, "id": "LT-011", "stopped_reason": "budget_exhausted",
              "iterations": [
                  {"n": 1, "progress_value": 3, "outcome": "blocked", "signature": "x"},
                  {"n": 2, "progress_value": 2, "outcome": "blocked", "signature": "y"},
                  {"n": 3, "progress_value": 1, "outcome": "blocked", "signature": "z"}]}
        assert analyze(pr)["verdict"] == "progressing"


# --- Structural errors ---

class TestStructuralErrors:
    @pytest.mark.unit
    def test_n_out_of_order(self, schema_example):
        errs = check({**schema_example, "iterations": [
            {"n": 5, "progress_value": 0, "outcome": "success"}]})
        assert any(".n должен быть" in x for x in errs)

    @pytest.mark.unit
    def test_stopped_reason_success_with_non_success_last(self, schema_example):
        errs = check({**schema_example, "iterations": [
            {"n": 1, "progress_value": 1, "outcome": "blocked", "signature": "a"}]})
        assert any("success" in x for x in errs)

    @pytest.mark.unit
    def test_broken_id(self, schema_example):
        errs = check({**schema_example, "id": "LT1"})
        assert any("id" in x for x in errs)
