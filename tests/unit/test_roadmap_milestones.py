# -*- coding: utf-8 -*-
"""Цепочка направление→milestone→задачи связывается, а её разрыв виден в отчёте.

Работа `milestones-linked-to-backlog`, цель `roadmap-and-delivery` (PR-7).

Backlog не читается из GitHub: связывание строится по КОНТРАКТУ ДАННЫХ ленты 3 на фикстуре.
Три обязательных теста на capability:
  * positive     — целая цепочка направление→milestone→задачи собирается;
  * fail-closed  — разрыв цепочки (Now без milestone, висячая ссылка, сирота) назван поимённо;
  * side-effect  — «источник не подключён» ≠ «backlog пуст»: третье состояние не подменяется нулём.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[2]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))

from ai_ops_kit.planning import roadmap_manager as rm            # noqa: E402
from ai_ops_kit.planning import roadmap_milestones as ml         # noqa: E402

pytestmark = pytest.mark.unit


def _roadmap():
    plan = {
        "goals": [
            {"id": "g-now", "outcome": {"a": False}},     # Now: есть работа in_progress
            {"id": "g-now2", "outcome": {"a": False}},    # Now: без milestone/задач — разрыв
        ],
        "work": [{"id": "w", "goal": "g-now", "status": "in_progress"},
                 {"id": "w2", "goal": "g-now2", "status": "in_progress"}],
    }
    return rm.build(plan)


def _dir(rep, gid):
    return next(d for d in rep["directions"] if d["goal"] == gid)


def test_full_chain_links_direction_milestone_tasks():
    """positive: направление→milestone→задачи собирается через m.roadmap и task.milestone."""
    milestones = [{"id": "m1", "roadmap": "g-now"}]
    tasks = [
        {"id": "t1", "milestone": "m1"},                  # к направлению через milestone
        {"id": "t2", "roadmap": "g-now"},                 # к направлению напрямую
    ]
    rep = ml.link(_roadmap(), milestones, tasks)
    assert rep["connected"] is True
    d = _dir(rep, "g-now")
    assert d["milestones"] == ["m1"]
    assert set(d["tasks"]) == {"t1", "t2"}
    assert d["breaks"] == []


def test_task_pulls_milestone_into_direction():
    """milestone без явного roadmap попадает под направление через задачу с task.roadmap."""
    milestones = [{"id": "m1"}]                            # milestone не объявляет направление
    tasks = [{"id": "t1", "milestone": "m1", "roadmap": "g-now"}]
    rep = ml.link(_roadmap(), milestones, tasks)
    assert _dir(rep, "g-now")["milestones"] == ["m1"]


def test_chain_breaks_are_named():
    """fail-closed: Now без цепочки, висячая ссылка и сирота-milestone названы поимённо."""
    milestones = [{"id": "m1", "roadmap": "g-now"},
                  {"id": "m-empty", "roadmap": "g-now"}]   # привязан, но без задач
    tasks = [
        {"id": "t1", "milestone": "m1"},
        {"id": "t-bad", "roadmap": "no-such-goal"},        # висячая ссылка на направление
        {"id": "t-orphan", "milestone": "m-unknown"},      # milestone не существует
    ]
    rep = ml.link(_roadmap(), milestones, tasks)

    # g-now2 в Now, но без milestone/задач — разрыв на направлении.
    assert "g-now2" in rep["unlinked_now"]
    assert any("рвётся на направлении" in b for b in _dir(rep, "g-now2")["breaks"])

    # milestone без задач — разрыв в середине.
    assert any("без задач" in b for b in _dir(rep, "g-now")["breaks"])

    # висячая ссылка и сирота — в своих списках.
    assert any("no-such-goal" in s for s in rep["dangling_links"])
    assert any("t-orphan" in s for s in rep["orphan_tasks"])


def test_source_not_connected_is_third_state():
    """side-effect: tasks=None — «источник не подключён», а не пустой backlog."""
    rep = ml.link(_roadmap(), None, None)
    assert rep["connected"] is False
    assert rep["directions"] == []
    assert "не подключён" in rep["note"]
    # Явно НЕ то же, что подключённый пустой backlog:
    empty = ml.link(_roadmap(), [], [])
    assert empty["connected"] is True
    assert empty["unlinked_now"]          # пустой backlog -> Now-направления без цепочки


def test_missing_backlog_file_is_error(tmp_path):
    """Названный, но отсутствующий файл источника — ошибка, а не тихое «не подключено»."""
    with pytest.raises(FileNotFoundError):
        ml._load_backlog(tmp_path / "nope.yaml")
    # Не названный путь — законное третье состояние.
    assert ml._load_backlog(None) == (None, None)
