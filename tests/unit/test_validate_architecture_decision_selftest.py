"""Селфтест validate_architecture_decision, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_architecture_decision import (  # noqa: F401 — имена, которые использует тело
    SCHEMA,
    STATUS,
    check,
    json,
)


@pytest.mark.slow
def test_validate_architecture_decision_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    # эталон из примера схемы должен быть валиден
    ex = json.loads(SCHEMA.read_text(encoding="utf-8"))["examples"][0]
    expect("пример из схемы валиден", check(ex) == [])

    expect("нет negative-последствий -> ошибка (издержки скрыты)",
           any("negative" in x for x in check({**ex, "consequences": {"positive": ["x"], "negative": []}})))
    expect("битый id -> ошибка", any("id" in x for x in check({**ex, "id": "ADR1"})))
    expect("неизвестный status -> ошибка", any("status" in x for x in check({**ex, "status": "done"})))
    expect("superseded без superseded_by -> ошибка",
           any("superseded_by" in x for x in check({**ex, "status": "superseded"})))
    expect("superseded с superseded_by -> валиден",
           check({**ex, "status": "superseded", "superseded_by": "ADR-002"}) == [])
    expect("битый quality_attribute -> ошибка",
           any("attribute" in x for x in check({**ex,
               "quality_attributes": [{"attribute": "vibes", "effect": "improves"}]})))
    expect("битый ui_impact -> ошибка", any("ui_impact" in x for x in check({**ex, "ui_impact": "huge"})))
    expect("ui_impact=user_facing валиден (согласовано с gate_policy)",
           check({**ex, "ui_impact": "user_facing"}) == [])
    expect("пустой context -> ошибка", any("context" in x for x in check({**ex, "context": "  "})))

    # согласованность enum'ов со схемой (drift-guard)
    sch = json.loads(SCHEMA.read_text(encoding="utf-8"))
    expect("enum status == схема (нет дрейфа)",
           set(sch["properties"]["status"]["enum"]) == STATUS)

    assert ok, "перенесённый селфтест validate_architecture_decision: см. строки FAIL в выводе"
