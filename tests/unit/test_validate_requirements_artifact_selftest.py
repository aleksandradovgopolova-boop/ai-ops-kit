"""Селфтест validate_requirements_artifact, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_requirements_artifact import (  # noqa: F401 — имена, которые использует тело
    check,
    provided_evidence,
)


@pytest.mark.slow
def test_validate_requirements_artifact_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    good = {"schema_version": 1, "kind": "requirements-artifact", "workitem_id": "feat-1",
            "requirements": [{"id": "R1", "statement": "фильтр по статусу сужает список",
                              "acceptance": ["when статус=paid then только оплаченные"]}]}
    expect("валидный артефакт -> без ошибок", check(good) == [])
    expect("валидный -> закрывает оба required_evidence",
           provided_evidence(good) == ["testable_requirements", "acceptance_scenarios"])
    expect("пустой requirements -> ошибка + evidence пуст",
           check({"schema_version": 1, "kind": "requirements-artifact", "requirements": []}) != []
           and provided_evidence({"kind": "requirements-artifact", "requirements": []}) == [])
    expect("требование без acceptance -> ошибка (нет сценария приёмки)",
           any("acceptance" in e for e in check({"schema_version": 1, "kind": "requirements-artifact",
               "requirements": [{"id": "R1", "statement": "x"}]})))
    expect("требование без statement -> ошибка",
           any("statement" in e for e in check({"schema_version": 1, "kind": "requirements-artifact",
               "requirements": [{"id": "R1", "acceptance": ["a"]}]})))
    expect("неверный kind -> ошибка", any("kind" in e for e in check({"kind": "x", "requirements": []})))
    expect("дублирующийся id -> ошибка",
           any("дубл" in e for e in check({"schema_version": 1, "kind": "requirements-artifact",
               "requirements": [{"id": "R1", "statement": "a", "acceptance": ["s"]},
                                {"id": "R1", "statement": "b", "acceptance": ["s"]}]})))

    assert ok, "перенесённый селфтест validate_requirements_artifact: см. строки FAIL в выводе"
