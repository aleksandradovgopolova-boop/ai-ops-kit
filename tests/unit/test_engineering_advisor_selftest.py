"""Селфтест engineering_advisor, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from engineering_advisor import (  # noqa: F401 — имена, которые использует тело
    advise,
    check,
)


@pytest.mark.slow
def test_engineering_advisor_selftest():
    """Selftest: контракт + честность (unavailable не как 0)."""
    import tempfile
    ok = True

    # 1. advise на пустом репо — не падает, возвращает рекомендации
    with tempfile.TemporaryDirectory() as td:
        result = advise(td)
        if result.get("kind") == "EngineeringAdvice":
            print("PASS engineering_advisor: advise на пустом репо -> EngineeringAdvice")
        else:
            ok = False
            print(f"FAIL engineering_advisor: kind={result.get('kind')}")
        # 2. check валиден
        errors = check(result)
        if not errors:
            print("PASS engineering_advisor: check(valid) -> []")
        else:
            ok = False
            print(f"FAIL engineering_advisor: check(valid) -> {errors}")
        # 3. recommendations — список
        recs = result.get("recommendations", [])
        if isinstance(recs, list):
            print(f"PASS engineering_advisor: {len(recs)} рекомендаций")
        else:
            ok = False
            print("FAIL engineering_advisor: recommendations не список")
        # 4. summary — строка
        if isinstance(result.get("summary"), str):
            print(f"PASS engineering_advisor: summary = '{result['summary']}'")
        else:
            ok = False
            print("FAIL engineering_advisor: summary не строка")

    # 5. check с невалидными данными -> errors
    errors = check({"kind": "wrong"})
    if errors:
        print("PASS engineering_advisor: check(invalid) -> errors")
    else:
        ok = False
        print("FAIL engineering_advisor: check(invalid) должен вернуть errors")

    assert ok, "перенесённый селфтест engineering_advisor: см. строки FAIL в выводе"
