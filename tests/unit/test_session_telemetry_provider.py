"""Гранулярные тесты session_telemetry_provider (мигрировано из test_session_telemetry_provider_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.engops.session_telemetry_provider import (
    check,
    read_session_metadata,
)


@pytest.mark.unit
class TestReadSessionMetadata:
    def test_nonexistent_session_returns_none(self):
        result = read_session_metadata(session_id="nonexistent-session-12345")
        assert result is None


@pytest.mark.unit
class TestCheck:
    def test_check_none_returns_empty(self):
        errors = check(None)
        assert errors == []

    def test_check_valid_data_returns_empty(self):
        valid_data = {
            "session_id": "test-session",
            "started_at": "2026-08-05T10:00:00Z",
            "message_count": 10,
            "input_tokens": 5000,
            "output_tokens": 2000,
        }
        errors = check(valid_data)
        assert errors == []

    def test_check_invalid_data_returns_errors(self):
        invalid_data = {"message_count": -1}
        errors = check(invalid_data)
        assert errors
