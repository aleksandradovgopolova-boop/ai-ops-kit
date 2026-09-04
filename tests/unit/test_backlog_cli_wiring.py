"""`ai-ops backlog <sub>` доходит до обработчика и исполняется, а не печатает заглушку с кодом 0.

Тот же класс отказа, что ловил `session` (лента A, 19.08): интент объявлен, обработчик написан, а до
него не доходит. Здесь проверяется весь путь: разбор argv -> DIRECT_INTENTS -> _run_intent ->
_run_backlog. Живого GitHub нет — мокаем `integrations.github.make_client`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]

from ai_ops_kit.cli import ai_ops_cli # noqa: E402
from ai_ops_kit.integrations import github as gh  # noqa: E402


class _FakeClient:
    def __init__(self, res):
        self._res = res
        self.repo = "o/r"

    def issues(self, state="open"):
        return self._res


def _fake_issue(number, title="", labels=None, body="", state="open"):
    return {"number": number, "title": title, "labels": labels or [], "body": body,
            "state": state, "milestone": None, "url": f"u{number}"}


@pytest.fixture
def with_issues(monkeypatch):
    def _install(items):
        res = gh.FetchResult(True, items=items, source="gh")
        monkeypatch.setattr(gh, "make_client", lambda *a, **k: _FakeClient(res))
    return _install


@pytest.fixture
def unavailable(monkeypatch):
    res = gh.FetchResult(False, reason="нет доступа: gh не найден и не задан токен")
    monkeypatch.setattr(gh, "make_client", lambda *a, **k: _FakeClient(res))


@pytest.mark.unit
def test_backlog_is_a_direct_intent():
    assert "backlog" in ai_ops_cli.DIRECT_INTENTS
    assert "backlog" in ai_ops_cli.INTENTS


@pytest.mark.unit
@pytest.mark.parametrize("sub", ["classify", "dedup", "prioritize", "graph"])
def test_each_sub_reaches_handler_and_returns_zero(sub, with_issues, capsys, tmp_path):
    with_issues([_fake_issue(1, "баг падает", labels=["bug"]),
                 _fake_issue(2, "добавить экспорт")])
    rc = ai_ops_cli.main(["backlog", sub, str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.strip() and "Выполню намерение" not in out    # не заглушка превью


@pytest.mark.unit
def test_graph_alias_deps(with_issues, tmp_path):
    with_issues([_fake_issue(1, "a"), _fake_issue(2, "b")])
    assert ai_ops_cli.main(["backlog", "deps", str(tmp_path)]) == 0


@pytest.mark.unit
def test_unavailable_is_blocked_not_empty_success(unavailable, capsys, tmp_path):
    rc = ai_ops_cli.main(["backlog", "classify", str(tmp_path)])
    assert rc == 2                                            # не исполнено (блокировано)
    assert "не проверен" in capsys.readouterr().out


@pytest.mark.unit
def test_no_subcommand_lists_options_rc_zero(capsys, tmp_path):
    rc = ai_ops_cli.main(["backlog", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    for sub in ("classify", "dedup", "prioritize", "graph"):
        assert sub in out


@pytest.mark.unit
def test_unknown_subcommand_is_rejected(capsys, tmp_path):
    rc = ai_ops_cli.main(["backlog", "bogus", str(tmp_path)])
    assert rc == 2


@pytest.mark.unit
def test_json_mode_emits_report(with_issues, capsys, tmp_path):
    import json
    with_issues([_fake_issue(1, "баг", labels=["bug"])])
    rc = ai_ops_cli.main(["backlog", "classify", str(tmp_path), "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True and data["total"] == 1
