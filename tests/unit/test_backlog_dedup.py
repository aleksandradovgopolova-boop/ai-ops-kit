"""Дедуп backlog (PR-8): находит близкие пары и устаревшие — и только ПРЕДЛАГАЕТ (PR-19/20).

Дедуп не сливает молча: `action == "suggest_merge"`, слияние требует одобрения. Каждая пара несёт
объяснение (общие слова/метки). Устаревание детерминировано: опорная дата задаётся, к часам тест не
обращается. Живого GitHub нет.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.planning import backlog_dedup as dd


def _issue(number, title="", body="", labels=None, updated_at=""):
    return {"number": number, "title": title, "body": body,
            "labels": labels or [], "updated_at": updated_at}


@pytest.mark.unit
def test_finds_near_identical_titles():
    items = [
        _issue(1, "экспорт заказов падает на пустом фильтре", labels=["bug"]),
        _issue(2, "экспорт заказов падает при пустом фильтре", labels=["bug"]),
        _issue(3, "совершенно другая задача про роадмап"),
    ]
    pairs = dd.find_duplicates(items, threshold=0.5)
    assert len(pairs) == 1
    p = pairs[0]
    assert {p.a, p.b} == {1, 2}
    assert "экспорт" in p.shared_title_words
    assert p.action == "suggest_merge"                 # только предложение
    assert "одобрения" in p.suggestion


@pytest.mark.unit
def test_no_false_pair_for_distinct_issues():
    items = [_issue(1, "экспорт заказов в csv"), _issue(2, "настроить пайплайн деплоя")]
    assert dd.find_duplicates(items, threshold=0.5) == []


@pytest.mark.unit
def test_pairs_sorted_by_score_desc():
    items = [
        _issue(1, "кэш пользователей истекает слишком рано"),
        _issue(2, "кэш пользователей истекает слишком рано совсем"),
        _issue(3, "кэш пользователей"),
    ]
    pairs = dd.find_duplicates(items, threshold=0.3)
    scores = [p.score for p in pairs]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.unit
def test_stale_by_reference_date():
    items = [
        _issue(1, "свежая", updated_at="2026-08-19T00:00:00Z"),
        _issue(2, "старая", updated_at="2026-01-01T00:00:00Z"),
        _issue(3, "без даты"),
    ]
    stale = dd.find_stale(items, stale_days=120, now_iso="2026-08-20T00:00:00Z")
    assert [s.number for s in stale] == [2]
    assert stale[0].days_idle > 120
    assert "предложить" in stale[0].reason.lower()


@pytest.mark.unit
def test_stale_reference_defaults_to_latest_update():
    """Без now_iso опорная дата — самый свежий updated_at (детерминизм без часов)."""
    items = [
        _issue(1, "новейшая", updated_at="2026-08-20T00:00:00Z"),
        _issue(2, "старая", updated_at="2026-02-01T00:00:00Z"),
    ]
    stale = dd.find_stale(items, stale_days=120)
    assert [s.number for s in stale] == [2]


class _FakeClient:
    def __init__(self, res):
        self._res = res
        self.repo = "o/r"

    def issues(self, state="open"):
        return self._res


@pytest.mark.unit
def test_dedup_backlog_unavailable_is_not_empty():
    from ai_ops_kit.integrations.github import FetchResult
    rep = dd.dedup_backlog(client=_FakeClient(FetchResult(False, reason="нет токена")))
    assert rep.ok is False and "нет токена" in rep.reason
    assert rep.duplicate_pairs == [] and rep.stale == []


@pytest.mark.unit
def test_dedup_backlog_end_to_end_suggests():
    from ai_ops_kit.integrations.github import FetchResult
    items = [
        _issue(1, "таймаут при загрузке отчёта", labels=["bug"], updated_at="2026-08-20T00:00:00Z"),
        _issue(2, "таймаут при загрузке отчёта", labels=["bug"], updated_at="2026-08-20T00:00:00Z"),
    ]
    rep = dd.dedup_backlog(client=_FakeClient(FetchResult(True, items=items, source="gh")),
                           threshold=0.5, now_iso="2026-08-20T00:00:00Z")
    assert rep.ok and rep.total == 2
    assert len(rep.duplicate_pairs) == 1
    assert rep.duplicate_pairs[0].action == "suggest_merge"
