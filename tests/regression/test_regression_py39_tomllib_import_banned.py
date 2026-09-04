"""Regression: импорт stdlib новее объявленного пола ломает установку у пользователя.

ИСТОЧНИК. Полевой дефект v3.33.2: `import tomllib` попал в код, тест дистрибутива уронил джобу
CI на Python 3.9 (тогдашний объявленный пол). `tomllib` появился в stdlib только в 3.11 — у
пользователя со старым python это гарантированный ModuleNotFoundError ещё на импорте, а не
«стилистика». Запись `tomllib: (3, 11)` в `STDLIB_SINCE` до сих пор несёт этот комментарий
«поймано живьём».

СИМПТОМ. Модуль из будущей (относительно объявленного пола) stdlib валит импорт всего движка до
первой строки полезной работы у пользователя со старым python.

ЧТО КРАСНЕЕТ ПРИ РЕГРЕССЕ. `check_imports` — параметризованный полом guard: импорт stdlib-модуля,
появившегося ПОЗЖЕ пола, помечается; не позже — пропускается. Тесты пиннят именно этот механизм на
задокументированном случае tomllib. Если из `STDLIB_SINCE` убрать запись или перестать сравнивать
версию импорта с полом — тест краснеет.

Пол репозитория с тех пор поднят до 3.12 (3.9 снят как EOL, решение ep-2026-08-20-python-floor-3.12),
поэтому «живой» инвариант ниже привязан к ФАКТИЧЕСКОМУ полу из pyproject, а не к 3.9.

Угол НОВЫЙ относительно unit-слоя: `tests/unit/test_validate_python_compat.py` покрывает только
`check_source` (union-аннотации); запрет импортов из будущей stdlib он не трогает.
"""
from __future__ import annotations

import pytest

from validate_python_compat import PKG, check_imports, declared_floor, scan


@pytest.mark.regression
def test_tomllib_import_is_flagged_on_39_floor():
    """При поле 3.9 `import tomllib` помечен: строка, модуль, версия появления."""
    src = "import tomllib\n\ndata = tomllib.loads('')\n"
    flagged = check_imports(src, floor=(3, 9), filename="offender.py")
    assert flagged == [(1, "tomllib", "3.11")], flagged


@pytest.mark.regression
def test_tomllib_import_is_allowed_when_floor_is_311():
    """Тот же импорт при поднятом поле 3.11 — не нарушение (проверка следует декларации пола)."""
    src = "import tomllib\n"
    assert check_imports(src, floor=(3, 11), filename="ok.py") == []


@pytest.mark.regression
def test_from_import_of_future_stdlib_is_also_flagged():
    """`from graphlib import ...` тоже ловится: forma import значения не меняет."""
    src = "from graphlib import TopologicalSorter\n"
    flagged = check_imports(src, floor=(3, 8), filename="offender.py")
    assert (1, "graphlib", "3.9") in flagged, flagged


@pytest.mark.regression
def test_real_package_reads_floor_from_pyproject_and_is_clean():
    """Живой инвариант: пол берётся из pyproject (не зашит), и пакет чист от импортов из будущей stdlib.

    Это защита от того самого класса поля-дефекта: если кто-то внесёт в реальный код кита stdlib-модуль
    новее объявленного пола, `scan` вернёт непустой список и тест покраснеет. Пол сверяем с фактическим
    (>= 3.12 — 3.9 снят), а не хардкодим старое значение.
    """
    floor = declared_floor(PKG)
    assert floor >= (3, 12), floor          # следует pyproject requires-python, не зашито
    assert scan(PKG) == []
