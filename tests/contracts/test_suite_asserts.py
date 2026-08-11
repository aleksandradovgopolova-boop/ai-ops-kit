"""Контракт набора тестов: тест обязан УТВЕРЖДАТЬ, а не возвращать (ревизия 2026-08-11).

НАХОДКА, которую этот файл закрывает. Перенос селфтестов из продакшн-модулей в pytest (v3.30)
оставил в пяти обёртках `return` вместо `assert`:

    def test_validate_pipeline_e2e_selftest():
        return main([])                 # <- код возврата валидатора
        assert ok, "..."                # <- недостижимо, мёртвая строка

pytest на непустой `return` из теста отвечает ПРЕДУПРЕЖДЕНИЕМ (PytestReturnNotNoneWarning), а
тест считает пройденным. То есть `main([]) == 1` — упавший валидатор — давал зелёный тест.
Так были фактически отключены четыре валидатора (container_delivery, pipeline_e2e,
product_qualification, stack_qualification) и селфтест инвариантов: их можно было сломать,
и 1830 тестов оставались зелёными. Ровно тот класс «ложный green», против которого стоит
fail-closed — только внутри самой сети проверок.

Почему проверка структурная, а не `filterwarnings = error`. Категория
`PytestReturnNotNoneWarning` появилась в pytest 7.2, а объявленный пол — `pytest>=7.0`:
запись в `pytest.ini` упала бы на нижней границе поддержки при разборе конфига. Разбор AST
работает на любом pytest и не зависит от того, включил ли кто-то предупреждения.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract]

TESTS_ROOT = Path(__file__).resolve().parents[1]


def _test_functions(tree: ast.AST):
    """Функции-тесты: `test_*` на любом уровне (модуль или класс Test*)."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            yield node


def _returns_a_value(fn: ast.AST):
    """`return <выражение>` внутри тела теста, не считая вложенных функций.

    Вложенные `def`/`lambda` пропускаем намеренно: хелпер внутри теста возвращать значение
    обязан — предмет проверки только сам тест.
    """
    for node in ast.walk(fn):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node is not fn:
            continue
        if isinstance(node, ast.Return) and node.value is not None:
            yield node.lineno


def test_no_test_function_returns_a_value():
    """Ни один тест не возвращает значение: pytest его молча проглотит."""
    offenders = []
    for path in sorted(TESTS_ROOT.rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for fn in _test_functions(tree):
            # Вложенные функции обходим отдельно: ast.walk от модуля отдаёт их тоже, а нам
            # нужно тело именно теста — потому сверяем, что найденный return принадлежит ему.
            nested = {id(n) for f in ast.walk(fn)
                      if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) and f is not fn
                      for n in ast.walk(f)}
            for node in ast.walk(fn):
                if isinstance(node, ast.Return) and node.value is not None and id(node) not in nested:
                    offenders.append(f"{path.relative_to(TESTS_ROOT.parent)}:{node.lineno} {fn.name}")
    assert not offenders, (
        "тест возвращает значение вместо assert — pytest примет его за пройденный "
        "независимо от результата:\n  " + "\n  ".join(offenders))


def test_no_statements_after_return_in_tests():
    """`assert` после `return` — недостижимая проверка: она объявлена, но не исполняется."""
    offenders = []
    for path in sorted(TESTS_ROOT.rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for fn in _test_functions(tree):
            for i, stmt in enumerate(fn.body[:-1]):
                if isinstance(stmt, ast.Return):
                    dead = fn.body[i + 1]
                    offenders.append(
                        f"{path.relative_to(TESTS_ROOT.parent)}:{dead.lineno} "
                        f"{fn.name} (недостижимо после return на строке {stmt.lineno})")
    assert not offenders, (
        "в тесте есть код после return — он никогда не исполняется:\n  " + "\n  ".join(offenders))
