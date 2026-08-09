"""Селфтест validate_context_architecture, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_context_architecture import (  # noqa: F401 — имена, которые использует тело
    CANON,
    SCHEMA,
    check,
    json,
)


@pytest.mark.slow
def test_validate_context_architecture_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    ex = json.loads(SCHEMA.read_text(encoding="utf-8"))["examples"][0]
    expect("пример из схемы валиден", check(ex) == [])
    expect("нарушение порядка pipeline -> ошибка",
           any("порядк" in x for x in check({**ex,
               "retrieval_pipeline": ["full_text", "repository_graph", "budgeted_role_view"]})))
    expect("accepted начинает с semantic_fallback -> ошибка",
           any("сначала вектор" in x for x in check({**ex,
               "retrieval_pipeline": ["semantic_fallback", "reranking", "budgeted_role_view"]})))
    expect("accepted без инварианта -> ошибка",
           any("exact_revision_binding" in x for x in check({**ex,
               "invariants": {**ex["invariants"], "exact_revision_binding": False}})))
    expect("accepted без всех role_views -> ошибка",
           any("role_views" in x for x in check({**ex, "role_views": ["planner"]})))
    expect("accepted с неполным cache_key -> ошибка",
           any("cache_key" in x for x in check({**ex, "cache_key": ["repository", "sha"]})))
    expect("accepted без builds_on context_compiler -> ошибка",
           any("context_compiler" in x for x in check({**ex, "builds_on": "новая vector-db"})))
    expect("proposed мягче: неполные role_views допустимы",
           check({**ex, "status": "proposed", "role_views": ["planner"]}) == [])
    expect("битый id -> ошибка", any("id" in x for x in check({**ex, "id": "CAD1"})))
    expect("enum stage == схема (нет дрейфа)",
           set(json.loads(SCHEMA.read_text(encoding="utf-8"))["properties"]["retrieval_pipeline"]
               ["items"]["enum"]) == set(CANON))

    assert ok, "перенесённый селфтест validate_context_architecture: см. строки FAIL в выводе"
