# -*- coding: utf-8 -*-
"""Контракт: тест не сводит воронкой десятки проверок в один assert (по образцу test_suite_asserts).

Работа `selftests-are-granular-not-monolithic`, цель `green-means-checked`.

НАХОДКА. Прополка (`unit-weeding-is-mutation-proven`) убрала монолитные `*_selftest` — одна
мега-функция на модуль, где проверки шли через локальный `expect()`-накопитель (`nonlocal ok` /
`print` PASS-FAIL), а настоящий assert один в конце:

    @pytest.mark.slow
    def test_validate_claims_selftest():
        ok = True
        def expect(name, cond):
            nonlocal ok
            ok = ok and cond
            print(f"{'PASS' if cond else 'FAIL'} {name}")
        ...
        expect("file-exists проходит", res["file-ok"] == "ok")   # десятки таких
        ...
        assert ok                                                 # один финальный

Диагностика такого файла — ОДИН красный на весь модуль; по поведению ярусами не читается. Файлов не
осталось (0), но ФОРМА могла бы вернуться — этот контракт её ловит, чтобы регрессия поймалась в тот
же день, а не через год (ровно причина, по которой стоит `test_suite_asserts`).

ДВА ИНВАРИАНТА:
  1. Ни один тест-файл не носит ретированный суффикс `_selftest.py` (конвенция снята — AGENTS.md).
  2. Ни одна тест-функция не funnel-ит >= THRESHOLD проверок через soft-помощник-накопитель в один
     assert. Soft-помощник = вложенный `def` без своего `assert` и без value-return, который
     РЕГИСТРИРУЕТ результат (`nonlocal` / `list.append` / `print`) и вызывается с булевым
     условием-аргументом (`Compare` / `BoolOp` / `not ...`).

ПОЧЕМУ ФОРМА, А НЕ ДЛИНА. Длинный тест бывает законным (`test_delivery_footprint`). Ловим воронку,
а не размер: помощник, который САМ содержит `assert`, РАЗРЕШЁН (падает на точной проверке) — он
гранулярен по сути; запрещён soft-накопитель, funnel-ящий в один терминальный assert. Порог 5 при
замере 2026-08-28: максимум таких вызовов в текущем наборе — 1 (монолит имел десятки), запас огромен.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract]

KIT = Path(__file__).resolve().parents[2]
TEST_DIRS = ("tests/unit", "tests/contracts")
# Порог воронки: сколько условие-проверок через soft-накопитель делают тест монолитом. Замер
# 2026-08-28: легитимный максимум в наборе — 1; монолиты имели десятки. 5 — с большим запасом.
FUNNEL_THRESHOLD = 5


def _test_files():
    for d in TEST_DIRS:
        for p in sorted((KIT / d).glob("test_*.py")):
            yield p


def _is_condition(node: ast.AST) -> bool:
    """Аргумент-условие: сравнение, булева связка или `not ...` — то, что передают в expect()."""
    return isinstance(node, (ast.Compare, ast.BoolOp)) or (
        isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not))


def _soft_accumulators(fn: ast.FunctionDef) -> dict[str, ast.FunctionDef]:
    """Вложенные помощники, которые РЕГИСТРИРУЮТ результат вместо assert: nonlocal/append/print,
    без своего assert и без value-return. Билдер (возвращает значение) и assert-помощник — не они."""
    out: dict[str, ast.FunctionDef] = {}
    for node in ast.walk(fn):
        if isinstance(node, ast.FunctionDef) and node is not fn:
            body = list(ast.walk(node))
            if any(isinstance(x, ast.Assert) for x in body):
                continue                                   # сам ассёртит — гранулярен по сути
            if any(isinstance(x, ast.Return) and x.value is not None for x in body):
                continue                                   # билдер: возвращает значение
            records = (
                any(isinstance(x, ast.Nonlocal) for x in body)
                or any(isinstance(x, ast.Attribute) and x.attr == "append" for x in body)
                or any(isinstance(x, ast.Call) and isinstance(x.func, ast.Name)
                       and x.func.id == "print" for x in body))
            if records:
                out[node.name] = node
    return out


def _condition_calls(fn: ast.FunctionDef, name: str) -> int:
    return sum(1 for n in ast.walk(fn)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == name
               and any(_is_condition(a) for a in n.args))


def _funnels_in_source(src: str):
    """(тест-функция, помощник, число условие-вызовов) для воронок выше порога в исходнике."""
    tree = ast.parse(src)
    hits = []
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and fn.name.startswith("test"):
            for hname in _soft_accumulators(fn):
                c = _condition_calls(fn, hname)
                if c >= FUNNEL_THRESHOLD:
                    hits.append((fn.name, hname, c))
    return hits


def _funnels(path: Path):
    return _funnels_in_source(path.read_text(encoding="utf-8"))


@pytest.mark.contract
def test_no_test_file_carries_the_retired_selftest_suffix():
    """Суффикс `_selftest.py` ретирован (прополка 2026-08, AGENTS.md). Новый файл с ним — регрессия
    к монолитной конвенции: гейт называет её по имени, а не ждёт год."""
    stray = sorted(str(p.relative_to(KIT)) for p in _test_files() if p.stem.endswith("_selftest"))
    assert not stray, (
        f"тест-файлы с ретированным суффиксом _selftest: {stray}. Конвенция снята — назови файл "
        f"test_<module>.py и разложи поведение по гранулярным тестам (AGENTS.md).")


@pytest.mark.contract
def test_no_test_funnels_many_checks_into_one_assert():
    """Мега-функция с воронкой через soft-накопитель — монолит: один красный на весь модуль. Каждая
    проверка обязана быть отдельным assert (или падать в помощнике, который сам ассёртит)."""
    offenders = []
    for p in _test_files():
        for fn, helper, c in _funnels(p):
            offenders.append(f"{p.relative_to(KIT)}::{fn} — {c} условий через {helper}() в один assert")
    assert not offenders, (
        "тест сводит десятки проверок в один assert (монолитная форма *_selftest):\n  "
        + "\n  ".join(offenders)
        + "\nРазложи: одно поведение = один именованный тест с настоящим assert. Помощник, который "
        "САМ ассёртит, разрешён — soft-накопитель (nonlocal/append/print) в один финальный assert нет.")


# ─── fail-closed: у детектора есть зубы (иначе гейт непробиваем по построению) ────────────────────

_MONOLITH = '''
import pytest
@pytest.mark.slow
def test_thing_selftest():
    ok = True
    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(name)
    expect("a", res["a"] == 1)
    expect("b", res["b"] == 2)
    expect("c", res["c"] == 3)
    expect("d", res["d"] == 4)
    expect("e", res["e"] == 5)
    assert ok
'''

_GRANULAR = '''
def test_a():
    assert res["a"] == 1
def test_b():
    assert res["b"] == 2
'''

_ASSERT_HELPER = '''
def test_with_a_real_helper():
    def check(cond, msg):
        assert cond, msg          # сам ассёртит — гранулярен по сути, не soft-накопитель
    check(res["a"] == 1, "a")
    check(res["b"] == 2, "b")
    check(res["c"] == 3, "c")
    check(res["d"] == 4, "d")
    check(res["e"] == 5, "e")
    check(res["f"] == 6, "f")
'''


@pytest.mark.contract
def test_detector_catches_a_synthetic_monolith():
    """FAIL-CLOSED: воронка из 5 expect() через nonlocal-накопитель обязана ловиться — иначе гейт
    зелёный на том самом дефекте, ради которого стоит."""
    hits = _funnels_in_source(_MONOLITH)
    assert any(h[0] == "test_thing_selftest" and h[2] >= FUNNEL_THRESHOLD for h in hits), hits


@pytest.mark.contract
def test_detector_does_not_flag_granular_tests():
    """Точность: гранулярные тесты с прямыми assert не ловятся (иначе гейт бесполезен)."""
    assert _funnels_in_source(_GRANULAR) == []


@pytest.mark.contract
def test_detector_allows_a_helper_that_asserts_itself():
    """Точность: помощник, который САМ ассёртит (падает на точной проверке), разрешён и вызванный
    много раз — он гранулярен по сути, не soft-воронка."""
    assert _funnels_in_source(_ASSERT_HELPER) == []
