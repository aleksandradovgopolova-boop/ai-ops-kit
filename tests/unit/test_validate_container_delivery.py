"""Гранулярные тесты validate_container_delivery (миграция с селфтеста)."""
from __future__ import annotations

import pytest

from validate_container_delivery import main


@pytest.mark.unit
@pytest.mark.slow
def test_validate_container_delivery_runs_cleanly():
    assert main([]) == 0
