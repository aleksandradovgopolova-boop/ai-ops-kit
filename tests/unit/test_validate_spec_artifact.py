"""Granular tests for validate_spec_artifact (migrated from selftest)."""
from __future__ import annotations

import tempfile

import pytest

from validate_spec_artifact import (  # noqa: F401
    Path,
    check,
    provided_evidence,
    render,
)


@pytest.fixture
def good_spec():
    return {
        "schema_version": 1,
        "kind": "spec-change",
        "capability": "pricing",
        "why": "нужна утилита цены",
        "what_changes": ["добавить formatPrice"],
        "tasks": ["реализовать", "покрыть тестом"],
        "requirements": [
            {
                "name": "Price formatting",
                "text": "The system SHALL format an integer price with thousand separators.",
                "scenarios": [
                    {"name": "Thousands", "when": "formatPrice(1000)", "then": "returns 1 000"}
                ],
            }
        ],
    }


@pytest.mark.unit
@pytest.mark.slow
class TestCheckSpecArtifact:
    """Validation of spec-change artifacts."""

    def test_valid_spec_change_no_errors(self, good_spec):
        assert check(good_spec) == []

    def test_valid_spec_requirements_covered(self, good_spec):
        assert provided_evidence(good_spec) == ["requirements_covered"]

    def test_bad_capability_produces_error(self, good_spec):
        assert any("capability" in e for e in check({**good_spec, "capability": "Bad Cap"}))

    def test_requirement_without_scenarios_produces_error(self, good_spec):
        assert any(
            "scenarios" in e
            for e in check({**good_spec, "requirements": [{"name": "x", "text": "SHALL y"}]})
        )

    def test_scenario_without_then_produces_error(self, good_spec):
        assert any(
            "when + then" in e
            for e in check(
                {
                    **good_spec,
                    "requirements": [
                        {"name": "x", "text": "SHALL y", "scenarios": [{"when": "a"}]}
                    ],
                }
            )
        )

    def test_invalid_spec_evidence_empty(self):
        assert provided_evidence({"kind": "spec-change"}) == []


@pytest.mark.unit
@pytest.mark.slow
class TestRenderSpecArtifact:
    """Rendering spec artifacts to OpenSpec markdown."""

    def test_render_produces_three_files(self, good_spec):
        with tempfile.TemporaryDirectory() as td:
            written = render(good_spec, Path(td) / "openspec", "feat-x")
            assert len(written) == 3

    def test_render_spec_contains_added_requirements(self, good_spec):
        with tempfile.TemporaryDirectory() as td:
            render(good_spec, Path(td) / "openspec", "feat-x")
            spec_txt = (
                Path(td) / "openspec" / "changes" / "feat-x" / "specs" / "pricing" / "spec.md"
            ).read_text(encoding="utf-8")
            assert "## ADDED Requirements" in spec_txt

    def test_render_spec_contains_requirement_and_when_then(self, good_spec):
        with tempfile.TemporaryDirectory() as td:
            render(good_spec, Path(td) / "openspec", "feat-x")
            spec_txt = (
                Path(td) / "openspec" / "changes" / "feat-x" / "specs" / "pricing" / "spec.md"
            ).read_text(encoding="utf-8")
            assert "### Requirement: Price formatting" in spec_txt
            assert "- WHEN" in spec_txt
            assert "- THEN" in spec_txt

    def test_render_proposal_contains_sections(self, good_spec):
        with tempfile.TemporaryDirectory() as td:
            render(good_spec, Path(td) / "openspec", "feat-x")
            prop = (
                Path(td) / "openspec" / "changes" / "feat-x" / "proposal.md"
            ).read_text(encoding="utf-8")
            assert "## Why" in prop
            assert "## What Changes" in prop
            assert "## Impact" in prop
