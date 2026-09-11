# -*- coding: utf-8 -*-
"""`roadmap sync-issues`: сверка issue-трекера с роадмапом на ФЕЙКОВОМ клиенте (без GitHub).

Ядро — чистая оркестрация: желаемое (эпик на направление + подзадача на открытую работу) сводится
с существующим через инъектируемый порт. Тесты держат порт в памяти, поэтому проверяют СОСТАВ
решения, а не сеть.

Три обязательных теста на capability (AGENTS.md):
  * positive     — из роадмапа заводятся эпики и подзадачи, эпик ссылается на подзадачи;
  * fail-closed  — второй прогон подряд ничего не делает (идемпотентность); устаревшее закрывается;
  * side-effect  — issue, заведённые ДО команды вручную, усыновляются по ключу, а не дублируются.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[2]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))

from ai_ops_kit.planning import roadmap_issue_sync as s   # noqa: E402

pytestmark = pytest.mark.unit


class FakeClient:
    """Порт трекера в памяти: держит issue, раздаёт номера, пишет действия в журнал."""

    def __init__(self, seed=None):
        self._issues = {i.number: i for i in (seed or [])}
        self._next = (max(self._issues, default=100)) + 1
        self.log = []

    def list(self):
        return list(self._issues.values())

    def create(self, title, body, labels):
        n = self._next
        self._next += 1
        self._issues[n] = s.Issue(number=n, title=title, body=body, state="open")
        self.log.append(("create", n))
        return n

    def edit(self, number, body):
        old = self._issues[number]
        self._issues[number] = s.Issue(number, old.title, body, old.state)
        self.log.append(("edit", number))

    def close(self, number):
        old = self._issues[number]
        self._issues[number] = s.Issue(number, old.title, old.body, "closed")
        self.log.append(("close", number))


def _report(now=(), next_=()):
    def block(dirs):
        out = []
        for goal, outcomes in dirs:
            out.append({"goal": goal,
                        "outcomes": [{"name": n, "reached": r} for n, r in outcomes],
                        "reached": sum(1 for _, r in outcomes if r), "total": len(outcomes)})
        return out
    return {"errors": [], "authored_present": True,
            "roadmap": {"now": block(now), "next": block(next_), "later": []}}


def _plan_items(*works):
    return [{"id": wid, "goal": goal, "status": st} for wid, goal, st in works]


# ── positive ──

def test_creates_epics_and_subtasks_and_links_them():
    rep = _report(now=[("checks-that-run", [("a", True), ("b", False)])])
    items = _plan_items(("w-types", "checks-that-run", "todo"),
                        ("w-fmt", "checks-that-run", "in_progress"),
                        ("w-done", "checks-that-run", "achieved"))  # achieved не заводится
    c = FakeClient()
    s.sync(rep, items, c, apply=True)

    titles = [i.title for i in c.list()]
    assert any(t.startswith("[roadmap:checks-that-run]") for t in titles)   # эпик
    assert sum(1 for t in titles if t.startswith("[checks-that-run]")) == 2  # две открытые работы
    # Эпик ссылается на номера подзадач (task-list → sub-issue).
    epic = next(i for i in c.list() if i.title.startswith("[roadmap:"))
    sub_nums = [i.number for i in c.list() if i.title.startswith("[checks-that-run]")]
    for n in sub_nums:
        assert f"#{n}" in epic.body
    assert "achieved" not in "".join(i.body for i in c.list())


# ── fail-closed: идемпотентность и закрытие устаревшего ──

def test_second_run_is_a_noop():
    rep = _report(now=[("green-means-checked", [("x", False)])])
    items = _plan_items(("w1", "green-means-checked", "todo"))
    c = FakeClient()
    s.sync(rep, items, c, apply=True)
    c.log.clear()
    plan2 = s.sync(rep, items, c, apply=True)
    assert plan2.in_sync, [(a.kind, a.key) for a in plan2.actions]
    assert c.log == []


def test_obsolete_issue_is_closed_when_direction_gone():
    rep = _report(now=[("green-means-checked", [("x", False)])])
    items = _plan_items(("w1", "green-means-checked", "todo"))
    c = FakeClient()
    s.sync(rep, items, c, apply=True)
    # Направление ушло из роадмапа (достигнуто/снято) — работа больше не открыта.
    empty = _report(now=[])
    plan = s.sync(empty, [], c, apply=True)
    assert plan.closes, "устаревшие issue должны закрываться"
    assert all(i.state == "closed" for i in c.list())


def test_dry_run_makes_no_changes():
    rep = _report(now=[("layering-ring-is-a-dag", [("x", False)])])
    items = _plan_items(("w1", "layering-ring-is-a-dag", "todo"))
    c = FakeClient()
    plan = s.sync(rep, items, c, apply=False)
    assert not plan.in_sync            # есть что делать
    assert c.log == []                 # но ничего не сделано
    assert c.list() == []


# ── side-effect: усыновление вручную заведённых issue ──

def test_adopts_manual_epic_and_work_without_duplicating():
    rep = _report(now=[("kit-release-strategy", [("x", False)])])
    items = _plan_items(("w-menu", "kit-release-strategy", "todo"))
    # Заведено вручную ДО команды: без HTML-ключа, но по конвенции заголовка/тела.
    seed = [
        s.Issue(743, "[roadmap:kit-release-strategy] Стратегия релизов",
                "Направление роадмапа **`kit-release-strategy`**. Готово 0 из 1.", "open"),
        s.Issue(771, "[kit-release-strategy] Собранные релизы и меню обновления",
                "Работа `w-menu` под направлением-эпиком #743.", "open"),
    ]
    c = FakeClient(seed)
    plan = s.sync(rep, items, c, apply=True)
    assert plan.creates == [], "усыновление не должно плодить дубли"
    assert {i.number for i in c.list()} == {743, 771}


def test_parse_key_reads_marker_and_legacy():
    assert s.parse_key(s.Issue(1, "x", "<!-- roadmap-sync: dir:foo -->\n...", "open")) == "dir:foo"
    assert s.parse_key(s.Issue(2, "[roadmap:foo] t", "тело", "open")) == "dir:foo"
    assert s.parse_key(s.Issue(3, "[foo] t", "Работа `w-1` под ...", "open")) == "work:foo:w-1"
    assert s.parse_key(s.Issue(4, "не наше", "просто issue", "open")) is None
