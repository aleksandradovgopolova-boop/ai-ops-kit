"""Единый источник версии Python: `.python-version` (dev + CI) не должен расходиться с полом
`requires-python` в pyproject.

ЗАЧЕМ. Требование владельца первого класса: разница версий Python не должна мешать разработке
(см. правило памяти проекта + issue #1378/#1414). «Единое окружение» держится, только пока
версия объявлена В ОДНОМ месте: `.python-version` задаёт интерпретатор для dev и для CI
(`setup-python` читает `python-version-file: .python-version`), а `requires-python` — пол
совместимости. Если их minor разойдётся, дрейф вернётся молча. Этот тест делает совпадение
инвариантом, а не договорённостью.
"""
import pathlib

from ai_ops_kit.validation.validate_python_compat import declared_floor

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_python_version_pin_matches_requires_python_floor():
    pin = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
    major, minor = (int(part) for part in pin.split(".")[:2])
    floor = declared_floor(ROOT)
    assert (major, minor) == tuple(floor), (
        f".python-version={pin} и requires-python floor={floor[0]}.{floor[1]} разошлись — "
        "единый источник версии Python нарушен")
