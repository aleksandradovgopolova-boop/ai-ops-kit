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
