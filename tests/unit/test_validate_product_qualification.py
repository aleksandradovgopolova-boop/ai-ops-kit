"""Гранулярные тесты validate_product_qualification (миграция из селфтеста v3.30)."""
from __future__ import annotations

import pytest

from validate_product_qualification import (  # noqa: F401
    main,
)


@pytest.mark.unit
@pytest.mark.slow
def test_product_qualification_passes():
    """Полный прогон валидации product qualification завершается без ошибок."""
    assert main([]) == 0
