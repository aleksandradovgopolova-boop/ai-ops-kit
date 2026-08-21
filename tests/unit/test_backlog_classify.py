"""Классификация backlog (PR-8): вывод типа/области/приоритета и ОБЪЯСНИМОСТЬ каждого вывода.

Как судейский вердикт — вывод без основания непроверяем. Каждый тест проверяет не только результат,
но и что в `evidence` назван сигнал, который его дал. Живого GitHub нет: классификатор работает над
нормализованными dict'ами, а `classify_backlog` мокает клиент.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.planning import backlog_classify as bc


def _issue(number=1, title="", body="", labels=None, state="open", milestone=None):
    return {"number": number, "title": title, "body": body, "labels": labels or [],
            "state": state, "milestone": milestone, "url": f"u{number}"}


@pytest.mark.unit
def test_type_from_label_beats_title():
    """Метка — сильнейший сигнал: 'bug' побеждает даже фича-слова в заголовке."""
    c = bc.classify_issue(_issue(title="добавить поддержку X", labels=["bug"]))
    assert c.type == "bug"
    assert "метка" in c.evidence["type"] and c.confidence == "high"


@pytest.mark.unit
@pytest.mark.parametrize("title,expected", [
    ("main() падает на длинном аргументе", "bug"),
    ("исследовать гипотезу про кэш", "research"),
    ("рефакторинг слоя providers, техдолг", "tech-debt"),
    ("починить CI workflow деплоя", "infrastructure"),
    ("добавить экспорт заказов", "feature"),
])
def test_type_from_title(title, expected):
    c = bc.classify_issue(_issue(title=title))
    assert c.type == expected
    assert "заголовк" in c.evidence["type"]


@pytest.mark.unit
def test_type_default_is_low_confidence():
    c = bc.classify_issue(_issue(title="Культура разработки в команде"))
    assert c.type == "feature" and c.confidence == "low"
    assert "дефолт" in c.evidence["type"]


@pytest.mark.unit
def test_priority_from_label_else_unset():
    hi = bc.classify_issue(_issue(labels=["priority: high"]))
    assert hi.priority == "high" and "метка" in hi.evidence["priority"]
    crit = bc.classify_issue(_issue(labels=["P0"]))
    assert crit.priority == "critical"
    none = bc.classify_issue(_issue(labels=["bug"]))
    assert none.priority == "unset" and "PR-9" in none.evidence["priority"]


@pytest.mark.unit
def test_area_from_label_and_body_path():
    lbl = bc.classify_issue(_issue(labels=["area:providers"]))
    assert lbl.area == "providers" and "метка области" in lbl.evidence["area"]
    path = bc.classify_issue(_issue(body="ошибка в `ai_ops_kit/planning/roadmap.py`"))
    assert path.area == "ai_ops_kit"
    none = bc.classify_issue(_issue(title="без пути и меток"))
    assert none.area == "unknown"


@pytest.mark.unit
def test_dependencies_vs_bare_references():
    """«blocked by #7» — зависимость; голая ссылка #3 — только reference, не зависимость."""
    c = bc.classify_issue(_issue(body="blocked by #7, связано с #3"))
    assert c.dependencies == [7]
    assert c.references == [3]
    assert "#7" in c.evidence["dependencies"]


@pytest.mark.unit
def test_strategic_alignment_is_honest_unknown():
    """Без источника стратегии — unknown, а не выдуманное 'средне'."""
    c = bc.classify_issue(_issue(title="что угодно"))
    assert c.strategic_alignment == "unknown"
    assert "не оцениваем" in c.evidence["strategic_alignment"]


@pytest.mark.unit
def test_impact_urgency_effort_unknown_without_signal():
    c = bc.classify_issue(_issue(title="обычная задача"))
    assert c.impact == "unknown" and c.urgency == "unknown" and c.effort == "unknown"
    crit = bc.classify_issue(_issue(labels=["critical"]))
    assert crit.impact == "high" and crit.urgency == "high"


class _FakeClient:
    def __init__(self, res):
        self._res = res
        self.repo = "o/r"

    def issues(self, state="open"):
        return self._res


@pytest.mark.unit
def test_classify_backlog_counts_by_type():
    from ai_ops_kit.integrations.github import FetchResult
    items = [_issue(1, labels=["bug"]), _issue(2, title="добавить X"),
             _issue(3, title="починить деплой CI")]
    rep = bc.classify_backlog(client=_FakeClient(FetchResult(True, items=items, source="gh")))
    assert rep.ok and rep.total == 3
    assert rep.by_type == {"bug": 1, "feature": 1, "infrastructure": 1}


@pytest.mark.unit
def test_classify_backlog_unavailable_is_not_empty():
    """GitHub недоступен → ok=False с причиной, а не «0 задач»."""
    from ai_ops_kit.integrations.github import FetchResult
    rep = bc.classify_backlog(client=_FakeClient(FetchResult(False, reason="нет доступа: gh не найден")))
    assert rep.ok is False
    assert "нет доступа" in rep.reason
    assert rep.items == [] and rep.total == 0
