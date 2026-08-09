"""Селфтест validate_freshness, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_freshness import (  # noqa: F401 — имена, которые использует тело
    Path,
    _default_child_context,
    assess,
    date,
)


@pytest.mark.slow
def test_validate_freshness_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    today = date(2026, 7, 13)
    expect("stable не истекает",
           assess({"stability": "stable", "reviewed_at": "2020-01-01"}, today)[0] == "ok")
    expect("volatile 35д назад — протух",
           assess({"stability": "volatile", "reviewed_at": "2026-06-08"}, today)[0] == "stale")
    expect("volatile 3д назад — свеж",
           assess({"stability": "volatile", "reviewed_at": "2026-07-10"}, today)[0] == "ok")
    expect("evolving 100д назад — протух",
           assess({"stability": "evolving", "reviewed_at": "2026-04-04"}, today)[0] == "stale")
    expect("нет reviewed_at — WARN",
           assess({"stability": "volatile"}, today)[0] == "no-review-date")
    expect("без stability — не проверяется",
           assess({"title": "x"}, today) is None)
    expect("кастомный expires_after_days уважается",
           assess({"stability": "evolving", "reviewed_at": "2026-07-01",
                   "expires_after_days": 5}, today)[0] == "stale")
    # v3.12.0: шаблон кита (template: true) не проверяется, даже с протухшей датой
    expect("template: true — не проверяется (протух шаблон != протух репо)",
           assess({"template": True, "stability": "volatile", "reviewed_at": "2020-01-01"}, today) is None)
    # v3.12.0: дефолтный путь — контекст РЕПОЗИТОРИЯ, не шаблоны кита
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / ".ai/project/context").mkdir(parents=True)
        expect("дефолт -> .ai/project/context репозитория",
               _default_child_context(base) == (base / ".ai/project/context").resolve())
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / ".ai/custom/context").mkdir(parents=True)
        expect("дефолт -> .ai/custom/context при отсутствии project",
               _default_child_context(base) == (base / ".ai/custom/context").resolve())

    assert ok, "перенесённый селфтест validate_freshness: см. строки FAIL в выводе"
