"""Гранулярные тесты provider_endpoints (мигрировано из test_provider_endpoints_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import os

import pytest

from provider_endpoints import (
    endpoint_for,
    key_available,
)


@pytest.mark.unit
class TestEndpoints:
    def test_kimi_endpoint(self):
        ep = endpoint_for("kimi")
        assert ep["base_url"].startswith("https://api.moonshot.ai")
        assert ep["key_env"] == "KIMI_API_KEY"

    def test_qwen_endpoint(self):
        assert "dashscope-intl" in endpoint_for("qwen")["base_url"]

    def test_deepseek_endpoint(self):
        assert "api.deepseek.com" in endpoint_for("deepseek")["base_url"]

    def test_unknown_provider_returns_none(self):
        assert endpoint_for("ghost") is None


@pytest.mark.unit
class TestDeepseekKeyFallback:
    def test_fallback_to_openai_compatible_key(self):
        saved_d = os.environ.pop("DEEPSEEK_API_KEY", None)
        saved_o = os.environ.get("OPENAI_COMPATIBLE_API_KEY")
        os.environ["OPENAI_COMPATIBLE_API_KEY"] = "x"
        try:
            ep = endpoint_for("deepseek")
            assert ep["key_env"] == "OPENAI_COMPATIBLE_API_KEY"
            assert key_available("deepseek") is True
        finally:
            os.environ.pop("DEEPSEEK_API_KEY", None)
            if saved_d is not None:
                os.environ["DEEPSEEK_API_KEY"] = saved_d
            if saved_o is None:
                os.environ.pop("OPENAI_COMPATIBLE_API_KEY", None)
            else:
                os.environ["OPENAI_COMPATIBLE_API_KEY"] = saved_o

    def test_primary_key_preferred(self):
        saved_d = os.environ.pop("DEEPSEEK_API_KEY", None)
        os.environ["DEEPSEEK_API_KEY"] = "y"
        try:
            assert endpoint_for("deepseek")["key_env"] == "DEEPSEEK_API_KEY"
        finally:
            os.environ.pop("DEEPSEEK_API_KEY", None)
            if saved_d is not None:
                os.environ["DEEPSEEK_API_KEY"] = saved_d


@pytest.mark.unit
class TestKeyAvailable:
    def test_kimi_without_key(self):
        saved = os.environ.pop("KIMI_API_KEY", None)
        try:
            assert key_available("kimi") is False
        finally:
            if saved is not None:
                os.environ["KIMI_API_KEY"] = saved
