"""Granular tests for validate_runtime_surface (migrated from selftest)."""
from __future__ import annotations

import tempfile

import pytest

from validate_runtime_surface import (  # noqa: F401
    PKG,
    Path,
    check_runtime_surface,
    check_skill_descriptions,
)


@pytest.fixture
def skill_tree():
    """Create a temp tree with one ok-skill and one fat-skill."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "ok-skill").mkdir()
        (root / "ok-skill" / "SKILL.md").write_text(
            "---\nname: ok\ndescription: короткое описание в бюджете\n---\n# тело", encoding="utf-8")
        (root / "fat-skill").mkdir()
        (root / "fat-skill" / "SKILL.md").write_text(
            "---\nname: fat\ndescription: " + ("очень длинное " * 40) + "\n---\n# тело", encoding="utf-8")
        yield root


@pytest.mark.unit
def test_fat_description_detected(skill_tree):
    over = check_skill_descriptions(skill_tree)
    assert any(o["skill"] == "fat-skill" for o in over)


@pytest.mark.unit
def test_short_description_passes(skill_tree):
    over = check_skill_descriptions(skill_tree)
    assert not any(o["skill"] == "ok-skill" for o in over)


@pytest.mark.unit
def test_empty_runtime_surface_is_valid():
    assert check_runtime_surface({}) == []


@pytest.mark.unit
def test_enabled_all_is_valid():
    assert check_runtime_surface({"runtime_surface": {"skills": {"enabled": "all"}}}) == []


@pytest.mark.unit
def test_enabled_list_is_valid():
    assert check_runtime_surface({"runtime_surface": {"commands": {"enabled": ["ai-run"]}}}) == []


@pytest.mark.unit
def test_enabled_number_raises():
    assert check_runtime_surface({"runtime_surface": {"skills": {"enabled": 5}}}) != []


@pytest.mark.unit
def test_all_shipped_skills_within_budget():
    real_over = check_skill_descriptions(PKG / "skills")
    assert not real_over, (
        "exceed budget: " + ", ".join(f"{o['skill']}({o['chars']})" for o in real_over)
    )
