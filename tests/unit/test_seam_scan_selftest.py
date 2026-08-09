"""Селфтест seam_scan, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from seam_scan import (  # noqa: F401 — имена, которые использует тело
    gate_decision,
    scan_diff,
)


@pytest.mark.slow
def test_seam_scan_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    # #3 catch без happy-path -> block; с тестом -> нет
    d_catch = "+++ b/src/handler.py\n+    try:\n+        do()\n+    except Exception:\n+        pass\n"
    s = scan_diff(d_catch)
    expect("catch-swallow найден", any(f["signal"] == "catch_without_happy_path" for f in s["findings"]))
    expect("catch без теста -> gate BLOCK", gate_decision(s)["block"] is True)
    d_catch_test = d_catch + "+++ b/tests/test_handler.py\n+def test_do_happy():\n+    assert do() == 1\n"
    expect("catch + happy-path тест -> НЕ block", gate_decision(scan_diff(d_catch_test))["block"] is False)

    # #4 optional field в общем контракте -> block без теста
    d_opt = "+++ b/schemas/order.schema.json\n+    \"discount\": {\"type\": \"number\"}\n+++ b/src/types.ts\n+  discount?: number\n"
    so = scan_diff(d_opt)
    expect("optional-поле в контракте найдено",
           any(f["signal"] == "optional_field_in_shared_contract" for f in so["findings"]))
    expect("optional-поле без теста перехода -> BLOCK", gate_decision(so)["block"] is True)

    # #5 stub без real-run -> block; с integration -> нет
    d_stub = "+++ b/tests/test_api.py\n+    client = MagicMock()\n+    responses.add('GET', url)\n"
    ss = scan_diff(d_stub)
    expect("stub внешней системы найден", any(f["signal"] == "external_stub_without_real_run" for f in ss["findings"]))
    expect("stub без real-run -> BLOCK", gate_decision(ss)["block"] is True)
    d_stub_real = d_stub + "+    @pytest.mark.integration\n+    def test_against_real_api(): ...\n"
    expect("stub + integration real-run -> НЕ block", gate_decision(scan_diff(d_stub_real))["block"] is False)

    # #1 write без round-trip -> advisory (не block сам по себе)
    d_write = "+++ b/src/store.py\n+    path.write_text(data)\n"
    sw = scan_diff(d_write)
    expect("write без round-trip -> advisory (#1), не в блокерах",
           any(f["signal"] == "write_without_roundtrip" for f in sw["findings"])
           and gate_decision(sw)["block"] is False)

    # #2 precondition (включили гейт/auth) -> advisory
    d_pre = "+++ b/api/orders.py\n+    if not authorized(user):\n+        abort(401)\n"
    sp = scan_diff(d_pre)
    expect("смена предусловия эндпоинта -> advisory (#2)",
           any(f["signal"] == "endpoint_precondition_change" for f in sp["findings"]))

    # #6 surface wiring: новый маршрут ядра + вызов клиента -> advisory (не block), с подсказкой про реестр
    d_route = ("+++ b/server/domain/handler.mjs\n+  app.get('/api/catalog', catalogHandler)\n"
               "+++ b/src/shared/api/client.ts\n+  return fetch('/api/catalog')\n")
    sr = scan_diff(d_route)
    expect("#6 маршрут ядра найден (surface_wiring_drift)",
           any(f["signal"] == "surface_wiring_drift" for f in sr["findings"]))
    dr = gate_decision(sr)
    expect("#6 surface drift -> advisory, НЕ block", dr["block"] is False
           and any("surface_wiring_drift" in a for a in dr["advisories"]))
    expect("#6 реестр маршрутов не менялся -> подсказка про core⊆обёртки⊆client",
           any("реестр маршрутов не менялся" in a for a in dr["advisories"]))
    # #6 если реестр маршрутов В дифе -> подсказки про «не менялся» нет
    d_route_reg = d_route + "+++ b/server/domain/routes.mjs\n+  '/api/catalog',\n"
    expect("#6 реестр маршрутов изменён -> без подсказки 'не менялся'",
           not any("реестр маршрутов не менялся" in a for a in gate_decision(scan_diff(d_route_reg))["advisories"]))

    # чистый диф без швов -> нет блока
    expect("диф без швов -> нет находок, нет блока",
           gate_decision(scan_diff("+++ b/README.md\n+# docs\n"))["block"] is False)

    assert ok, "перенесённый селфтест seam_scan: см. строки FAIL в выводе"
