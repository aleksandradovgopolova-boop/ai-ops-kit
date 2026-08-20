"""Тесты Delivery Health (PR-15) на фикстурах: заблокированность из плана + milestone из выгрузки."""
from __future__ import annotations

import yaml

import health_delivery as hd
from ai_ops_kit.intelligence import health_common as hc


def _plan(root, work):
    (root / "planning").mkdir(exist_ok=True)
    plan = {"schema_version": 1, "kind": "delivery-plan",
            "goals": [{"id": "g", "status": "active"}], "work": work}
    (root / hd.PLAN_REL).write_text(yaml.safe_dump(plan, allow_unicode=True), encoding="utf-8")


def _signals(root, data):
    (root / ".ai-ops").mkdir(exist_ok=True)
    (root / hd.SIGNALS_REL).write_text(yaml.safe_dump(data), encoding="utf-8")


def test_nothing_to_read_is_unknown(tmp_path):
    r = hd.delivery_health_report(tmp_path)
    assert r["band"] == hc.UNKNOWN
    assert set(r["unverified"]) == {"blocked_work", "milestone"}


def test_no_blocked_work_is_green(tmp_path):
    # A без зависимостей; B зависит от C, а C нет в плане (закрыта) -> ни одна не заблокирована
    _plan(tmp_path, [
        {"id": "A", "status": "todo"},
        {"id": "B", "status": "todo", "depends_on": ["C"]},
    ])
    sig = hd._blocked_signal(tmp_path)
    assert sig.band == hc.GREEN


def test_some_blocked_work_is_yellow(tmp_path):
    _plan(tmp_path, [
        {"id": "A", "status": "todo", "depends_on": ["B"]},  # B открыта -> A заблокирована
        {"id": "B", "status": "todo"},
    ])
    sig = hd._blocked_signal(tmp_path)
    assert sig.band == hc.YELLOW
    assert "A" in sig.reason


def test_all_blocked_work_is_red(tmp_path):
    _plan(tmp_path, [
        {"id": "A", "status": "in_progress", "depends_on": ["B"]},
        {"id": "B", "status": "todo", "depends_on": ["A"]},
    ])
    sig = hd._blocked_signal(tmp_path)
    assert sig.band == hc.RED


def test_no_open_work_is_green(tmp_path):
    _plan(tmp_path, [{"id": "A", "status": "blocked"}])  # не todo/in_progress
    sig = hd._blocked_signal(tmp_path)
    assert sig.band == hc.GREEN


def test_broken_plan_is_unknown_not_green(tmp_path):
    (tmp_path / "planning").mkdir()
    (tmp_path / hd.PLAN_REL).write_text("[]\n", encoding="utf-8")  # non-dict -> PlanCorrupt
    sig = hd._blocked_signal(tmp_path)
    assert sig.band == hc.UNKNOWN


def test_milestone_bands(tmp_path):
    _signals(tmp_path, {"milestone": {"done": 9, "total": 10}})
    assert hd._milestone_signal(tmp_path).band == hc.GREEN


def test_milestone_behind_is_red(tmp_path):
    _signals(tmp_path, {"milestone": {"done": 2, "total": 10}})
    assert hd._milestone_signal(tmp_path).band == hc.RED


def test_milestone_overdue_is_red_even_if_ahead(tmp_path):
    _signals(tmp_path, {"milestone": {"done": 9, "total": 10}, "overdue": {"count": 3}})
    sig = hd._milestone_signal(tmp_path)
    assert sig.band == hc.RED
    assert "просроч" in sig.reason


def test_milestone_zero_total_is_unknown(tmp_path):
    _signals(tmp_path, {"milestone": {"done": 0, "total": 0}})
    assert hd._milestone_signal(tmp_path).band == hc.UNKNOWN
