"""Пост-фактум сторож путей для shell (v3.36).

Проверяется закрытие разрыва из живого прогона: `write` в protected-путь отклонялся, а
эквивалентная правка тем же движком через shell (`sed -i`, `echo >`) проходила молча — и не
попадала даже в счётчик правок. Теперь последствия shell сверяются с protected_paths, нарушения
откатываются, а операция помечается запрещённой.

Границы сторожа тоже зафиксированы тестами, чтобы обещание не разрослось: не-git дерево не
проверяется, write_scope для shell по умолчанию не enforced, чужая грязь до операции не судится.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]

from ai_ops_kit.engine import tool_broker


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


@pytest.fixture
def git_repo(tmp_path):
    """Git-дерево с закоммиченным файлом в protected-пути (production/ — дефолт пакета)."""
    repo = tmp_path / "child"
    (repo / "production").mkdir(parents=True)
    (repo / "src").mkdir()
    (repo / "docs").mkdir()
    (repo / "production" / "app.conf").write_text("real=1\n", encoding="utf-8")
    (repo / "src" / "main.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "docs" / "readme.md").write_text("док\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "начальное состояние")
    return repo


def _head(root):
    return _git(root, "rev-parse", "HEAD").stdout.strip()


@pytest.mark.critical_path
@pytest.mark.unit
class TestShellPathGuard:
    def test_write_op_into_protected_denied(self, git_repo):
        """Опора: канал write в protected-путь запрещён (поведение не изменилось)."""
        policy = tool_broker.Policy(level="execution", child_root=str(git_repo))
        ev = tool_broker.execute(
            {"op": "write", "path": "production/app.conf", "content": "взломано\n"},
            git_repo, policy)
        assert ev["allowed"] is False
        assert "protected" in ev["reason"]
        assert (git_repo / "production" / "app.conf").read_text() == "real=1\n"

    def test_shell_into_protected_reverted_and_denied(self, git_repo):
        """Тот же путь через shell: раньше проходило молча, теперь откат + запрет."""
        policy = tool_broker.Policy(level="execution", child_root=str(git_repo))
        ev = tool_broker.execute(
            {"op": "shell", "command": "echo взломано > production/app.conf"}, git_repo, policy)
        assert ev["allowed"] is False, "shell в protected-путь обязан быть помечен запрещённым"
        assert ev["fs_guard"]["violations"], "нарушение должно попасть в evidence"
        assert ev["fs_guard"]["violations"][0]["path"] == "production/app.conf"
        assert (git_repo / "production" / "app.conf").read_text() == "real=1\n", "правка не откачена"

    def test_shell_creating_new_file_in_protected_removed(self, git_repo):
        """Новый файл в protected-пути удаляется (его нет в HEAD, восстанавливать нечего)."""
        policy = tool_broker.Policy(level="execution", child_root=str(git_repo))
        ev = tool_broker.execute(
            {"op": "shell", "command": "echo x > production/new.conf"}, git_repo, policy)
        assert ev["allowed"] is False
        assert not (git_repo / "production" / "new.conf").exists()
        assert "production/new.conf" in ev["fs_guard"]["reverted"]["removed"]

    def test_shell_creating_nested_file_in_protected_removed(self, git_repo):
        """Файл в НОВОМ подкаталоге: git сворачивает untracked-каталоги, откат обязан не промахнуться."""
        policy = tool_broker.Policy(level="execution", child_root=str(git_repo))
        ev = tool_broker.execute(
            {"op": "shell", "command": "mkdir -p production/sub && echo x > production/sub/new.conf"},
            git_repo, policy)
        assert ev["allowed"] is False
        assert not (git_repo / "production" / "sub" / "new.conf").exists(), "вложенный файл не удалён"
        assert ev["fs_guard"]["reverted"]["failed"] == []

    def test_shell_commit_of_protected_is_reset(self, git_repo):
        """Модель может коммитить сама — тогда снимается и коммит, иначе откат дерева бесполезен."""
        before = _head(git_repo)
        policy = tool_broker.Policy(level="execution", child_root=str(git_repo))
        ev = tool_broker.execute(
            {"op": "shell",
             "command": "echo взломано > production/app.conf && git add -A && git commit -qm правка"},
            git_repo, policy)
        assert ev["allowed"] is False
        assert _head(git_repo) == before, "коммит операции обязан быть снят"
        assert (git_repo / "production" / "app.conf").read_text() == "real=1\n"
        assert any(v["committed"] for v in ev["fs_guard"]["violations"])

    def test_shell_deleting_protected_file_restored(self, git_repo):
        """Удаление — тоже изменение защищённого пути. `rm file` денайлистом не ловится."""
        policy = tool_broker.Policy(level="execution", child_root=str(git_repo))
        ev = tool_broker.execute(
            {"op": "shell", "command": "rm production/app.conf"}, git_repo, policy)
        assert ev["allowed"] is False
        assert (git_repo / "production" / "app.conf").read_text() == "real=1\n", "файл не восстановлен"

    def test_shell_moving_content_out_of_protected_reverted_both_sides(self, git_repo):
        """Вынос содержимого переносом: откат ОБЕИХ сторон, иначе копия снаружи остаётся."""
        policy = tool_broker.Policy(level="execution", child_root=str(git_repo))
        ev = tool_broker.execute(
            {"op": "shell", "command": "git mv production/app.conf src/leaked.conf"},
            git_repo, policy)
        assert ev["allowed"] is False
        assert (git_repo / "production" / "app.conf").read_text() == "real=1\n"
        assert not (git_repo / "src" / "leaked.conf").exists(), "копия вне protected-пути осталась"

    def test_shell_into_allowed_path_untouched(self, git_repo):
        """Законная правка не страдает: сторож судит только запрещённые пути."""
        policy = tool_broker.Policy(level="execution", child_root=str(git_repo))
        ev = tool_broker.execute(
            {"op": "shell", "command": "echo 'y = 2' > src/main.py"}, git_repo, policy)
        assert ev["allowed"] is True
        assert ev["fs_guard"]["violations"] == []
        assert (git_repo / "src" / "main.py").read_text().strip() == "y = 2"

    def test_pre_existing_dirt_not_blamed(self, git_repo):
        """Грязь, существовавшая ДО операции, не вменяется команде — судится только delta."""
        (git_repo / "production" / "app.conf").write_text("правил человек\n", encoding="utf-8")
        policy = tool_broker.Policy(level="execution", child_root=str(git_repo))
        ev = tool_broker.execute(
            {"op": "shell", "command": "echo 'y = 2' > src/main.py"}, git_repo, policy)
        assert ev["allowed"] is True, "чужая грязь до операции не должна её запрещать"
        assert (git_repo / "production" / "app.conf").read_text() == "правил человек\n"


@pytest.mark.unit
class TestShellPathGuardBoundaries:
    """Обещание сторожа ровно такое, как объявлено — не больше."""

    def test_scope_guard_off_by_default(self, git_repo):
        """write_scope для shell по умолчанию НЕ enforced: движок сам пишет lock-файлы вне scope."""
        policy = tool_broker.Policy(level="execution", write_scope=["src/"], child_root=str(git_repo))
        ev = tool_broker.execute(
            {"op": "shell", "command": "echo дописано >> docs/readme.md"}, git_repo, policy)
        assert ev["allowed"] is True
        assert ev["fs_guard"]["violations"] == []

    def test_scope_guard_enforces_when_enabled(self, git_repo):
        """С shell_scope_guard=True тот же случай откатывается."""
        policy = tool_broker.Policy(level="execution", write_scope=["src/"],
                                    child_root=str(git_repo), shell_scope_guard=True)
        ev = tool_broker.execute(
            {"op": "shell", "command": "echo дописано >> docs/readme.md"}, git_repo, policy)
        assert ev["allowed"] is False
        assert "write_scope" in ev["reason"]
        assert (git_repo / "docs" / "readme.md").read_text() == "док\n"

    def test_non_git_root_guard_silent(self, tmp_path):
        """Не-git дерево: сверять не с чем — сторож молчит и НЕ делает вид, что проверил."""
        repo = tmp_path / "plain"
        (repo / "production").mkdir(parents=True)
        policy = tool_broker.Policy(level="execution", child_root=str(repo))
        ev = tool_broker.execute(
            {"op": "shell", "command": "echo x > production/app.conf"}, repo, policy)
        assert ev["allowed"] is True
        assert "fs_guard" not in ev, "без git сторож не должен заявлять о проверке"

    def test_guard_can_be_disabled(self, git_repo):
        """Выключаемость: shell_path_guard=False возвращает прежнее поведение."""
        policy = tool_broker.Policy(level="execution", child_root=str(git_repo),
                                    shell_path_guard=False)
        ev = tool_broker.execute(
            {"op": "shell", "command": "echo взломано > production/app.conf"}, git_repo, policy)
        assert ev["allowed"] is True
        assert "fs_guard" not in ev

    def test_privileged_with_approval_may_touch_protected(self, git_repo):
        """Одобренный человеком привилегированный прогон правит protected-путь и через shell."""
        policy = tool_broker.Policy(level="privileged", child_root=str(git_repo),
                                    approvals={"protected_path_write"})
        ev = tool_broker.execute(
            {"op": "shell", "command": "echo одобрено > production/app.conf"}, git_repo, policy)
        assert ev["allowed"] is True
        assert ev["fs_guard"]["violations"] == []
        assert (git_repo / "production" / "app.conf").read_text().strip() == "одобрено"
