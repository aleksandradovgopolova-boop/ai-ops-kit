"""Селфтест validate_python_compat, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_python_compat import (  # noqa: F401 — имена, которые использует тело
    PKG,
    check_source,
    scan,
)


@pytest.mark.slow
def test_validate_python_compat_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    # union без future -> нарушение (в т.ч. return, arg, AnnAssign)
    bad_arg = "def f(x: int | None):\n    return x\n"
    bad_ret = "def g() -> str | None:\n    return None\n"
    bad_var = "y: int | str = 1\n"
    expect("union в аргументе без future -> flagged", check_source(bad_arg) == [1])
    expect("union в возврате без future -> flagged", check_source(bad_ret) == [1])
    expect("union в AnnAssign без future -> flagged", check_source(bad_var) == [1])

    # с future -> ок
    good = "from __future__ import annotations\n\ndef f(x: int | None):\n    return x\n"
    expect("union под future-import -> ок", check_source(good) == [])

    # нет union -> ок
    expect("нет union -> ок", check_source("def f(x: int):\n    return x\n") == [])

    # реальный пакет: после фикса нарушений быть не должно
    expect("реальный пакет: 0 нарушений совместимости", scan(PKG) == [])

    assert ok, "перенесённый селфтест validate_python_compat: см. строки FAIL в выводе"
