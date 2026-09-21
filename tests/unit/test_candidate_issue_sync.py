# -*- coding: utf-8 -*-
"""`candidates sync-issues`: сверка трекера с задачами-кандидатами на ФЕЙКОВОМ клиенте (без GitHub).

Ядро — чистая оркестрация: желаемое (issue-предложение на каждого открытого кандидата) сводится с
существующим через инъектируемый порт. Тесты держат порт в памяти — проверяют СОСТАВ решения, а не
сеть. Зеркалит стиль test_roadmap_issue_sync.py.

Обязательные проверки capability:
  * positive     — открытый кандидат → создаётся issue с призывом «как принять в план»;
  * fail-closed  — второй прогон подряд ничего не делает (идемпотентно); ушедший кандидат закрывается;
  * side-effect  — issue, заведённое ранее (по маркеру), усыновляется, а не дублируется;
  * dedup        — кандидат-направление по умолчанию НЕ заводится (у него уже есть эпик roadmap-sync);
  * dry-run      — apply=False не делает ни одной мутации клиента.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[2]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))

from ai_ops_kit.planning import candidate_issue_sync as s   # noqa: E402

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


def _finding(oid="obs-1", title="Разобрать наблюдение: флак в CI", rationale="тест мигает"):
    return {"id": f"cand-{oid}", "title": title, "source": "child-finding",
            "rationale": rationale}


def _direction(gid="checks-that-run", title="Декомпозировать направление: проверки"):
    return {"id": f"cand-dir-{gid}", "title": title, "source": "roadmap-direction",
            "source_goal": gid, "rationale": "направление без работ"}


# ── positive ──

def test_open_candidate_creates_issue_with_accept_call_to_action():
    c = FakeClient()
    plan = s.sync([_finding()], c, apply=True)
    assert len(plan.creates) == 1
    iss = c.list()[0]
    assert s.LABEL == "task-candidate"
    # Тело несёт маркер, призыв к приёму и явную оговорку «issue не пишет план».
    assert "<!-- candidate-sync: cand-obs-1 -->" in iss.body
    assert "candidates accept cand-obs-1" in iss.body
    assert "--goal" in iss.body                              # у находки нет направления
    assert "НЕ кладёт" in iss.body and "plan.yaml" in iss.body


# ── fail-closed: идемпотентность и закрытие ушедшего ──

def test_second_run_is_a_noop():
    c = FakeClient()
    s.sync([_finding()], c, apply=True)
    c.log.clear()
    plan2 = s.sync([_finding()], c, apply=True)
    assert plan2.in_sync, [(a.kind, a.key) for a in plan2.actions]
    assert c.log == []


def test_vanished_candidate_gets_its_issue_closed():
    c = FakeClient()
    s.sync([_finding()], c, apply=True)
    # Находка закрыта/принята — кандидата больше нет: issue закрывается.
    plan = s.sync([], c, apply=True)
    assert plan.closes, "issue ушедшего кандидата должно закрываться"
    assert all(i.state == "closed" for i in c.list())


# ── side-effect: усыновление ранее заведённого issue ──

def test_adopts_existing_issue_by_marker_without_duplicating():
    seed = [s.Issue(200, "Разобрать наблюдение: флак в CI",
                    "<!-- candidate-sync: cand-obs-1 -->\nстарое тело", "open")]
    c = FakeClient(seed)
    plan = s.sync([_finding()], c, apply=True)
    assert plan.creates == [], "усыновление не должно плодить дубли"
    # тело дрейфнуло → обновление того же номера, не новый issue
    assert {i.number for i in c.list()} == {200}
    assert any(a.kind == "update" and a.number == 200 for a in plan.actions)


# ── dedup против roadmap-sync ──

def test_roadmap_direction_candidate_is_skipped_by_default():
    # Направление уже получает эпик от roadmap-sync — candidate-sync его НЕ дублирует.
    c = FakeClient()
    plan = s.sync([_direction()], c, apply=True)
    assert plan.in_sync, "направление по умолчанию не материализуется candidate-sync"
    assert c.list() == []


def test_roadmap_direction_included_behind_seam():
    # Шов: политику можно перевернуть одним флагом (не вшитое допущение).
    c = FakeClient()
    plan = s.sync([_direction()], c, apply=True, include_roadmap_directions=True)
    assert len(plan.creates) == 1
    assert c.list()[0].body.count("candidate-sync: cand-dir-checks-that-run") == 1


def test_mixed_union_only_findings_materialize_by_default():
    c = FakeClient()
    plan = s.sync([_finding("obs-a"), _direction(), _finding("obs-b")], c, apply=True)
    assert len(plan.creates) == 2
    keys = {a.key for a in plan.creates}
    assert keys == {"cand-obs-a", "cand-obs-b"}


# ── dry-run ──

def test_dry_run_makes_no_client_mutations():
    c = FakeClient()
    plan = s.sync([_finding()], c, apply=False)
    assert not plan.in_sync            # есть что делать
    assert c.log == []                 # но клиент не тронут
    assert c.list() == []


def test_parse_key_reads_marker_only():
    assert s.parse_key(s.Issue(1, "x", "<!-- candidate-sync: cand-obs-9 -->\n...", "open")) \
        == "cand-obs-9"
    assert s.parse_key(s.Issue(2, "x", "не наше issue", "open")) is None
