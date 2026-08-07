"""Селфтест pr_open, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

import pr_open

from pr_open import (  # noqa: F401 — имена, которые использует тело
    _pr_payload,
    open_draft_pr,
    os,
    reconcile_delivery,
    subprocess,
)


@pytest.mark.slow
def test_pr_open_selftest():
    _orig_gh, _orig_cp = pr_open._gh_request, pr_open._cp
    try:
        ok = True

        def expect(name, cond):
            nonlocal ok
            ok = ok and cond
            print(f"{'PASS' if cond else 'FAIL'} {name}")

        # чистая конструкция payload
        p = _pr_payload("ai-ops/x", "Заголовок", "Тело", base="main")
        expect("payload: draft=True", p["draft"] is True)
        expect("payload: head/base/title/body", p["head"] == "ai-ops/x" and p["base"] == "main"
               and p["title"] == "Заголовок" and p["body"] == "Тело")

        # без токена -> honest unavailable, сеть не трогаем, payload приложен
        import tempfile
        saved = {k: os.environ.pop(k, None) for k in ("GITHUB_TOKEN", "GH_TOKEN")}
        try:
            with tempfile.TemporaryDirectory() as td:
                subprocess.run(["git", "-C", td, "init", "-q"])
                r = open_draft_pr(td, "ai-ops/y", "T", "B")
                expect("нет токена -> unavailable (не имитируем PR)",
                       r["status"] == "unavailable" and "GITHUB_TOKEN" in r["note"])
                expect("unavailable несёт готовый payload (механизм готов)",
                       r.get("payload", {}).get("draft") is True)
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v

        # v2.93: base=None -> резолвится дефолт-ветка репо (не хардкод main); существующий PR ->
        # идемпотентный 'updated' без создания дубля. Сеть стабим через pr_open._gh_request.
        import tempfile as _tf
        real_gh, real_token = pr_open._gh_request, pr_open._cp._github_token
        try:
            pr_open._cp._github_token = lambda: "tok"  # noqa: E731 (стаб на время теста)
            calls = {"post": 0}

            def fake_gh(url, token, data=None, method="GET"):
                if method == "GET" and url.endswith("/repos/o/r"):
                    return {"default_branch": "develop"}, None       # дефолт-ветка НЕ main
                if "pulls?head=" in url:
                    return [], None                                  # открытого PR нет
                if method == "POST":
                    calls["post"] += 1
                    return {"html_url": "u", "number": 7, "draft": True}, None
                return {}, None
            pr_open._gh_request = fake_gh
            with _tf.TemporaryDirectory() as td:
                subprocess.run(["git", "-C", td, "init", "-q"])
                subprocess.run(["git", "-C", td, "remote", "add", "origin", "https://github.com/o/r.git"])
                r = open_draft_pr(td, "ai-ops/z", "T", "B", push=False)
                expect("v2.93: base=None -> дефолт-ветка develop (не хардкод main)",
                       r["status"] == "opened" and r.get("base") == "develop")

            def fake_gh_existing(url, token, data=None, method="GET"):
                if "pulls?head=" in url:
                    return [{"html_url": "u2", "number": 3, "draft": True}], None   # PR уже открыт
                if method == "POST":
                    calls["post"] += 1
                    return {"html_url": "x", "number": 99}, None
                return {"default_branch": "main"}, None
            pr_open._gh_request = fake_gh_existing
            with _tf.TemporaryDirectory() as td:
                subprocess.run(["git", "-C", td, "init", "-q"])
                subprocess.run(["git", "-C", td, "remote", "add", "origin", "https://github.com/o/r.git"])
                before = calls["post"]
                r = open_draft_pr(td, "ai-ops/z", "T", "B", base="main", push=False)
                expect("v2.93: существующий PR -> 'updated', без создания дубля (идемпотентно)",
                       r["status"] == "updated" and r["number"] == 3 and calls["post"] == before)
        finally:
            pr_open._gh_request = real_gh
            pr_open._cp._github_token = real_token

        # v3.0.17 (finding аудита P1): неоднозначный POST (сеть/timeout после отправки) -> outcome_unknown
        real_gh2, real_token2 = pr_open._gh_request, pr_open._cp._github_token
        _cap = {}
        try:
            pr_open._cp._github_token = lambda: "tok"  # noqa: E731

            def fake_gh_ambiguous(url, token, data=None, method="GET"):
                if "pulls?head=" in url:
                    return [], None                     # открытого PR нет
                if method == "POST":
                    _cap["body"] = (data or {}).get("body")
                    return None, "URLError"             # ответ ПОСЛЕ POST потерян
                return {"default_branch": "main"}, None
            pr_open._gh_request = fake_gh_ambiguous
            with _tf.TemporaryDirectory() as td:
                subprocess.run(["git", "-C", td, "init", "-q"])
                subprocess.run(["git", "-C", td, "remote", "add", "origin", "https://github.com/o/r.git"])
                r = open_draft_pr(td, "ai-ops/z", "T", "B", base="main", push=False, delivery_id="deadbeef")
                expect("v3.0.17 P1: неоднозначный POST -> outcome_unknown (не confirmed error)",
                       r["status"] == "outcome_unknown" and r.get("repository") == "o/r")
                expect("v3.0.17: delivery_id вшит маркером в body PR",
                       "ai-ops-delivery-id: deadbeef" in (_cap.get("body") or ""))

            # v3.0.17 (P0): reconcile_delivery возвращает ФАКТЫ remote (head_sha/base_ref/repo/state)
            def fake_gh_reconcile(url, token, data=None, method="GET"):
                if "pulls?head=" in url and "state=all" in url:
                    return [{"html_url": "https://x/pr/9", "number": 9, "state": "open",
                             "head": {"sha": "abc1234"}, "base": {"ref": "main"}}], None
                return {}, None
            pr_open._gh_request = fake_gh_reconcile
            with _tf.TemporaryDirectory() as td:
                subprocess.run(["git", "-C", td, "init", "-q"])
                subprocess.run(["git", "-C", td, "remote", "add", "origin", "https://github.com/o/r.git"])
                rc = reconcile_delivery(td, "ai-ops/z")
                expect("v3.0.17 P0: reconcile возвращает head_sha/base_ref/repository/state (не только имя ветки)",
                       rc["status"] == "found" and rc["head_sha"] == "abc1234"
                       and rc["base_ref"] == "main" and rc["repository"] == "o/r" and rc["pr_state"] == "open")

            def fake_gh_absent(url, token, data=None, method="GET"):
                return [], None
            pr_open._gh_request = fake_gh_absent
            with _tf.TemporaryDirectory() as td:
                subprocess.run(["git", "-C", td, "init", "-q"])
                subprocess.run(["git", "-C", td, "remote", "add", "origin", "https://github.com/o/r.git"])
                expect("v3.0.17 P0: PR отсутствует -> absent + repository",
                       reconcile_delivery(td, "ai-ops/z") == {"status": "absent", "repository": "o/r"})
        finally:
            pr_open._gh_request = real_gh2
            pr_open._cp._github_token = real_token2

        assert ok, "перенесённый селфтест pr_open: см. строки FAIL в выводе"
    finally:
        pr_open._gh_request, pr_open._cp = _orig_gh, _orig_cp
