"""Селфтест orchestrator_http, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from orchestrator_http import (  # noqa: F401 — имена, которые использует тело
    _http_post_json,
)


@pytest.mark.slow
def test_orchestrator_http_selftest():
    ok = True
    # _http_post_json ретраит ТРАНЗИЕНТНЫЕ сбои (SSL-timeout оборвал задачу).
    # Монкипатчим urlopen + sleep: 2 сетевых сбоя -> успех; 4xx не ретраится.
    import urllib.request as _ur
    import urllib.error as _ue
    import time as _time
    _real_open, _real_sleep = _ur.urlopen, _time.sleep
    _time.sleep = lambda *_a, **_k: None                     # без реальных пауз в тесте

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"ok": true}'

    try:
        calls = {"n": 0}
        def flaky(req, timeout=0):
            calls["n"] += 1
            if calls["n"] < 3:
                raise _ue.URLError("ssl handshake timed out")
            return _Resp()
        _ur.urlopen = flaky
        r = _http_post_json("http://x", {}, {}, retries=3)
        expect_ok = r.get("ok") is True and calls["n"] == 3
        print(("PASS" if expect_ok else "FAIL")
              + " http-retry: 2 транзиентных сбоя -> успех на 3-й попытке")
        ok = ok and expect_ok

        calls2 = {"n": 0}
        def not_found(req, timeout=0):
            calls2["n"] += 1
            raise _ue.HTTPError("http://x", 404, "not found", {}, None)
        _ur.urlopen = not_found
        try:
            _http_post_json("http://x", {}, {}, retries=3)
            ok = False; print("FAIL http-retry: 404 не должен возвращать успех")
        except _ue.HTTPError:
            good = calls2["n"] == 1                          # 4xx не ретраится
            print(("PASS" if good else "FAIL") + " http-retry: 4xx (404) не ретраится (1 попытка)")
            ok = ok and good
    finally:
        _ur.urlopen = _real_open
        _time.sleep = _real_sleep

    assert ok, "перенесённый селфтест orchestrator_http: см. строки FAIL в выводе"
