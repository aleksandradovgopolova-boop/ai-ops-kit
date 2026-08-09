"""Селфтест validate_regression_corpus, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_regression_corpus import (  # noqa: F401 — имена, которые использует тело
    DEFAULT_DIR,
    SCHEMA,
    check,
    check_registry,
    json,
    taxonomy,
)


@pytest.mark.slow
def test_validate_regression_corpus_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    ex = json.loads(SCHEMA.read_text(encoding="utf-8"))["examples"][0]
    expect("пример RC из схемы валиден", check(ex) == [])
    reg_errs, ids = check_registry(DEFAULT_DIR)
    expect(f"реальный regression-corpus целостен ({len(ids)} кейсов)", reg_errs == [])
    expect("status=fixed без fixed_version -> ошибка",
           any("fixed_version" in x for x in check({**ex, "status": "fixed", "fixed_version": None})))
    expect("status=fixed без regression_test -> ошибка",
           any("regression_test" in x for x in check({**ex, "regression_test": " "})))
    expect("status=open с fixed_version -> ошибка",
           any("open" in x for x in check({**ex, "status": "open", "fixed_version": "3.0.19"})))
    expect("неизвестный layer -> ошибка",
           any("affected_layer" in x for x in check({**ex, "affected_layer": "vibes"})))
    expect("битый failure_id -> ошибка", any("failure_id" in x for x in check({**ex, "failure_id": "RC1"})))
    # Вывод 3: повтор класса требует конструкцию (правило СРАБАТЫВАЕТ)
    expect("occurrences>=2 без on_repeat -> ошибка (рекомендации мало)",
           any("occurrences>=2" in x for x in check({**ex, "occurrences": 2})))
    expect("escalate_to_structural без structural_fix -> ошибка",
           any("structural_fix" in x for x in check({**ex, "occurrences": 2, "on_repeat": "escalate_to_structural"})))
    expect("повтор + escalate + конструкция -> валиден",
           check({**ex, "occurrences": 2, "on_repeat": "escalate_to_structural",
                  "structural_fix": "единственная функция apply_token + запрет прямого вызова линтером"}) == [])
    expect("occurrences=1 без on_repeat -> валиден (правило не срабатывает на одиночном)",
           check({**ex, "occurrences": 1}) == [])
    expect("битый on_repeat -> ошибка", any("on_repeat" in x for x in check({**ex, "on_repeat": "maybe"})))
    # таксономия непуста на реальном корпусе + несёт счётчики повторов
    tx = taxonomy(DEFAULT_DIR)
    expect("таксономия по слоям непуста", bool(tx["by_layer"]))
    expect("таксономия несёт repeated/structural счётчики",
           "repeated_classes" in tx and "escalated_to_structural" in tx)

    assert ok, "перенесённый селфтест validate_regression_corpus: см. строки FAIL в выводе"
