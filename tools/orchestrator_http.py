#!/usr/bin/env python3
from __future__ import annotations
"""HTTP client for orchestrator providers — POST JSON with retry on transient failures.

Extracted from orchestrator.py to keep provider/HTTP concerns isolated.
"""

import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]


def _http_post_json(url, headers, payload, timeout=120, retries=6):
    """POST JSON с ретраями на ТРАНЗИЕНТНЫЕ сбои (finding живого прогона: SSL-handshake timeout
    оборвал задачу). Ретраим сетевые таймауты/сбросы и 5xx/429 с бэкоффом; 4xx (кроме 429) —
    не ретраим (это не транзиент, а ошибка запроса/ключа). Бэкофф детерминированный (без сна на
    последней попытке)."""
    import json as _json
    import time
    import urllib.error
    import urllib.request
    body = _json.dumps(payload).encode("utf-8")
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=body,
                                     headers={**headers, "content-type": "application/json"},
                                     method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:   # прокси — из env
                return _json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in (429, 500, 502, 503, 504) or attempt == retries - 1:
                raise
            # v3.0-rc7 (finding kimi): 429/overload перегруженного провайдера — уважаем Retry-After,
            # иначе экспон. бэкофф с бОльшим потолком (multi-call ENGINEERING-прогон переживает всплеск).
            ra = 0
            try:
                ra = int((e.headers or {}).get("Retry-After") or 0)
            except (ValueError, TypeError):
                ra = 0
            time.sleep(max(ra, min(3 * (2 ** attempt), 60)))
            continue
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = e                                    # сетевой транзиент (в т.ч. SSL timeout)
            if attempt == retries - 1:
                raise
        time.sleep(min(3 * (2 ** attempt), 60))         # 3s,6,12,24,48,60 между попытками
    raise last if last else RuntimeError("http retry exhausted")


# ---------------- selftest ----------------

def selftest():
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

    print("orchestrator_http selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv):
    if len(argv) > 1 and argv[1] == "--selftest":
        return selftest()
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
