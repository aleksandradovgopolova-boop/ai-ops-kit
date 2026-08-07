"""Селфтест validate_plan_artifact, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_plan_artifact import (  # noqa: F401 — имена, которые использует тело
    check,
    provided_evidence,
)


@pytest.mark.slow
def test_validate_plan_artifact_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    good = {"schema_version": 1, "kind": "plan-artifact", "workitem_id": "feat-1",
            "work_packages": [{"id": "WP1", "summary": "фильтр в контроллере", "depends_on": []},
                              {"id": "WP2", "summary": "тест фильтра", "depends_on": ["WP1"]}],
            "write_scope": ["src/catalog/"]}
    expect("валидный план -> без ошибок", check(good) == [])
    expect("валидный -> закрывает три required_evidence",
           provided_evidence(good) == ["work_packages", "dependencies", "write_scope"])
    expect("пустой work_packages -> ошибка",
           check({"schema_version": 1, "kind": "plan-artifact", "work_packages": [],
                  "write_scope": ["src/"]}) != [])
    expect("отсутствует write_scope -> ошибка",
           any("write_scope" in e for e in check({"schema_version": 1, "kind": "plan-artifact",
               "work_packages": [{"id": "WP1", "summary": "x", "depends_on": []}]})))
    expect("depends_on не список -> ошибка",
           any("depends_on" in e for e in check({"schema_version": 1, "kind": "plan-artifact",
               "work_packages": [{"id": "WP1", "summary": "x", "depends_on": "WP0"}],
               "write_scope": ["src/"]})))
    expect("depends_on на несуществующий WP -> ошибка (целостность)",
           any("несуществующ" in e for e in check({"schema_version": 1, "kind": "plan-artifact",
               "work_packages": [{"id": "WP1", "summary": "x", "depends_on": ["WPX"]}],
               "write_scope": ["src/"]})))
    expect("невалидный -> evidence пуст",
           provided_evidence({"kind": "plan-artifact", "work_packages": []}) == [])
    # регрессия (live full-stack прогон): author вернул depends_on как список DICT'ов -> раньше краш
    # `d not in set` (unhashable type: dict). Теперь — ЧЕСТНАЯ ошибка валидации, не исключение.
    _dep_dict = {"schema_version": 1, "kind": "plan-artifact",
                 "work_packages": [{"id": "WP1", "summary": "x", "depends_on": [{"id": "WP0"}]}],
                 "write_scope": ["src/"]}
    try:
        _e_dep = check(_dep_dict)
        expect("depends_on содержит dict -> ошибка (не краш unhashable)",
               any("строкой-id" in e for e in _e_dep))
    except TypeError:
        expect("depends_on содержит dict -> ошибка (не краш unhashable)", False)
    # регрессия: id work_package не строка (dict) -> раньше краш `in set`; теперь ошибка
    _id_dict = {"schema_version": 1, "kind": "plan-artifact",
                "work_packages": [{"id": {"nested": 1}, "summary": "x", "depends_on": []}],
                "write_scope": ["src/"]}
    try:
        _e_id = check(_id_dict)
        expect("id work_package не строка -> ошибка (не краш unhashable)",
               any("id должен быть строкой" in e for e in _e_id))
    except TypeError:
        expect("id work_package не строка -> ошибка (не краш unhashable)", False)

    assert ok, "перенесённый селфтест validate_plan_artifact: см. строки FAIL в выводе"
