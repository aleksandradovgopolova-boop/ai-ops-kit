"""Селфтест gitio, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from gitio import (  # noqa: F401 — имена, которые использует тело
    git,
)


@pytest.mark.slow
def test_gitio_selftest():
    import tempfile
    from pathlib import Path
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        rc, out, err = git(root, "rev-parse", "--is-inside-work-tree")
        expect("git: не-репо -> rc!=0 (кортеж (rc,out,err))", rc != 0 and isinstance(out, str) and isinstance(err, str))
        for a in (("init", "-q"), ("config", "user.email", "t@t"), ("config", "user.name", "t")):
            git(root, *a)
        (root / "f").write_text("x", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "i")
        rc2, out2, _ = git(root, "rev-parse", "--abbrev-ref", "HEAD")
        expect("git: rev-parse ветки -> rc=0 + непустой stdout.strip()", rc2 == 0 and bool(out2))
        # таймаут: невозможная задержка отдаёт rc=124, а не висит (git не запускается на левой команде,
        # но проверяем контракт таймаута на заведомо быстрой команде с крошечным лимитом косвенно нельзя —
        # проверяем лишь, что параметр timeout принимается и обычная команда укладывается)
        rc3, _, _ = git(root, "status", "--porcelain", timeout=30)
        expect("git: timeout-параметр принят, быстрая команда укладывается (rc=0)", rc3 == 0)

    assert ok, "перенесённый селфтест gitio: см. строки FAIL в выводе"
