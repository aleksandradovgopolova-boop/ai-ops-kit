"""Гранулярные тесты validate_pipeline_e2e (миграция из селфтеста v3.30)."""
from __future__ import annotations

import pytest

from validate_pipeline_e2e import (  # noqa: F401
    main,
)


@pytest.mark.unit
@pytest.mark.slow
def test_pipeline_e2e_passes():
    """Полный e2e прогон пайплайна завершается без ошибок."""
    assert main([]) == 0
