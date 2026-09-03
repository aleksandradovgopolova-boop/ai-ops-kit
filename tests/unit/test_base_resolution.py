"""Unit-тесты выбора базы worktree (F-014) — tools/pipeline_git._resolve_base.

Находка живой квалификации на niti (2026-08-06): рабочая ветка сессии содержала уже принятые
задачи, но каждый `run --execute` резал worktree от origin/main — вторая задача не видела
результат первой и правила те же файлы от старой версии. Исполнителю пришлось вручную делать
`git reset --hard` в каждом managed-worktree.

Причина — порядок AUTO-резолва: upstream -> origin/HEAD -> текущая ветка. Ветка, на которой
стоит пользователь, стояла последней и почти никогда не выбиралась.

Три обязательных теста на capability (AGENTS.md):
  * positive       — AUTO берёт текущую ветку; явный --base по-прежнему сильнее;
  * fail-closed    — несуществующая явная база не резолвится (не тихий HEAD); detached HEAD без
                     upstream/origin честно не резолвится, а не выдаёт «ветку» с именем HEAD;
  * side-effect    — сценарий niti целиком: база РЕАЛЬНО содержит коммит предыдущей задачи.
"""
from __future__ import annotations

import subprocess

import pytest

from ai_ops_kit.engine import pipeline_git


def _git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)


def _repo_with_origin(tmp_path):
    """Клон с origin/HEAD -> main и локальной веткой поверх: ровно расклад niti."""
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], capture_output=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], capture_output=True)
    _git(work, "config", "user.email", "t@t")
    _git(work, "config", "user.name", "t")
    (work / "f.txt").write_text("v1\n", encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "base")
    _git(work, "push", "-q", "origin", "HEAD:main")
    _git(work, "remote", "set-head", "origin", "main")
    return work


# ---------------------------------------------------------------- positive ---

@pytest.mark.unit
class TestAutoPrefersWhereTheUserStands:

    def test_auto_takes_current_branch(self, tmp_path):
        work = _repo_with_origin(tmp_path)
        _git(work, "checkout", "-q", "-b", "ai-ops-main")

        res = pipeline_git._resolve_base(work, None)

        assert res["resolved"] is True
        assert res["base_ref"] == "ai-ops-main"
        assert res["source"] == "current-branch"
        assert res["mode"] == "auto"

    def test_explicit_base_still_wins(self, tmp_path):
        """Решение человека сильнее автовыбора — иначе --base стал бы декоративным."""
        work = _repo_with_origin(tmp_path)
        _git(work, "checkout", "-q", "-b", "ai-ops-main")

        res = pipeline_git._resolve_base(work, "main")

        assert res["resolved"] is True
        assert res["base_ref"] == "main"
        assert res["source"] in ("explicit-local", "explicit-remote")


# ------------------------------------------------------------- fail-closed ---

@pytest.mark.unit
class TestUnresolvableBaseIsAdmitted:

    def test_missing_explicit_base_is_not_resolved(self, tmp_path):
        work = _repo_with_origin(tmp_path)
        assert pipeline_git._resolve_base(work, "no-such-branch-xyz")["resolved"] is False

    def test_detached_head_without_remote_is_not_a_branch(self, tmp_path):
        """Прежде здесь возвращалось base_ref='HEAD' — не ветка. Дальше по цепочке такая «база»
        ищется как refs/heads/HEAD, и доставка врёт. Честный отказ вместо псевдо-ветки."""
        work = tmp_path / "solo"
        work.mkdir()
        _git(work, "init", "-q")
        _git(work, "config", "user.email", "t@t")
        _git(work, "config", "user.name", "t")
        (work / "f.txt").write_text("v1\n", encoding="utf-8")
        _git(work, "add", "-A")
        _git(work, "commit", "-qm", "one")
        sha = _git(work, "rev-parse", "HEAD").stdout.strip()
        _git(work, "checkout", "-q", sha)          # detached

        res = pipeline_git._resolve_base(work, None)

        assert res["resolved"] is False
        assert res["base_ref"] is None
        assert "detached" in res["reason"].lower()

    def test_not_a_git_repo_is_not_resolved(self, tmp_path):
        assert pipeline_git._resolve_base(tmp_path, None)["resolved"] is False


# -------------------------------------------------------- side-effect proof ---

@pytest.mark.unit
def test_sequential_tasks_build_on_each_other(tmp_path):
    """Сценарий niti целиком: на ветке лежит принятая задача, которой нет в origin/main.
    База обязана её содержать — иначе следующая задача правит файлы от старой версии."""
    work = _repo_with_origin(tmp_path)
    _git(work, "checkout", "-q", "-b", "ai-ops-main")
    (work / "accepted.txt").write_text("результат задачи 1\n", encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "принятая задача 1")

    # предпосылка сценария: старый порядок выбрал бы origin/main, где этой задачи нет
    assert _git(work, "rev-parse", "--symbolic-full-name", "@{u}").returncode != 0, \
        "у ветки не должно быть upstream — иначе сценарий не тот"
    origin_main = _git(work, "rev-parse", "refs/remotes/origin/main").stdout.strip()
    assert _git(work, "cat-file", "-e", f"{origin_main}:accepted.txt").returncode != 0

    res = pipeline_git._resolve_base(work, None)

    assert _git(work, "cat-file", "-e", f"{res['base_sha']}:accepted.txt").returncode == 0, \
        "база не содержит результат предыдущей задачи — последовательная работа снова сломана"
