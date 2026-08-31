"""Approval-gated слияние дублей backlog (вторая половина исхода duplicates_detected_and_merged).

Решение владельца (2026-08-31, вариант «одобряемое слияние»): кит СЛИВАЕТ дубли только по явно
одобренным человеком парам, никогда сам. GitHub не «сливает» Issue — закрывает ДУБЛЬ с кросс-ссылкой
на канонический (обратимо).

Мутационно (снятие поведения красит тест):
  * approval-gated — пустой/битый approved -> отказ, НИ ОДНОГО вызова записи; пары не из детектора;
  * canonical неприкосновенен — закрывается ТОЛЬКО дубль, канонический не трогается;
  * dry-run по умолчанию — без --apply ничего не пишется (executed — план, не факт);
  * fail-safe — провал комментария -> дубль НЕ закрыт (нет тихого закрытия);
  * reversible — дубль закрывается как not_planned, есть обратная reopen;
  * write-seam — все мутации github идут через единственный _gh_mutate; rest-путь для записи закрыт.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.planning import backlog_dedup as DD
from ai_ops_kit.integrations import github as GH


class _MockClient:
    """Мок GitHub-клиента: записывает вызовы записи, живого GitHub не касается."""
    def __init__(self, repo="o/r", comment_ok=True):
        self.repo = repo
        self._comment_ok = comment_ok
        self.calls = []                     # [("comment"|"close", number, extra)]

    def availability(self):
        return GH.Availability(True, transport="gh", repo=self.repo)

    def comment_issue(self, number, body):
        self.calls.append(("comment", number, body))
        return GH.WriteResult(self._comment_ok, number=number, action="comment",
                              reason="" if self._comment_ok else "mock: комментарий не оставлен")

    def close_issue(self, number, reason="not_planned"):
        self.calls.append(("close", number, reason))
        return GH.WriteResult(True, number=number, action="close")


# ── approval-gated ───────────────────────────────────────────────────────────────────────────────

def test_empty_approved_refuses_and_writes_nothing():
    client = _MockClient()
    res = DD.execute_merge(".", approved=[], client=client)
    assert res.ok is False
    assert "approved" in res.reason.lower() or "одобрен" in res.reason.lower()
    assert client.calls == []                 # НИ ОДНОГО вызова записи


def test_none_approved_refuses():
    client = _MockClient()
    res = DD.execute_merge(".", approved=None, client=client)
    assert res.ok is False and client.calls == []


def test_duplicate_equal_canonical_is_rejected():
    client = _MockClient()
    res = DD.execute_merge(".", approved=[{"duplicate": 5, "canonical": 5}], client=client)
    assert res.ok is False
    assert any("== canonical" in s["reason"] for s in res.skipped)
    assert client.calls == []


def test_non_int_pair_is_rejected():
    client = _MockClient()
    res = DD.execute_merge(".", approved=[{"duplicate": "x", "canonical": 3}], client=client)
    assert res.ok is False and client.calls == []


# ── canonical неприкосновенен; дубль закрывается ──────────────────────────────────────────────────

def test_closes_duplicate_keeps_canonical():
    client = _MockClient()
    res = DD.execute_merge(".", approved=[{"duplicate": 11, "canonical": 7}],
                           dry_run=False, by="sasha", client=client)
    assert res.ok is True and res.dry_run is False
    # закрыт ТОЛЬКО дубль #11; канонический #7 не комментировался и не закрывался.
    closed = [n for (kind, n, _x) in client.calls if kind == "close"]
    commented = [n for (kind, n, _x) in client.calls if kind == "comment"]
    assert closed == [11]
    assert commented == [11]
    assert 7 not in closed and 7 not in commented
    # кросс-ссылка на канонический — в теле комментария.
    body = next(x for (kind, n, x) in client.calls if kind == "comment")
    assert "#7" in body


def test_close_uses_not_planned_reason_reversible():
    client = _MockClient()
    DD.execute_merge(".", approved=[{"duplicate": 11, "canonical": 7}], dry_run=False, client=client)
    reason = next(x for (kind, n, x) in client.calls if kind == "close")
    assert reason == "not_planned"           # закрытие как «не будет сделано» -> обратимо reopen


# ── dry-run по умолчанию ──────────────────────────────────────────────────────────────────────────

def test_dry_run_is_default_and_writes_nothing():
    client = _MockClient()
    res = DD.execute_merge(".", approved=[{"duplicate": 11, "canonical": 7}], client=client)
    assert res.dry_run is True
    assert client.calls == []                 # без dry_run=False НИЧЕГО не пишется
    assert res.executed and res.executed[0].get("dry_run") is True


# ── fail-safe: провал комментария -> дубль НЕ закрыт ──────────────────────────────────────────────

def test_comment_failure_does_not_close_the_duplicate():
    client = _MockClient(comment_ok=False)
    res = DD.execute_merge(".", approved=[{"duplicate": 11, "canonical": 7}],
                           dry_run=False, client=client)
    closed = [n for (kind, n, _x) in client.calls if kind == "close"]
    assert closed == []                       # комментарий не удался -> НЕ закрываем
    assert any(s.get("duplicate") == 11 for s in res.skipped)
    assert res.ok is False


def test_unavailable_github_refuses_with_reason():
    class _Down(_MockClient):
        def availability(self):
            return GH.Availability(False, reason="нет доступа к GitHub")
    res = DD.execute_merge(".", approved=[{"duplicate": 11, "canonical": 7}],
                           dry_run=False, client=_Down())
    assert res.ok is False and "GitHub" in res.reason


# ── github write-seam: все мутации через _gh_mutate, rest-путь записи закрыт ───────────────────────

def test_comment_and_close_go_through_gh_mutate(monkeypatch):
    client = GH.GitHubClient(repo="o/r", transport="gh")
    seen = []
    monkeypatch.setattr(client, "_gh_mutate",
                        lambda method, path, fields=None: seen.append((method, path, fields)) or {})
    assert client.comment_issue(11, "тело").ok is True
    assert client.close_issue(11).ok is True
    methods = [(m, p) for (m, p, _f) in seen]
    assert ("POST", "repos/o/r/issues/11/comments") in methods
    assert ("PATCH", "repos/o/r/issues/11") in methods
    # закрытие несёт state=closed + state_reason
    close_fields = next(f for (m, p, f) in seen if m == "PATCH")
    assert close_fields.get("state") == "closed"


def test_write_refused_when_transport_is_not_gh():
    """Мутации разрешены только через gh: rest-токен-путь для записи закрыт (один шов)."""
    client = GH.GitHubClient(repo="o/r", transport="rest", token="x")
    r = client.comment_issue(11, "тело")
    assert r.ok is False and "gh" in r.reason.lower()


def test_reopen_exists_for_reversibility(monkeypatch):
    client = GH.GitHubClient(repo="o/r", transport="gh")
    seen = []
    monkeypatch.setattr(client, "_gh_mutate",
                        lambda method, path, fields=None: seen.append((method, path, fields)) or {})
    assert client.reopen_issue(11).ok is True
    assert seen and seen[0][2].get("state") == "open"
