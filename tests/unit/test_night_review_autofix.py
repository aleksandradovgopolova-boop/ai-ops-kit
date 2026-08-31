"""Класс A ночного автофикса: детерминированные правки в worktree -> один черновой PR за ночь.

DONE-WHEN (предложен работой, у карточки его не было):
1. Изоляция и один PR: правки только в worktree на не-main ветке, собираются в ОДИН черновой PR;
   main не трогается никогда.
2. Класс A детерминирован, gated и ПУСТ по умолчанию: без включённых фиксеров / с kill-switch /
   с policy=suggest — ничего не правится и не открывается, отчёт честно говорит почему.
3. Провал проверки откатывается; unknown не чинится (берём только доказанные правки).
4. Прогон auditable: отчёт называет ветку, файлы, PR или причину, что ничего не сделано.

`tests/` — вне write_scope этой работы (принадлежит соседней); правки согласованы (см. PR).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT))

from ai_ops_kit.engine import worktree  # noqa: E402
from ai_ops_kit.intelligence import nightly_review as NR  # noqa: E402


def _repo(tmp_path, with_dirty_doc=True):
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    (root / "src").mkdir()
    (root / "src" / "keep.py").write_text("x = 1\n", encoding="utf-8")
    (root / "docs" / "guide.md").write_text(
        "Заголовок   \n\nстрока с хвостом  \n" if with_dirty_doc else "Чисто\n", encoding="utf-8")

    def git(*a):
        subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True)
    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    git("add", "-A")
    git("commit", "-qm", "base")
    return root, git


def _head(root):
    return subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()


@pytest.mark.unit
def test_class_a_is_empty_by_default(tmp_path, monkeypatch):
    """Fail-closed: без включённых фиксеров ничего не правится и не открывается PR."""
    monkeypatch.delenv(NR.NIGHTLY_AUTOFIX_ENV, raising=False)
    root, _ = _repo(tmp_path)
    res = NR.run_autofix(root)
    assert res["status"] == "disabled"
    assert "пуст" in res["reason"]
    assert res["pr"] is None and res["applied"] == []


@pytest.mark.unit
def test_kill_switch_env_disables(tmp_path, monkeypatch):
    """Kill-switch env глушит даже при включённом фиксере."""
    monkeypatch.setenv(NR.NIGHTLY_AUTOFIX_ENV, "off")
    root, _ = _repo(tmp_path)
    res = NR.run_autofix(root, enabled=["trailing-whitespace"])
    assert res["status"] == "disabled" and "заглушён" in res["reason"]


@pytest.mark.unit
def test_dry_run_collects_into_branch_without_pr_and_never_touches_main(tmp_path, monkeypatch):
    """Правки собираются в НЕ-main ветку; main (HEAD рабочего дерева) не сдвинут; PR не открыт."""
    monkeypatch.delenv(NR.NIGHTLY_AUTOFIX_ENV, raising=False)
    root, _ = _repo(tmp_path)
    head_before = _head(root)
    res = NR.run_autofix(root, enabled=["trailing-whitespace"], dry_run=True, date="2026-08-27")

    assert res["status"] == "dry_run"
    assert res["branch"] == "ai-ops/nightly-autofix/2026-08-27"
    assert res["branch"] not in ("main", "master")
    assert any("docs/guide.md" in a["files"] for a in res["applied"])
    assert res["pr"] is None
    # main НЕ тронут: HEAD рабочего дерева тот же, рабочее дерево чистое
    assert _head(root) == head_before
    assert subprocess.run(["git", "-C", str(root), "status", "--porcelain"],
                          capture_output=True, text=True).stdout.strip() == ""
    # правка живёт на ветке автофикса
    branch_doc = subprocess.run(
        ["git", "-C", str(root), "show", f"{res['branch']}:docs/guide.md"],
        capture_output=True, text=True).stdout
    assert "хвостом  \n" not in branch_doc and "хвостом\n" in branch_doc


@pytest.mark.unit
def test_no_changes_when_docs_already_clean(tmp_path, monkeypatch):
    monkeypatch.delenv(NR.NIGHTLY_AUTOFIX_ENV, raising=False)
    root, _ = _repo(tmp_path, with_dirty_doc=False)
    res = NR.run_autofix(root, enabled=["trailing-whitespace"], dry_run=True)
    assert res["status"] == "no_changes"


@pytest.mark.unit
def test_verify_failure_rolls_back(tmp_path, monkeypatch):
    """Если проверка после фиксера не прошла — правка откатывается, ничего не собирается."""
    monkeypatch.delenv(NR.NIGHTLY_AUTOFIX_ENV, raising=False)
    root, _ = _repo(tmp_path)
    res = NR.run_autofix(root, enabled=["trailing-whitespace"], dry_run=True,
                         verify=lambda wt: False)
    assert res["status"] == "no_changes"          # всё откачено
    assert any("проверк" in s["reason"] for s in res["skipped"])


@pytest.mark.unit
def test_suggest_policy_only_recommends(tmp_path, monkeypatch):
    monkeypatch.delenv(NR.NIGHTLY_AUTOFIX_ENV, raising=False)
    root, _ = _repo(tmp_path)
    policy = {"default": "suggest", "actions": {"nightly_autofix": "suggest"}, "source": "тест"}
    res = NR.run_autofix(root, enabled=["trailing-whitespace"], policy=policy)
    assert res["status"] == "suggest-only" and res["pr"] is None


@pytest.mark.unit
def test_prepared_opens_one_draft_pr(tmp_path, monkeypatch):
    """С включённым фиксером и не-suggest политикой готовится ОДИН черновой PR (open_draft_pr заглушён)."""
    monkeypatch.delenv(NR.NIGHTLY_AUTOFIX_ENV, raising=False)
    root, _ = _repo(tmp_path)
    calls = []
    from ai_ops_kit.delivery import pr_open

    def fake_pr(root, branch, title, body="", base=None, push=True, delivery_id=None):
        calls.append({"branch": branch, "delivery_id": delivery_id})
        return {"status": "unavailable", "note": "stub — без токена PR не создаётся"}

    monkeypatch.setattr(pr_open, "open_draft_pr", fake_pr)
    policy = {"default": "prepare", "actions": {"nightly_autofix": "prepare"}, "source": "тест"}
    res = NR.run_autofix(root, enabled=["trailing-whitespace"], policy=policy, date="2026-08-27")

    assert res["status"] == "prepared"
    assert len(calls) == 1, "не более одного PR за ночь"
    assert calls[0]["branch"] == "ai-ops/nightly-autofix/2026-08-27"
    assert res["pr"]["status"] == "unavailable"


@pytest.mark.unit
def test_engine_primitive_refuses_main(tmp_path):
    """worktree.apply_fixes_in_worktree не пишет в main (add отказывает main/master)."""
    root, _ = _repo(tmp_path)
    res = worktree.apply_fixes_in_worktree(
        root, "main", [{"key": "x", "apply": lambda wt: []}])
    assert res["status"] == "error"


@pytest.mark.unit
def test_report_names_branch_and_files(tmp_path, monkeypatch):
    monkeypatch.delenv(NR.NIGHTLY_AUTOFIX_ENV, raising=False)
    root, _ = _repo(tmp_path)
    res = NR.run_autofix(root, enabled=["trailing-whitespace"], dry_run=True, date="2026-08-27")
    report = NR.format_autofix_report(res)
    assert "docs/guide.md" in report and "2026-08-27" in report


@pytest.mark.unit
def test_disabled_report_calls_it_a_decision_not_a_gap(tmp_path, monkeypatch):
    monkeypatch.delenv(NR.NIGHTLY_AUTOFIX_ENV, raising=False)
    root, _ = _repo(tmp_path)
    report = NR.format_autofix_report(NR.run_autofix(root))
    assert "решени" in report.lower()      # «граница по решению, а не недоделка»
