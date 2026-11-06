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


def _ci_versions() -> list[str]:
    """ВСЕ пины `ruff==` в CI, а не только первый. В package-quality.yml ruff ставится ДВАЖДЫ
    (джоба `lint` и шард `contracts`); если один подняли, а другой нет — «чисто в CI» снова
    расходится само с собой. Прежний guard читал только lines[0] и второй пин не видел (#1402)."""
    text = (KIT / ".github" / "workflows" / "package-quality.yml").read_text(encoding="utf-8")
    lines = [l for l in text.splitlines()
             if "pip install" in l and "ruff" in l and not l.strip().startswith("#")]
    assert lines, "в CI нет установки ruff"
    versions = []
    for l in lines:
        m = re.search(r"ruff==([\d.]+)", l)
        assert m, (
            f"CI ставит ruff без пина версии — «чисто в CI» перестаёт совпадать с локальным: {l.strip()}")
        versions.append(m.group(1))
    return versions


def _ci_version() -> str:
    """Единственная версия ruff в CI. Если пины разошлись между джобами — падаем здесь."""
    versions = _ci_versions()
    assert len(set(versions)) == 1, (
        f"CI пинит ruff разными версиями в разных джобах {versions} — «чисто в CI» перестаёт быть "
        "одним утверждением: один шард найдёт то, что другой пропустит")
    return versions[0]


def _pyproject_dev_floor() -> str:
    text = (KIT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'"ruff>=([\d.]+)"', text)
    assert m, "в dev-зависимостях pyproject нет ruff"
    return m.group(1)


def _requirements_dev_floor() -> str:
    """requirements-dev.txt — тоже dev-инструкция (#1402). Её нижняя граница должна держать тот же
    пин: `pip install -r requirements-dev.txt` не должен давать линтер ниже проверочного."""
    text = (KIT / "requirements-dev.txt").read_text(encoding="utf-8")
    m = re.search(r"^ruff>=([\d.]+)", text, re.MULTILINE)
    assert m, "в requirements-dev.txt нет ruff"
    return m.group(1)


def _to_tuple(s: str) -> tuple:
    return tuple(int(x) for x in s.split("."))


@pytest.mark.unit
def test_ci_and_hook_pin_the_same_ruff():
    hook, ci = _hook_version(), _ci_version()
    assert hook == ci, (
        f"хук пинит ruff {hook}, а CI ставит {ci} — «локально чисто» и «чисто в CI» это утверждения "
        f"про разные линтеры; именно так дефект в property-тесте прятался от локального прогона")


@pytest.mark.unit
def test_all_ci_jobs_pin_the_same_ruff():
    """Оба CI-пина ruff (lint и contracts) — одна версия: расхождение между джобами краснеет."""
    assert len(set(_ci_versions())) == 1, f"CI-джобы пинят ruff по-разному: {_ci_versions()}"


@pytest.mark.unit
@pytest.mark.parametrize("floor_fn", [_pyproject_dev_floor, _requirements_dev_floor])
def test_dev_floor_is_not_below_the_pin(floor_fn):
    """Нижняя граница dev-инструкций (pyproject .[dev] И requirements-dev.txt) не ниже пина: иначе
    `pip install -e .[dev]` или `-r requirements-dev.txt` даст разработчику третий линтер (#1402)."""
    floor, pin = floor_fn(), _ci_version()
    assert _to_tuple(floor) >= _to_tuple(pin), (
        f"dev ставит ruff>={floor}, а проверки идут на {pin} — разработчик получит другой линтер")
