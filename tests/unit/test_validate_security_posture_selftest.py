"""Селфтест validate_security_posture, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_security_posture import (  # noqa: F401 — имена, которые использует тело
    PKG,
    POSTURE,
    check,
    yaml,
)


@pytest.mark.slow
def test_validate_security_posture_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    data = yaml.safe_load(POSTURE.read_text(encoding="utf-8"))
    e, tally = check(data, PKG)
    expect("реальная постура: форма валидна и evidence резолвится", e == [])
    expect("покрыты все 13 областей", len(data.get("areas") or []) == 13)

    bad = {"areas": [{"id": "x", "title": "t", "status": "выдумка", "severity": "high",
                      "evidence": ["nope/missing.md"]}]}
    e2, _ = check(bad, PKG)
    expect("невалидный status -> ошибка", any("status" in x for x in e2))
    expect("битый evidence-путь -> ошибка (drift)", any("не резолвится" in x for x in e2))

    assert ok, "перенесённый селфтест validate_security_posture: см. строки FAIL в выводе"
