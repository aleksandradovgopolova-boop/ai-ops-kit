"""Гранулярные тесты validate_python_compat (миграция из селфтеста v3.30)."""
from __future__ import annotations

import pytest

from validate_python_compat import (  # noqa: F401
    PKG,
    check_source,
    scan,
)


@pytest.mark.unit
def test_union_in_argument_without_future_is_flagged():
    """union в аргументе без future -> flagged."""
    bad = "def f(x: int | None):\n return x\n"
    assert check_source(bad) == [1]


@pytest.mark.unit
def test_union_in_return_without_future_is_flagged():
    """union в возврате без future -> flagged."""
    bad = "def g() -> str | None:\n return None\n"
    assert check_source(bad) == [1]


@pytest.mark.unit
def test_union_in_ann_assign_without_future_is_flagged():
    """union в AnnAssign без future -> flagged."""
    bad = "y: int | str = 1\n"
    assert check_source(bad) == [1]


@pytest.mark.unit
def test_union_under_future_import_is_ok():
    """union под future-import -> ок."""
    good = "from __future__ import annotations\n\ndef f(x: int | None):\n return x\n"
    assert check_source(good) == []


@pytest.mark.unit
def test_no_union_is_ok():
    """нет union -> ок."""
    assert check_source("def f(x: int):\n return x\n") == []


@pytest.mark.unit
def test_real_package_zero_violations():
    """Реальный пакет: 0 нарушений совместимости."""
    assert scan(PKG) == []
