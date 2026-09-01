"""ШОВ доставки: контроллер (_deliver_pr) реально зовёт pr_open.open_draft_pr.

Модульные тесты pr_open остаются зелёными, даже если конвейер перестанет вызывать механизм —
именно так дефект доставки жил бы незамеченным. Этот тест краснеет, когда точка входа
open_draft_pr исчезает (seam-проба переименовывает `def`): вызов на строке _deliver_pr падает
AttributeError.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from ai_ops_kit.engine import execution_pipeline
from ai_ops_kit.delivery import pr_open


@pytest.mark.unit
def test_deliver_pr_invokes_open_draft_pr(monkeypatch):
    monkeypatch.setattr(pr_open._cp, "_github_token", lambda: "tok")

    def fake_git(root, *args):
        if args[:1] == ("remote",):
            return (0, "https://github.com/o/r.git", "")
        if args and args[0] == "push":
            return (0, "", "")
        if args and args[0] == "rev-parse":
            return (0, "c0ffee\n", "")
        return (0, "", "")

    def fake_gh(url, token, data=None, method="GET"):
        if "pulls?head=" in url:
            return ([], None)                 # PR ещё нет -> POST -> opened
        if method == "POST":
            return ({"html_url": "u", "number": 1, "draft": True, "head": {"sha": "c0ffee"}}, None)
        return ({"default_branch": "main"}, None)

    monkeypatch.setattr(pr_open, "_git", fake_git)
    monkeypatch.setattr(pr_open, "_gh_request", fake_gh)
    monkeypatch.setattr(execution_pipeline, "_verify_remote_base",
                        lambda work_root, base_ref, base_sha: {"verdict": "verified-equal"})

    dv = execution_pipeline._deliver_pr(
        "/work", "ai-ops/x", "main", "b0base", {"resolved": True}, "c0ffee", "W1", "задача",
        delivery_id="d1")

    # Механизм достигнут: статус и head_sha пришли из open_draft_pr. При seam-мутации (def
    # переименован) строка вызова в _deliver_pr падает AttributeError -> тест краснеет.
    assert dv["status"] == "opened"
    assert dv["pr"]["head_sha"] == "c0ffee"
