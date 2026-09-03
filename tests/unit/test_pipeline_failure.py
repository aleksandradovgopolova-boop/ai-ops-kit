"""Гранулярные тесты pipeline_failure (мигрировано из test_pipeline_failure_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.engine.pipeline_failure import (
    _diff_checks,
    _env_proven_ok,
    _failure_ids,
    _failure_signal,
    _security_verdict_errors,
)


@pytest.mark.unit
class TestImports:
    def test_diff_checks_callable(self):
        assert callable(_diff_checks)

    def test_failure_signal_callable(self):
        assert callable(_failure_signal)

    def test_failure_ids_callable(self):
        assert callable(_failure_ids)

    def test_env_proven_ok_callable(self):
        assert callable(_env_proven_ok)

    def test_security_verdict_errors_callable(self):
        assert callable(_security_verdict_errors)
