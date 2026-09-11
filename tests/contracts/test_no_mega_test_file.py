# -*- coding: utf-8 -*-
"""Контракт: ни одного МЕГА-тест-файла в `tests/` сверх порога строк.

Работа #438 (продолжение серии разрезов монолитных тест-файлов).

НАХОДКА. Крупные тест-файлы копятся незаметно: каждая новая работа дописывает пару классов в
уже большой файл, пока он не станет непросматриваемым (навигация, конфликты слияния, ревью «в
одном assert»). Прошлые работы разрезали известные монолиты вручную; этот сторож держит планку,
чтобы новый мега-файл ловился в тот же день, а не спустя месяцы.

ИНВАРИАНТ (структурный, по числу строк). Ни один `tests/**/test_*.py` не длиннее ПОРОГА строк.
Порог зафиксирован ДАННЫМИ (`MAX_TEST_FILE_LINES`) с запасом над текущим максимумом.

ПОЧЕМУ НЕ ЧЕРЕЗ `validate_*`. Это чистая структурная проверка исходников тестов; registered-валидатор
в `ai_ops_kit/validation/` тянет реестровый каскад (package-surface, standalone-контракт, счётчики) —
здесь он не нужен. Место такой проверки — `tests/contracts/`, рядом с прочими структурными
контрактами (`test_no_monolith_funnel`, `test_no_unbounded_git`).
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract]

KIT = Path(__file__).resolve().parents[2]
TESTS = KIT / "tests"

# Потолок строк на один тест-файл. ОБОСНОВАНИЕ: после разреза #438 крупнейший тест-файл ~744 строки;
# 850 даёт ~14% запаса на органический рост существующих файлов, но краснеет на новом монолите
# (>850 — сигнал «пора резать по темам», как это уже делалось руками).
MAX_TEST_FILE_LINES = 850


def _line_count(text: str) -> int:
    """Число строк в тексте (перевод строки в конце не создаёт лишней пустой строки)."""
    return len(text.splitlines())


def _iter_test_files():
    for p in sorted(TESTS.rglob("test_*.py")):
        yield p, str(p.relative_to(TESTS)).replace("\\", "/")


def _oversized_test_files() -> dict[str, int]:
    """rel -> число строк для тест-файлов длиннее порога."""
    over = {}
    for path, rel in _iter_test_files():
        n = _line_count(path.read_text(encoding="utf-8"))
        if n > MAX_TEST_FILE_LINES:
            over[rel] = n
    return over


def test_no_mega_test_file():
    """Каждый tests/**/test_*.py не длиннее MAX_TEST_FILE_LINES строк."""
    offenders = _oversized_test_files()
    assert not offenders, (
        f"Мега-тест-файл сверх {MAX_TEST_FILE_LINES} строк — режь по поведенческим темам "
        "(behavior-preserving перенос классов в парный файл, общие хелперы в `_*_helpers.py`). "
        "Нарушения: " + "; ".join(f"{rel}={n}" for rel, n in sorted(offenders.items()))
    )


def test_detector_flags_oversized_synthetic():
    """Позитивный кейс: синтетический «файл» на 900 строк детектируется как превышение порога."""
    synthetic = "\n".join(f"# строка {i}" for i in range(900))
    assert _line_count(synthetic) == 900
    assert _line_count(synthetic) > MAX_TEST_FILE_LINES


def test_detector_passes_file_at_threshold():
    """Файл ровно на пороге нарушением НЕ считается (краснеет строго выше порога)."""
    at_threshold = "\n".join(f"# строка {i}" for i in range(MAX_TEST_FILE_LINES))
    assert _line_count(at_threshold) == MAX_TEST_FILE_LINES
    assert _line_count(at_threshold) <= MAX_TEST_FILE_LINES
