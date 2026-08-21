# -*- coding: utf-8 -*-
"""Ранние блокеры находятся по графу зависимостей; сигналы delivery — в форме ленты 5 (PR-15).

Работа `blockers-detected-early`, цель `roadmap-and-delivery`.

Границы: band Green/Yellow/Red считает лента 5; здесь — производитель сигналов и поиск блокеров.
Дата «сегодня» передаётся, не берётся из часов.

Обязательные тесты на capability:
  * positive     — блокер, держащий больше всего работы, наверху; сигналы в форме health_delivery;
  * fail-closed  — просрочка без даты/‌due НЕ выдаётся числом (третье состояние), а не 0;
  * side-effect  — транзитивная зависимость учтена, закрытые задачи блокером не считаются.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

KIT = Path(__file__).resolve().parents[2]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))

from ai_ops_kit.planning import delivery_planning_blockers as bl   # noqa: E402

pytestmark = pytest.mark.unit


def test_early_blockers_ranked_by_downstream():
    """positive: задача, держащая больше открытой работы, стоит выше; транзитивность учтена."""
    tasks = [
        {"id": "root", "milestone": "m1"},                              # держит b и c (через b)
        {"id": "b", "milestone": "m1", "dependencies": ["root"]},
        {"id": "c", "milestone": "m1", "dependencies": ["b"]},
        {"id": "leaf", "milestone": "m1", "dependencies": ["root"]},
        {"id": "lonely", "milestone": "m1"},                            # никого не держит
    ]
    blockers = bl.early_blockers(tasks)
    ids = [b["id"] for b in blockers]
    assert ids[0] == "root"                          # держит больше всех
    assert "lonely" not in ids                       # никого не держит — не блокер
    root = blockers[0]
    assert set(root["blocks"]) == {"b", "c", "leaf"}  # транзитивно: c через b
    assert root["downstream"] == 3


def test_closed_tasks_are_not_blockers_and_free_downstream():
    """side-effect: закрытая задача блокером не считается, и её зависимые больше её не ждут."""
    tasks = [
        {"id": "done-dep", "milestone": "m1", "status": "closed"},
        {"id": "x", "milestone": "m1", "dependencies": ["done-dep"]},
    ]
    blockers = bl.early_blockers(tasks)
    assert blockers == []                            # done-dep закрыта, x её не ждёт как открытую


def test_overdue_unknown_is_not_zero():
    """fail-closed: без даты 'сегодня' или due просрочка — третье состояние, не число."""
    tasks = [{"id": "a", "milestone": "m1"},
             {"id": "b", "milestone": "m1", "dependencies": ["a"]}]
    # today не передан -> overdue у блокера None (не False и не выдумка).
    blockers = bl.early_blockers(tasks)
    assert blockers[0]["overdue"] is None

    # Сигналы: просрочку не выдаём числом, а называем недоступной.
    sig = bl.delivery_signals(tasks, "m1", today=None)
    assert "overdue" not in sig
    assert "overdue_unavailable" in sig


def test_overdue_counted_when_dates_present():
    """С датой 'сегодня' и due просрочка считается и попадает в сигналы."""
    tasks = [{"id": "late", "milestone": "m1", "due": "2026-08-10"},
             {"id": "ok", "milestone": "m1", "due": "2026-09-01"}]
    sig = bl.delivery_signals(tasks, "m1", today="2026-08-20")
    assert sig["overdue"]["count"] == 1
    assert sig["overdue"]["ids"] == ["late"]


def test_signals_shape_matches_lane5_contract():
    """positive: выгрузка несёт milestone.done/total — то, что читает health_delivery ленты 5."""
    tasks = [
        {"id": "a", "milestone": "m1", "status": "closed", "closed_at": "2026-08-19"},
        {"id": "b", "milestone": "m1"},
        {"id": "c", "milestone": "m1", "dependencies": ["b"]},
        {"id": "other", "milestone": "m2"},
    ]
    sig = bl.delivery_signals(tasks, "m1", today="2026-08-20")
    assert sig["milestone"] == {"done": 1, "total": 3}   # other из m2 не считается
    assert sig["blocked"]["count"] == 1 and sig["blocked"]["ids"] == ["c"]
    assert sig["velocity"]["closed_with_date"] == 1


def test_write_signals_roundtrips(tmp_path):
    """emit пишет .ai-ops/delivery-signals.yaml, который разбирается как ждёт лента 5."""
    tasks = [{"id": "a", "milestone": "m1"}, {"id": "b", "milestone": "m1", "status": "closed"}]
    path = bl.write_signals(tmp_path, tasks, "m1", today="2026-08-20")
    assert path == tmp_path / ".ai-ops" / "delivery-signals.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["milestone"] == {"done": 1, "total": 2}


def test_missing_backlog_file_is_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        bl._load_tasks(tmp_path / "nope.yaml")
