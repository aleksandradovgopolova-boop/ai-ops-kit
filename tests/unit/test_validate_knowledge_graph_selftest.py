"""Селфтест validate_knowledge_graph, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_knowledge_graph import (  # noqa: F401 — имена, которые использует тело
    Path,
    load_dictionary,
    make_demo,
    tempfile,
    validate_graph,
)


@pytest.mark.slow
def test_validate_knowledge_graph_selftest():
    ok = True
    types, rels = load_dictionary()

    def expect(name, errs, want_errors):
        nonlocal ok
        good = bool(errs) == want_errors
        ok = ok and good
        print(f"{'PASS' if good else 'FAIL'} {name}" + ("" if good else f" -> {errs}"))

    with tempfile.TemporaryDirectory() as td:
        expect("валидный граф", validate_graph(make_demo(Path(td) / "a"), types, rels), False)
        expect("dangling reference -> fail",
               validate_graph(make_demo(Path(td) / "b", dangling=True), types, rels), True)
        expect("недопустимая связь -> fail",
               validate_graph(make_demo(Path(td) / "c", bad_relation=True), types, rels), True)

    assert ok, "перенесённый селфтест validate_knowledge_graph: см. строки FAIL в выводе"
