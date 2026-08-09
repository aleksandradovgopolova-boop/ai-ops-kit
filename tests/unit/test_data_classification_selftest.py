"""Селфтест data_classification, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from data_classification import (  # noqa: F401 — имена, которые использует тело
    DEMO,
    _load,
    _policy_class,
    classify,
    validate_policy,
)


@pytest.mark.slow
def test_data_classification_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    # marker НЕ понижает класс
    expect("marker 'public' НЕ понижает (base internal остаётся internal)",
           classify("# data-class: public\nx=1\n") == "internal")
    expect("marker 'confidential' ПОВЫШАЕТ (internal -> confidential)",
           classify("# data-class: confidential\nx=1\n") == "confidential")
    expect("секрет всегда secret, даже с marker public",
           classify("# data-class: public\nsk-ant-api03deadbeefcafe\n") == "secret")
    # policy авторитетна
    pol = {"schema_version": 1, "kind": "DataClassificationPolicy", "id": "DCP-001",
           "default_class": "internal", "strict_unknown": False,
           "rules": [{"path_prefix": "secrets/", "class": "secret"},
                     {"path_prefix": "src/private/", "class": "confidential"}]}
    expect("policy: secrets/x -> secret (без marker)", classify("y=1\n", "secrets/x.py", pol) == "secret")
    expect("policy: src/private/x -> confidential", classify("y=1\n", "src/private/x.py", pol) == "confidential")
    expect("policy: marker public на confidential-пути НЕ понижает",
           classify("# data-class: public\n", "src/private/x.py", pol) == "confidential")
    expect("policy: longest-prefix wins", _policy_class(
        {"rules": [{"path_prefix": "src/", "class": "internal"},
                   {"path_prefix": "src/private/", "class": "confidential"}]}, "src/private/a.py") == "confidential")
    # strict unknown -> deny (confidential)
    expect("strict + unknown path -> confidential (deny), не internal",
           classify("x=1\n", "weird/x.py", pol, strict=True) == "confidential")
    expect("не-strict + unknown -> internal", classify("x=1\n", "weird/x.py", pol) == "internal")

    # validate_policy
    expect("валидная policy проходит", validate_policy(pol) == [])
    expect("битый class в rule -> ошибка",
           any("class" in x for x in validate_policy({**pol, "rules": [{"path_prefix": "a/", "class": "vibes"}]})))
    expect("битый default_class -> ошибка", any("default_class" in x for x in validate_policy({**pol, "default_class": "x"})))
    if DEMO.is_dir():
        expect("реальный demo DCP валиден",
               all(validate_policy(_load(f)) == [] for f in sorted(DEMO.glob("DCP-*.yaml"))))

    assert ok, "перенесённый селфтест data_classification: см. строки FAIL в выводе"
