"""GitHub-интеграция (PR-11): разбор слага, третье состояние и нормализация — БЕЗ живого GitHub.

Всё сетевое сосредоточено в `GitHubClient._gh_api`/`._rest_get`; тесты подменяют ровно их. Ни один
тест сюда не ходит наружу — это инвариант ленты 3: тесты мокают слой интеграции.

Главное, что проверяется, — ТРЕТЬЕ СОСТОЯНИЕ: «не проверено» (`ok is False`, названа причина) — не
то же самое, что «задач нет» (`ok is True, items == []`).
"""
from __future__ import annotations

import pytest

from ai_ops_kit.integrations import github as gh


@pytest.mark.unit
@pytest.mark.parametrize("url,expected", [
    ("https://github.com/owner/repo.git", "owner/repo"),
    ("https://github.com/owner/repo", "owner/repo"),
    ("git@github.com:owner/repo.git", "owner/repo"),
    ("owner/repo", "owner/repo"),
    ("https://gitlab.com/owner/repo.git", ""),        # чужой хост — не наш source of truth
    ("", ""),
    ("not a url", ""),
])
def test_parse_slug(url, expected):
    assert gh.parse_slug(url) == expected


@pytest.mark.unit
def test_availability_third_state_no_transport(monkeypatch):
    """Нет gh и нет токена → НЕ проверено с названной причиной, а не «всё в порядке»."""
    monkeypatch.setattr(gh, "_has_gh", lambda: False)
    client = gh.GitHubClient(repo="o/r", token="")
    av = client.availability()
    assert av.ok is False
    assert "gh" in av.reason.lower() and "token" in av.reason.lower()


@pytest.mark.unit
def test_availability_no_repo():
    av = gh.GitHubClient(repo="").availability()
    assert av.ok is False
    assert "репозитор" in av.reason.lower()


@pytest.mark.unit
def test_availability_ok_with_token(monkeypatch):
    monkeypatch.setattr(gh, "_has_gh", lambda: False)
    av = gh.GitHubClient(repo="o/r", token="ghp_x").availability()
    assert av.ok is True and av.transport == "rest"


@pytest.mark.unit
def test_availability_prefers_gh(monkeypatch):
    monkeypatch.setattr(gh, "_has_gh", lambda: True)
    av = gh.GitHubClient(repo="o/r", token="ghp_x").availability()
    assert av.transport == "gh"


@pytest.mark.unit
def test_fetchresult_truthiness_distinguishes_empty_from_unavailable():
    available_empty = gh.FetchResult(True, items=[])
    unavailable = gh.FetchResult(False, reason="нет доступа")
    assert bool(available_empty) is True          # проверено, задач нет — это истина
    assert bool(unavailable) is False             # не проверено — ложь
    assert len(available_empty.items) == 0


@pytest.mark.unit
def test_next_link():
    header = ('<https://api.github.com/repositories/1/issues?page=2>; rel="next", '
              '<https://api.github.com/repositories/1/issues?page=5>; rel="last"')
    assert gh._next_link(header).endswith("page=2")
    assert gh._next_link("") == ""


@pytest.mark.unit
def test_decode_json_stream_concatenated_arrays():
    """`gh api --paginate` печатает несколько массивов подряд — склеиваем в один список."""
    text = '[{"number": 1}, {"number": 2}]\n[{"number": 3}]'
    out = gh._decode_json_stream(text)
    assert [o["number"] for o in out] == [1, 2, 3]
    assert gh._decode_json_stream("") == []


def _fake_transport(client, issues_payload):
    """Подменить транспорт клиента: и gh, и rest вернут один и тот же REST-JSON."""
    client.transport = "rest"
    client.token = "ghp_fake"
    client._rest_get = lambda path, params=None: issues_payload


@pytest.mark.unit
def test_issues_filters_pull_requests_and_normalizes(monkeypatch):
    monkeypatch.setattr(gh, "_has_gh", lambda: False)
    payload = [
        {"number": 1, "title": "баг", "state": "open",
         "labels": [{"name": "bug"}], "milestone": {"title": "v1"},
         "user": {"login": "alice"}, "html_url": "u1", "comments": 2},
        {"number": 2, "title": "это PR", "pull_request": {"url": "x"},
         "labels": [], "user": {"login": "bob"}},
    ]
    client = gh.GitHubClient(repo="o/r")
    _fake_transport(client, payload)
    res = client.issues(state="all")
    assert res.ok is True and res.source == "rest"
    assert [i["number"] for i in res.items] == [1]       # PR отфильтрован
    i = res.items[0]
    assert i["labels"] == ["bug"] and i["milestone"] == "v1" and i["author"] == "alice"
    assert i["is_pull"] is False


@pytest.mark.unit
def test_issues_unavailable_returns_reason_not_empty(monkeypatch):
    """Транспорт бросил ошибку → ok=False с причиной, а НЕ пустой список."""
    monkeypatch.setattr(gh, "_has_gh", lambda: False)
    client = gh.GitHubClient(repo="o/r", token="ghp_x")

    def boom(path, params=None):
        raise gh.GitHubError("HTTP 403 rate limit")

    client._rest_get = boom
    res = client.issues()
    assert res.ok is False
    assert "403" in res.reason
    assert res.items == []


@pytest.mark.unit
def test_labels_and_milestones_normalized(monkeypatch):
    monkeypatch.setattr(gh, "_has_gh", lambda: False)
    client = gh.GitHubClient(repo="o/r", token="ghp_x")
    client.transport = "rest"
    client._rest_get = lambda path, params=None: (
        [{"name": "bug", "color": "f00", "description": "d"}] if "labels" in path
        else [{"number": 1, "title": "v1", "state": "open", "open_issues": 3, "closed_issues": 1}]
    )
    labels = client.labels()
    assert labels.ok and labels.items[0]["name"] == "bug"
    ms = client.milestones()
    assert ms.ok and ms.items[0]["open_issues"] == 3
