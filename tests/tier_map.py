"""Единственный источник соответствия «каталог тестов → ярус пирамиды».

Ярус тестовой пирамиды задаётся РАСПОЛОЖЕНИЕМ файла, а не ручным маркером на каждой функции:
так пирамиду видно числом (`pytest -m unit|contract|integration`), новый тест не может остаться
без яруса молча, и не нужно править маркерами ~2700 функций (git blame не топится).

`conftest.pytest_collection_modifyitems` проставляет ярусный маркер на сборке по этому словарю;
`tests/contracts/test_pyramid_is_tiered.py` держит охранный инвариант: ни один тест-файл не живёт
вне каталога с известным ярусом. Оба читают ОТСЮДА — второй правды нет.
"""
from __future__ import annotations

# Непосредственный подкаталог tests/ -> имя ярусного маркера.
DIR_TIER = {
    "unit": "unit",
    "contracts": "contract",
    "integration": "integration",
}

# Маркеры, считающиеся ЯРУСНЫМИ — в отличие от ортогональных slow/live/regression/critical_path.
TIER_MARKERS = frozenset({"unit", "contract", "integration", "e2e"})
