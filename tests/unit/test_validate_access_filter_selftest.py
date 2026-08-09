"""Селфтест validate_access_filter, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_access_filter import (  # noqa: F401 — имена, которые использует тело
    DEMO,
    SCHEMA,
    _load,
    check,
    json,
)


@pytest.mark.slow
def test_validate_access_filter_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    ex = json.loads(SCHEMA.read_text(encoding="utf-8"))["examples"][0]
    expect("пример из схемы валиден", check(ex) == [])
    expect("реальный examples/access-filter-demo целостен",
           all(check(_load(f)) == [] for f in sorted(DEMO.glob("AFP-*.yaml"))) if DEMO.is_dir() else True)
    expect("filter_stage != before_retrieval -> ошибка",
           any("before_retrieval" in x for x in check({**ex, "filter_stage": "after"})))
    expect("default_deny=false -> ошибка",
           any("default_deny" in x for x in check({**ex, "default_deny": False})))
    # роль без правила
    less = {**ex, "rules": ex["rules"][:4]}
    expect("роль без правила доступа -> ошибка (никакой retrieval без filter)",
           any("нет правила доступа" in x for x in check(less)))
    # secret в allowed
    sec = {**ex, "rules": [{**ex["rules"][0], "allowed_classes": ["public", "secret"]}] + ex["rules"][1:]}
    expect("secret в allowed_classes -> ошибка (секреты не в context)",
           any("секреты не входят" in x for x in check(sec)))
    # класс не объявлен
    und = {**ex, "data_classes": ["public", "internal"],
           "rules": [{"role": "planner", "allowed_classes": ["confidential"]}] + [
               {"role": r, "allowed_classes": ["public"]} for r in
               ["executor", "ui_reviewer", "security_reviewer", "integration"]]}
    expect("класс вне data_classes -> ошибка",
           any("не объявлен в data_classes" in x for x in check(und)))
    expect("битый context_architecture -> ошибка",
           any("context_architecture" in x for x in check({**ex, "context_architecture": "CAD1"})))
    expect("дубль правила на роль -> ошибка",
           any(">1 правила" in x for x in check({**ex, "rules": ex["rules"] + [ex["rules"][0]]})))

    assert ok, "перенесённый селфтест validate_access_filter: см. строки FAIL в выводе"
