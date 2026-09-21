"""Поведенческие тесты `ai-ops delivery record` — подтверждённая расписка для вручную влитого PR.

Сетевой слой (`pr_open._gh_request`) замокан — тесты НЕ ходят в сеть; проверяется ровно инвариант
честности: `sha_verified: true` пишется ТОЛЬКО когда GitHub сообщает PR влитым (merged_at +
merge_commit_sha). Живой прогон против настоящего GitHub здесь не выполняется (нужны токен + доступ).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from ai_ops_kit.delivery import record_delivery as rd
from ai_ops_kit.delivery import pr_open
from ai_ops_kit.checks import feature_blueprint


def _git_repo_with_origin(root: Path):
    """Реальный git-репозиторий с origin GitHub-вида — чтобы разбор owner/repo шёл по-настоящему."""
    root.mkdir(parents=True, exist_ok=True)
    for a in (("init", "-q"), ("config", "user.email", "t@t"), ("config", "user.name", "t"),
              ("remote", "add", "origin", "git@github.com:acme/widget.git")):
        subprocess.run(["git", "-C", str(root), *a], capture_output=True)


def _fake_gh(pr_payload, *, checks=None):
    """Роутер REST по URL: канонический слаг, конкретный PR по номеру, проверки на SHA.
    Возвращает функцию совместимой с pr_open._gh_request сигнатуры (url, token, data, method)."""
    checks = checks or {"check_runs": []}

    def _router(url, token, data=None, method="GET"):
        if url.endswith("/repos/acme/widget"):
            return {"full_name": "acme/widget"}, None
        if "/pulls/" in url:
            return pr_payload, None
        if url.endswith("/check-runs"):
            return checks, None
        if url.endswith("/status"):
            return {"statuses": []}, None
        return None, "UnexpectedURL"
    return _router


def _merged_pr(number=7, merge_sha="mergedsha123456", head_sha="headsha7890"):
    return {"number": number, "merged_at": "2026-09-21T00:00:00Z",
            "merge_commit_sha": merge_sha, "state": "closed",
            "html_url": f"https://github.com/acme/widget/pull/{number}",
            "head": {"sha": head_sha, "ref": "feature/x"}, "base": {"ref": "main"}}


@pytest.mark.unit
class TestRecordDelivery:

    def test_merged_pr_writes_sha_verified_receipt_and_satisfies_released_check(
            self, tmp_path, monkeypatch):
        """Влитый PR -> расписка в приёмнике с sha_verified=True, commit_sha==merge_commit_sha,
        recorded_post_hoc=True; и released-check (delivery в профиле) ТЕПЕРЬ доволен (мост к #2a)."""
        repo = tmp_path / "repo"
        features = repo / "features"
        fdir = feature_blueprint.make_demo(features)      # features/demo-feature
        _git_repo_with_origin(repo)
        # released + один done-артефакт (предпосылка требования расписки)
        bp = yaml.safe_load((fdir / "blueprint.yaml").read_text(encoding="utf-8"))
        bp["feature"]["status"] = "released"
        bp["artifacts"]["discovery"][0]["status"] = "done"
        (fdir / "blueprint.yaml").write_text(yaml.safe_dump(bp, allow_unicode=True), encoding="utf-8")

        monkeypatch.setattr(pr_open._cp, "_github_token", lambda: "tok")
        monkeypatch.setattr(pr_open, "_gh_request", _fake_gh(_merged_pr(merge_sha="deadbeefcafe0001")))

        res = rd.record_delivery_for_pr(repo, "demo-feature", 7)
        assert res["status"] == "recorded"
        assert res["sha_verified"] is True

        receipts = list((fdir / "delivery-outbox").glob("*.receipt.yaml"))
        assert len(receipts) == 1
        r = yaml.safe_load(receipts[0].read_text(encoding="utf-8"))
        assert r["kind"] == "DeliveryReceipt"
        assert r["sha_verified"] is True
        assert r["commit_sha"] == "deadbeefcafe0001"
        assert r["remote_sha"] == "deadbeefcafe0001"
        assert r["merged"] is True
        assert r["recorded_post_hoc"] is True
        assert r["recorded_via"] == "delivery record"

        # МОСТ: released-check по тому же приёмнику теперь удовлетворён.
        errors, _adv = feature_blueprint.validate_dir_full(fdir)
        assert not [e for e in errors if "released" in e]

    def test_open_pr_never_writes_sha_verified_and_released_check_still_complains(
            self, tmp_path, monkeypatch):
        """Открытый (не влитый) PR -> НЕТ sha_verified=true; статус not-delivered; released-check
        по-прежнему честно жалуется."""
        repo = tmp_path / "repo"
        features = repo / "features"
        fdir = feature_blueprint.make_demo(features)
        _git_repo_with_origin(repo)
        bp = yaml.safe_load((fdir / "blueprint.yaml").read_text(encoding="utf-8"))
        bp["feature"]["status"] = "released"
        bp["artifacts"]["discovery"][0]["status"] = "done"
        (fdir / "blueprint.yaml").write_text(yaml.safe_dump(bp, allow_unicode=True), encoding="utf-8")

        open_pr = {"number": 9, "merged_at": None, "merge_commit_sha": None, "state": "open",
                   "html_url": "https://github.com/acme/widget/pull/9",
                   "head": {"sha": "openhead123", "ref": "feature/y"}, "base": {"ref": "main"}}
        monkeypatch.setattr(pr_open._cp, "_github_token", lambda: "tok")
        monkeypatch.setattr(pr_open, "_gh_request", _fake_gh(open_pr))

        res = rd.record_delivery_for_pr(repo, "demo-feature", 9)
        assert res["status"] == "not-delivered"
        assert res["sha_verified"] is False
        r = yaml.safe_load(next((fdir / "delivery-outbox").glob("*.receipt.yaml")).read_text(encoding="utf-8"))
        assert r.get("sha_verified") is not True
        assert r["merged"] is False

        errors, _adv = feature_blueprint.validate_dir_full(fdir)
        assert [e for e in errors if "released" in e]   # честно всё ещё жалуется

    def test_no_token_writes_nothing(self, tmp_path, monkeypatch):
        """Нет токена -> unavailable, НИЧЕГО не записано, честное сообщение (fail-closed)."""
        repo = tmp_path / "repo"
        (repo / "features" / "demo-feature").mkdir(parents=True)
        _git_repo_with_origin(repo)
        monkeypatch.setattr(pr_open._cp, "_github_token", lambda: None)

        res = rd.record_delivery_for_pr(repo, "demo-feature", 7)
        assert res["status"] == "unavailable"
        assert not list((repo / "features" / "demo-feature").glob("**/*.receipt.yaml"))

    def test_closed_unmerged_pr_not_verified(self, tmp_path, monkeypatch):
        """Закрытый БЕЗ merge PR -> mismatch, sha_verified не true (закрыт != влит)."""
        repo = tmp_path / "repo"
        (repo / "features" / "demo-feature").mkdir(parents=True)
        _git_repo_with_origin(repo)
        closed = {"number": 5, "merged_at": None, "merge_commit_sha": None, "state": "closed",
                  "html_url": "https://github.com/acme/widget/pull/5",
                  "head": {"sha": "closedhead", "ref": "feature/z"}, "base": {"ref": "main"}}
        monkeypatch.setattr(pr_open._cp, "_github_token", lambda: "tok")
        monkeypatch.setattr(pr_open, "_gh_request", _fake_gh(closed))

        res = rd.record_delivery_for_pr(repo, "demo-feature", 5)
        assert res["status"] == "mismatch"
        assert res["sha_verified"] is False
        r = yaml.safe_load(next((repo / "features" / "demo-feature" / "delivery-outbox")
                                .glob("*.receipt.yaml")).read_text(encoding="utf-8"))
        assert r.get("sha_verified") is not True

    def test_parse_pr_number_from_url_and_forms(self):
        """Разбор ввода: голое число, строка-число, полный URL PR; мусор -> None."""
        assert rd.parse_pr_number(7) == 7
        assert rd.parse_pr_number("42") == 42
        assert rd.parse_pr_number("https://github.com/acme/widget/pull/123") == 123
        assert rd.parse_pr_number("  https://github.com/acme/widget/pull/8/files  ") == 8
        assert rd.parse_pr_number("not-a-pr") is None
        assert rd.parse_pr_number("0") is None
        assert rd.parse_pr_number(None) is None
