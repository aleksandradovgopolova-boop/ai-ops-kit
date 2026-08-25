"""Granular tests for validate_stack_qualification (migrated from selftest)."""
from __future__ import annotations

import pytest

from validate_stack_qualification import (  # noqa: F401
    main,
)


@pytest.mark.unit
@pytest.mark.slow
def test_validate_stack_qualification_passes():
    assert main([]) == 0
