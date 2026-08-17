"""Версия линтера объявлена в одном значении, а не в трёх разных.

НАХОДКА (замер 12.08.2026). `.pre-commit-config.yaml` пинил ruff `v0.8.0`, а CI ставил
`pip install ruff` — то есть ПОСЛЕДНИЙ. Два разных линтера: «локально чисто» и «чисто в CI»
оказывались утверждениями про разные наборы правил.

Это не теория. Срез ратчета показал «7 мест» на моей версии, CI на своей нашёл восьмое —
`except (Конкретный, Exception)` в property-тесте, где кортеж с `Exception` делает конкретный тип
декоративным. Находка была НАСТОЯЩЕЙ: тест мог пройти при полностью сломанном бюджете. То есть
расхождение версий не просто шумело — оно прятало дефект от локального прогона.

Поэтому здесь охраняется не «версия достаточно новая», а СОВПАДЕНИЕ объявлений. Поднимать версию —
отдельный осознанный шаг: новая приносит новые правила и свою уборку.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[2]


def _hook_version() -> str:
    text = (KIT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    block = text.split("ruff-pre-commit", 1)
    assert len(block) == 2, "в .pre-commit-config.yaml больше нет ruff-pre-commit"
    m = re.search(r"rev:\s*v?([\d.]+)", block[1])
    assert m, "у хука ruff нет rev — версия не объявлена вовсе"
    return m.group(1)


def _ci_version() -> str:
    text = (KIT / ".github" / "workflows" / "package-quality.yml").read_text(encoding="utf-8")
    lines = [l for l in text.splitlines()
             if "pip install" in l and "ruff" in l and not l.strip().startswith("#")]
    assert lines, "в CI нет установки ruff"
    m = re.search(r"ruff==([\d.]+)", lines[0])
    assert m, (
        f"CI ставит ruff без пина версии — «чисто в CI» перестаёт совпадать с локальным: {lines[0].strip()}")
    return m.group(1)


def _dev_floor() -> str:
    text = (KIT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'"ruff>=([\d.]+)"', text)
    assert m, "в dev-зависимостях нет ruff"
    return m.group(1)


@pytest.mark.unit
def test_ci_and_hook_pin_the_same_ruff():
    hook, ci = _hook_version(), _ci_version()
    assert hook == ci, (
        f"хук пинит ruff {hook}, а CI ставит {ci} — «локально чисто» и «чисто в CI» это утверждения "
        f"про разные линтеры; именно так дефект в property-тесте прятался от локального прогона")


@pytest.mark.unit
def test_dev_floor_is_not_below_the_pin():
    """Нижняя граница dev-зависимости не ниже пина: иначе `pip install -e .[dev]` даст третий линтер."""
    floor, pin = _dev_floor(), _ci_version()
    to_tuple = lambda s: tuple(int(x) for x in s.split("."))  # noqa: E731 — локальный ключ сортировки
    assert to_tuple(floor) >= to_tuple(pin), (
        f"dev ставит ruff>={floor}, а проверки идут на {pin} — разработчик получит другой линтер")
