"""Защёлка на инвариант рантайм-зависимостей пакета: ровно {pyyaml}.

ИНВАРИАНТ (AGENTS.md, «Правила»): «Никаких новых зависимостей без явного решения: Python-инструменты
работают на stdlib + pyyaml». До этой защёлки инвариант держался ТОЛЬКО прозой и дисциплиной ревью:
новая строка в `[project].dependencies` или в runtime-секции `requirements.txt` прошла бы молча,
CI бы не покраснел. Здесь проза превращена в машинную защёлку — новая рантайм-зависимость краснит
тест, а не проезжает незамеченной.

ГРАНИЦА С СОСЕДЯМИ. `tests/unit/test_validate_supply_chain.py` проверяет SCP-артефакты (политику
пиннинга внешних моделей/MCP) — это ДРУГОЙ предмет, не зависимости самого Python-пакета; дубля нет.

ПОЧЕМУ tomllib из stdlib безопасен. Манифест читаем `tomllib` (stdlib с 3.11). Это допустимо только
потому, что объявленный пол пакета >= 3.11 — здесь мы проверяем это ПРОДУКТОВЫМ кодом
(`validate_python_compat.declared_floor`), а не предполагаем. Запрет импортов stdlib новее пола
держит `tests/regression/test_regression_py39_tomllib_import_banned.py`.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from validate_python_compat import PKG, declared_floor

REQUIREMENTS = PKG / "requirements.txt"
PYPROJECT = PKG / "pyproject.toml"

EXPECTED_RUNTIME_DEPS = {"pyyaml"}


def _normalize(spec: str) -> str:
    """Имя пакета без версии/маркеров/экстра/пробелов, в нижнем регистре.

    `PyYAML>=6.0` -> `pyyaml`; `pyyaml; python_version>='3.11'` -> `pyyaml`.
    """
    name = spec.strip()
    for sep in (";", "[", "==", ">=", "<=", "~=", "!=", ">", "<", "="):
        name = name.split(sep, 1)[0]
    return name.strip().lower()


def _pyproject_runtime_deps() -> set[str]:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return {_normalize(d) for d in data["project"]["dependencies"]}


def _requirements_runtime_deps() -> set[str]:
    deps: set[str] = set()
    for raw in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Опциональные (dev/test) строки в requirements.txt закомментированы — сюда попадают
        # только реальные runtime-строки.
        deps.add(_normalize(line))
    return deps


@pytest.mark.unit
class TestRuntimeDependenciesLocked:
    """Рантайм-поверхность зависимостей = ровно {pyyaml} в обоих манифестах."""

    def test_declared_python_floor_makes_stdlib_tomllib_safe(self):
        """Пол пакета >= 3.11 — иначе парсить манифест stdlib-tomllib было бы нельзя.

        Behavioral: зовём продуктовый `declared_floor` над реальным pyproject кита.
        """
        assert declared_floor(PKG) >= (3, 11), declared_floor(PKG)

    def test_pyproject_runtime_dependencies_are_exactly_pyyaml(self):
        """`[project].dependencies` после нормализации == {"pyyaml"} — новая зависит краснит тест."""
        assert _pyproject_runtime_deps() == EXPECTED_RUNTIME_DEPS, _pyproject_runtime_deps()

    def test_requirements_runtime_lines_reduce_to_pyyaml(self):
        """Не-комментарные runtime-строки requirements.txt сводятся к единственному пакету pyyaml."""
        assert _requirements_runtime_deps() == EXPECTED_RUNTIME_DEPS, _requirements_runtime_deps()

    def test_two_manifests_agree_on_runtime_surface(self):
        """pyproject и requirements не должны разъезжаться по рантайм-поверхности."""
        assert _pyproject_runtime_deps() == _requirements_runtime_deps()
