# -*- coding: utf-8 -*-
"""Backlog под milestone превращается в последовательность с прогнозом-ОЦЕНКОЙ и рисками (PR-10).

Работа `delivery-plan-with-confidence`, цель `roadmap-and-delivery`.

Backlog не читается из GitHub — план строится по контракту данных на фикстуре. Дата старта
передаётся, а не берётся из часов (иначе тест менялся бы день ото дня).

Обязательные тесты на capability:
  * positive     — выбор под milestone, топологический порядок, прогноз с датой;
  * fail-closed  — прогноз ОТКАЗЫВАЕТСЯ считать без effort/capacity, а не выдумывает дату/ноль;
  * side-effect  — риски (цикл, зависимость вне milestone, срыв срока) названы поимённо.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[2]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))

from ai_ops_kit.planning import delivery_planning as dpn   # noqa: E402

pytestmark = pytest.mark.unit


def test_selects_orders_and_forecasts():
    """positive: берём открытые задачи milestone, упорядочиваем по зависимостям, оцениваем срок."""
    tasks = [
        {"id": "a", "milestone": "m1", "effort": 2, "dependencies": ["b"]},
        {"id": "b", "milestone": "m1", "effort": 3},
        {"id": "done", "milestone": "m1", "effort": 5, "status": "closed"},
        {"id": "other", "milestone": "m2", "effort": 1},
    ]
    dp = dpn.plan(tasks, "m1", capacity=1, start="2026-08-20")
    assert "other" not in dp.sequence          # чужой milestone не берём
    assert dp.excluded_closed == ["done"]      # закрытую не планируем
    assert dp.sequence.index("b") < dp.sequence.index("a")   # b раньше a (a зависит от b)
    assert dp.forecast.available is True
    assert dp.forecast.effort_total == 5       # 2 + 3, закрытая не считается
    assert dp.forecast.days == 5               # 5 ед. / 1 в день
    assert dp.forecast.estimated_end == "2026-08-25"
    assert dp.forecast.as_dict()["kind"] == "estimate"   # это оценка, помечена как оценка
    assert dp.risks == []


def test_forecast_refuses_without_effort_or_capacity():
    """fail-closed: без effort или без capacity прогноз недоступен, а НЕ выдуманное число."""
    # effort одной задачи неизвестен -> отказ, задача названа.
    tasks = [{"id": "a", "milestone": "m1", "effort": None},
             {"id": "b", "milestone": "m1", "effort": 2}]
    dp = dpn.plan(tasks, "m1", capacity=2, start="2026-08-20")
    assert dp.forecast.available is False
    assert "effort" in dp.forecast.reason and "a" in dp.forecast.reason
    assert dp.forecast.as_dict().get("days") is None      # ноль НЕ подставлен
    assert any("прогноз недоступен" in r for r in dp.risks)

    # capacity не задана -> отказ, третье состояние (не ноль).
    tasks2 = [{"id": "a", "milestone": "m1", "effort": 2}]
    dp2 = dpn.plan(tasks2, "m1", capacity=None)
    assert dp2.forecast.available is False
    assert "capacity" in dp2.forecast.reason


def test_risks_named_cycle_outside_dep_and_overdue():
    """side-effect: цикл, зависимость вне milestone и срыв дедлайна названы поимённо."""
    # Цикл a<->b.
    cyc = [{"id": "a", "milestone": "m1", "effort": 1, "dependencies": ["b"]},
           {"id": "b", "milestone": "m1", "effort": 1, "dependencies": ["a"]}]
    dp = dpn.plan(cyc, "m1", capacity=1, start="2026-08-20")
    assert any("циклическ" in r for r in dp.risks)

    # Зависимость на задачу вне milestone.
    out = [{"id": "a", "milestone": "m1", "effort": 1, "dependencies": ["x-elsewhere"]}]
    dp2 = dpn.plan(out, "m1", capacity=1, start="2026-08-20")
    assert any("вне milestone" in r and "x-elsewhere" in r for r in dp2.risks)

    # Прогноз позже дедлайна.
    late = [{"id": "a", "milestone": "m1", "effort": 10}]
    dp3 = dpn.plan(late, "m1", capacity=1, start="2026-08-20", due="2026-08-22")
    assert any("позже дедлайна" in r for r in dp3.risks)
    # И это названо оценкой, а не фактом.
    assert any("оценка" in r for r in dp3.risks)


def test_empty_milestone_is_empty_not_error():
    """Milestone без открытых задач даёт пустую последовательность, а не падение."""
    dp = dpn.plan([], "m-empty", capacity=1, start="2026-08-20")
    assert dp.sequence == []
    assert dp.forecast.available is True and dp.forecast.days == 0


def test_missing_backlog_file_is_error(tmp_path):
    """Названный, но отсутствующий источник — ошибка, а не тихий пустой план."""
    with pytest.raises(FileNotFoundError):
        dpn._load_backlog(tmp_path / "nope.yaml")
