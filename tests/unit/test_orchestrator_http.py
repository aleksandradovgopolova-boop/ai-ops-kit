"""Гранулярные тесты orchestrator_http (мигрировано из test_orchestrator_http_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import urllib.error as _ue
import urllib.request as _ur
from unittest.mock import patch

import pytest

from ai_ops_kit.providers.orchestrator_http import (
    _http_post_json,
)


class _Resp:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return b'{"ok": true}'


@pytest.mark.unit
class TestHttpRetry:
    def test_transient_failures_retry_then_succeed(self):
        """2 транзиентных сбоя -> успех на 3-й попытке."""
        calls = {"n": 0}

        def flaky(req, timeout=0):
            calls["n"] += 1
            if calls["n"] < 3:
                raise _ue.URLError("ssl handshake timed out")
            return _Resp()

        with patch.object(_ur, "urlopen", flaky), patch("time.sleep"):
            r = _http_post_json("http://x", {}, {}, retries=3)

        assert r.get("ok") is True
        assert calls["n"] == 3

    def test_4xx_not_retried(self):
        """4xx (404) не ретраится — 1 попытка."""
        calls = {"n": 0}

        def not_found(req, timeout=0):
            calls["n"] += 1
            raise _ue.HTTPError("http://x", 404, "not found", {}, None)

        with patch.object(_ur, "urlopen", not_found), patch("time.sleep"):
            with pytest.raises(_ue.HTTPError):
                _http_post_json("http://x", {}, {}, retries=3)

        assert calls["n"] == 1
