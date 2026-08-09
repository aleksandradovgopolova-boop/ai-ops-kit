"""Селфтест delegation_advisor, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from delegation_advisor import (  # noqa: F401 — имена, которые использует тело
    advise,
    check,
)


@pytest.mark.slow
def test_delegation_advisor_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    r = advise({"exploration_files": 30})
    expect("30 файлов разведки -> делегировать exploration",
           any(x["trigger"] == "repository_wide_exploration" for x in r))
    expect("возвращается сводка, не сырьё",
           r and "релевантные пути" in r[0]["return_to_main"]
           and "все прочитанные файлы" in r[0]["do_not_return"])
    expect("check валиден", check(r) == [])
    r = advise({"exploration_files": 3})
    expect("3 файла -> НЕ делегировать (ниже порога)", not r)
    r = advise({"compare_files": 6})
    expect("сравнение 6 файлов -> делегировать", any(x["trigger"] == "many_file_comparison" for x in r))
    r = advise({"log_lines": 2000})
    expect("большой лог -> делегировать", any(x["trigger"] == "large_log_analysis" for x in r))
    r = advise({"external_research": True, "independent_review": True, "mass_mechanical_inspection": True})
    expect("research/review/mechanical -> 3 рекомендации", len(r) == 3)
    expect("research делегируется research-сабагенту",
           any(x["delegate_to"] == "research-сабагент" for x in r))
    expect("пустые сигналы -> нет рекомендаций", advise({}) == [])
    # честность: рекомендация не может возвращать сырьё
    bad = [{"trigger": "x", "return_to_main": ["все прочитанные файлы"], "do_not_return": []}]
    expect("check ловит возврат сырья", check(bad) != [])

    assert ok, "перенесённый селфтест delegation_advisor: см. строки FAIL в выводе"
