"""Селфтест lifecycle_intent, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from lifecycle_intent import (  # noqa: F401 — имена, которые использует тело
    ALL_STATES,
    derive,
    intent_to_lifecycle,
    validate_transition,
)


@pytest.mark.slow
def test_lifecycle_intent_selftest():
    """Selftest: контракты и логика derive."""
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    # 1. derive: draft без evidence → discovery
    expect("derive: draft без evidence → discovery",
           derive("draft") == "discovery")

    # 2. derive: draft с evidence → implementation
    expect("derive: draft с evidence → implementation",
           derive("draft", has_evidence=True) == "implementation")

    # 3. derive: done без PR → implementation
    expect("derive: done без PR → implementation",
           derive("done") == "implementation")

    # 4. derive: done с PR → review
    expect("derive: done с PR → review",
           derive("done", has_pr=True) == "review")

    # 5. derive: done с merged PR → delivery
    expect("derive: done с merged PR → delivery",
           derive("done", has_pr=True, pr_merged=True) == "delivery")

    # 6. derive: done с receipt → completed
    expect("derive: done с receipt → completed",
           derive("done", has_receipt=True) == "completed")

    # 7. derive: needs_human_decision → review
    expect("derive: needs_human_decision → review",
           derive("needs_human_decision") == "review")

    # 8. derive: blocked без evidence → discovery
    expect("derive: blocked без evidence → discovery",
           derive("blocked") == "discovery")

    # 9. derive: blocked с evidence → implementation
    expect("derive: blocked с evidence → implementation",
           derive("blocked", has_evidence=True) == "implementation")

    # 10. derive: terminal state имеет приоритет
    expect("derive: cancelled имеет приоритет",
           derive("done", has_receipt=True, terminal_state="cancelled") == "cancelled")

    # 11. validate_transition: допустимые переходы
    expect("validate_transition: discovery → implementation допустим",
           validate_transition("discovery", "implementation") is True)
    expect("validate_transition: implementation → review допустим",
           validate_transition("implementation", "review") is True)
    expect("validate_transition: review → delivery допустим",
           validate_transition("review", "delivery") is True)
    expect("validate_transition: delivery → completed допустим",
           validate_transition("delivery", "completed") is True)

    # 12. validate_transition: недопустимые переходы
    expect("validate_transition: completed → discovery запрещён",
           validate_transition("completed", "discovery") is False)
    expect("validate_transition: cancelled → implementation запрещён",
           validate_transition("cancelled", "implementation") is False)

    # 13. intent_to_lifecycle: маппинг CLI intents
    expect("intent_to_lifecycle: discuss → discovery",
           intent_to_lifecycle("discuss") == "discovery")
    expect("intent_to_lifecycle: run → implementation",
           intent_to_lifecycle("run") == "implementation")
    expect("intent_to_lifecycle: review → review",
           intent_to_lifecycle("review") == "review")
    expect("intent_to_lifecycle: resume → None",
           intent_to_lifecycle("resume") is None)

    # 14. ALL_STATES содержит все стадии
    expect("ALL_STATES содержит discovery, implementation, review, delivery, completed",
           all(s in ALL_STATES for s in ("discovery", "implementation", "review", "delivery", "completed")))
    expect("ALL_STATES содержит терминальные cancelled, superseded, abandoned",
           all(s in ALL_STATES for s in ("cancelled", "superseded", "abandoned")))

    assert ok, "перенесённый селфтест lifecycle_intent: см. строки FAIL в выводе"
