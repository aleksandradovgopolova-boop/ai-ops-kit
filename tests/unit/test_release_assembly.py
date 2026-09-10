"""Осознанная сборка релиза: по вехе/расписанию, а не реактивно.

ПОВОД (исход `releases_are_assembled_by_milestone_or_schedule_not_reactively`). `release_bump`
поднимает версию, когда решение выпускать УЖЕ принято. Само решение «что и когда собрать» было
реактивным. `release_assembly.assemble` делает его осознанным: сборка требует явного триггера (веха
ИЛИ расписание) и НАЗЫВАЕТ состав, ничего не бампая. Без триггера сборки нет.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT))

from ai_ops_kit.devtools import release_assembly as ra  # noqa: E402


def _repo(tmp_path, frags=("add-login.feat.md", "fix-crash.fix.md", "tidy.chore.md")):
    root = tmp_path / "repo"
    (root / "newsfragments").mkdir(parents=True)
    for name in frags:
        (root / "newsfragments" / name).write_text("запись\n", encoding="utf-8")
    (root / "newsfragments" / "README.md").write_text("конфиг\n", encoding="utf-8")
    return root


@pytest.mark.unit
def test_pending_fragments_group_by_category(tmp_path):
    frags = ra.pending_fragments(_repo(tmp_path))
    cats = sorted(f["category"] for f in frags)
    assert cats == ["chore", "feat", "fix"]          # README.md исключён
    assert all(f["slug"] for f in frags)


@pytest.mark.unit
def test_assembly_by_milestone_names_the_composition(tmp_path):
    res = ra.assemble(_repo(tmp_path), milestone="4.3")
    assert res["ready"] is True and res["count"] == 3
    assert res["trigger"] == "веха:4.3"
    assert set(res["by_category"]) == {"feat", "fix", "chore"}


@pytest.mark.unit
def test_assembly_by_schedule_is_a_named_trigger(tmp_path):
    res = ra.assemble(_repo(tmp_path), schedule="2026-10-01")
    assert res["ready"] is True and res["trigger"].startswith("расписание:")


@pytest.mark.unit
def test_no_trigger_is_not_ready_reactive_assembly_is_refused(tmp_path):
    res = ra.assemble(_repo(tmp_path))
    assert res["ready"] is False
    assert "триггер" in res["reason"]


@pytest.mark.unit
def test_empty_backlog_under_a_trigger_assembles_nothing(tmp_path):
    root = tmp_path / "empty"
    (root / "newsfragments").mkdir(parents=True)
    res = ra.assemble(root, milestone="4.3")
    assert res["ready"] is False and res["count"] == 0


# ── вывод целевой версии из состава (исход releases_are_assembled_…) ──

def _repo_with_version(tmp_path, version, frags):
    root = tmp_path / "repo"
    (root / "newsfragments").mkdir(parents=True)
    for name in frags:
        (root / "newsfragments" / name).write_text("запись\n", encoding="utf-8")
    (root / "VERSION").write_text(version + "\n", encoding="utf-8")
    return root


def test_next_version_levels():
    assert ra.next_version("4.2.7", "patch") == "4.2.8"
    assert ra.next_version("4.2.7", "minor") == "4.3.0"
    assert ra.next_version("4.2.7", "major") == "5.0.0"
    assert ra.next_version("4.0.0-qualification", "patch") == "4.0.1"  # pre-release-суффикс снят


def test_feat_drives_minor_others_patch():
    assert ra._bump_level({"feat": ["x"], "fix": ["y"]}) == "minor"
    assert ra._bump_level({"fix": ["y"], "chore": ["z"]}) == "patch"


def test_assemble_names_target_version(tmp_path):
    root = _repo_with_version(tmp_path, "4.2.7", ("add-login.feat.md", "fix-crash.fix.md"))
    res = ra.assemble(root, milestone="M1")
    assert res["ready"] and res["bump_level"] == "minor"
    assert res["current_version"] == "4.2.7" and res["target_version"] == "4.3.0"


def test_assemble_patch_when_no_feature(tmp_path):
    root = _repo_with_version(tmp_path, "4.2.7", ("fix-crash.fix.md", "tidy.chore.md"))
    res = ra.assemble(root, milestone="M1")
    assert res["bump_level"] == "patch" and res["target_version"] == "4.2.8"


def test_major_is_never_auto_derived(tmp_path):
    # даже с feat уровень не выше minor — мажор остаётся осознанным решением владельца
    root = _repo_with_version(tmp_path, "4.9.9", ("big.feat.md",))
    res = ra.assemble(root, milestone="M1")
    assert res["bump_level"] == "minor" and res["target_version"] == "4.10.0"
