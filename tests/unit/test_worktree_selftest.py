"""Селфтест worktree, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from worktree import (  # noqa: F401 — имена, которые использует тело
    Path,
    _branch_exists,
    _git,
    add,
    remove,
)


@pytest.mark.slow
def test_worktree_selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _git(root, "init", "-q")
        _git(root, "config", "user.email", "t@t")
        _git(root, "config", "user.name", "t")
        (root / "f.txt").write_text("x", encoding="utf-8")
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "init")

        expect("add в main -> ошибка", add(root, "wi-1", "main") == 1)
        expect("add без branch -> ошибка", add(root, "wi-1", "") == 1)

        rc = add(root, "wi-1", "feature/wi-1")
        expect("add: worktree создан", rc == 0 and (root / ".ai/worktrees/wi-1").is_dir())

        rc, out, _ = _git(root, "worktree", "list", "--porcelain")
        expect("list: содержит новый worktree", "wi-1" in out and "feature/wi-1" in out)

        expect("add дубликата -> ошибка", add(root, "wi-1", "feature/wi-1b") == 1)

        expect("remove: worktree удалён",
               remove(root, "wi-1") == 0 and not (root / ".ai/worktrees/wi-1").exists())

        # ветка feature/wi-1 сохранилась после remove
        expect("remove сохраняет ветку", _branch_exists(root, "feature/wi-1"))

        # P1.1: traversal-guard — id, выводящий за корень, отвергается
        expect("add: traversal id (../) отвергнут",
               add(root, "../escape", "feature/x") == 1 and not (root.parent / "escape").exists())
        expect("add: абсолютный id отвергнут", add(root, "/tmp/evil", "feature/y") == 1)
        expect("remove: traversal id (../) отвергнут", remove(root, "../escape") == 1)

    assert ok, "перенесённый селфтест worktree: см. строки FAIL в выводе"
