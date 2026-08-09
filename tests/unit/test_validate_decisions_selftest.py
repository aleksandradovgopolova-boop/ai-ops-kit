"""Селфтест validate_decisions, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_decisions import (  # noqa: F401 — имена, которые использует тело
    PKG,
    check,
    yaml,
)


@pytest.mark.slow
def test_validate_decisions_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    valid = {"schema_version": 1, "kind": "decisions-registry",
             "episodes": [{"id": "ep-1", "question": "q", "decision": "d", "reason": "r",
                           "reversibility": "two-way", "date": "2026-07-13"}],
             "principles": [{"id": "dp-1", "principle": "p", "scope": ["s"], "status": "ratified",
                             "confidence": "high", "recurrence_count": 3, "review_date": "2026-12-01",
                             "derived_from": ["ep-1"]}],
             "outcomes": [{"decision": "ep-1", "outcome": "ok"}]}
    e, w = check(valid)
    expect("валидный реестр без ошибок", e == [])

    e, _ = check({"principles": [{"id": "dp-x", "principle": "p", "scope": ["s"], "status": "retired",
                                  "confidence": "low", "recurrence_count": 1, "review_date": "2026-01-01",
                                  "derived_from": []}], "episodes": []})
    expect("retired без retired_reason -> ошибка", any("retired_reason" in x for x in e))

    e, _ = check({"principles": [{"id": "dp-y", "principle": "p", "scope": ["s"], "status": "ratified",
                                  "confidence": "high", "recurrence_count": 2, "review_date": "2026-01-01",
                                  "derived_from": ["ep-nope"]}], "episodes": []})
    expect("derived_from на несуществующий эпизод -> ошибка", any("ep-nope" in x for x in e))

    e, _ = check({"principles": [], "episodes": [
        {"id": "ep-z", "question": "q", "decision": "d", "reason": "r",
         "reversibility": "maybe", "date": "2026-07-13"}]})
    expect("невалидный reversibility -> ошибка", any("reversibility" in x for x in e))

    _, w = check({"principles": [{"id": "dp-w", "principle": "p", "scope": ["s"], "status": "ratified",
                                  "confidence": "high", "recurrence_count": 1, "review_date": "2026-12-01",
                                  "derived_from": []}], "episodes": []})
    expect("ratified из одного случая -> WARN калибровки", any("одного случая" in x for x in w))

    # реальный реестр кита
    reg = PKG / "decisions" / "registry.yaml"
    if reg.exists():
        e, _ = check(yaml.safe_load(reg.read_text(encoding="utf-8")))
        expect("реестр кита валиден", e == [])

    assert ok, "перенесённый селфтест validate_decisions: см. строки FAIL в выводе"
