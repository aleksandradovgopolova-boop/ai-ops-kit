"""Granular tests for validate_references (migrated from selftest)."""
from __future__ import annotations

import pytest

from validate_references import (  # noqa: F401
    PKG,
    Path,
    check,
    tempfile,
)


@pytest.mark.unit
def test_real_package_has_no_dangling_references():
    assert check(PKG) == []


@pytest.fixture
def broken_tree_findings():
    """Create an artificial broken tree and return the findings list."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "registry").mkdir(parents=True)
        (root / "quality").mkdir()
        (root / "manifest").mkdir()
        (root / "rules").mkdir()
        (root / "skills").mkdir()
        (root / "registry" / "agents.yaml").write_text(
            "agents:\n  - id: real-agent\n", encoding="utf-8")
        (root / "quality" / "gates.yaml").write_text(
            "gates:\n  real_gate: {id: real_gate}\n", encoding="utf-8")
        (root / "manifest" / "ai-ops-manifest.yaml").write_text(
            "skills:\n  shipped:\n    - id: real-skill\n      path: skills/real-skill/SKILL.md\n"
            "update_policy:\n  updater: installer/does_not_exist.py\n",
            encoding="utf-8")
        (root / "skills" / "real-skill").mkdir()
        (root / "skills" / "real-skill" / "SKILL.md").write_text(
            "---\nname: real-skill\nchecklist: rules/missing.yaml\n---\n", encoding="utf-8")
        (root / "registry" / "workflows.yaml").write_text(
            "workflows:\n"
            "  W:\n"
            "    quality_gates: [ghost_gate]\n"
            "    stages:\n"
            "      - {id: s1, owner: ghost-agent, uses_skills: [ghost-skill]}\n",
            encoding="utf-8")
        yield check(root)


@pytest.mark.unit
def test_detects_nonexistent_gate(broken_tree_findings):
    kinds = {x["kind"] for x in broken_tree_findings}
    assert "gate" in kinds


@pytest.mark.unit
def test_detects_nonexistent_agent(broken_tree_findings):
    kinds = {x["kind"] for x in broken_tree_findings}
    assert "agent" in kinds


@pytest.mark.unit
def test_detects_nonexistent_skill(broken_tree_findings):
    kinds = {x["kind"] for x in broken_tree_findings}
    assert "skill" in kinds


@pytest.mark.unit
def test_detects_broken_checklist_path(broken_tree_findings):
    kinds = {x["kind"] for x in broken_tree_findings}
    assert "path" in kinds


@pytest.mark.unit
def test_deep_research_external_not_falsely_broken(broken_tree_findings):
    assert all(x["ref"] != "deep-research" for x in broken_tree_findings)


@pytest.mark.unit
def test_detects_stale_manifest_path(broken_tree_findings):
    kinds = {x["kind"] for x in broken_tree_findings}
    assert "manifest-path" in kinds
