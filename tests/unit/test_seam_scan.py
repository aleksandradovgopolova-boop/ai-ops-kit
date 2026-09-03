"""Гранулярные тесты seam_scan (мигрировано из test_seam_scan_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.security.seam_scan import (
    gate_decision,
    scan_diff,
)


@pytest.mark.unit
class TestCatchSwallow:
    def test_catch_without_happy_path_found(self):
        d = "+++ b/src/handler.py\n+    try:\n+        do()\n+    except Exception:\n+        pass\n"
        s = scan_diff(d)
        assert any(f["signal"] == "catch_without_happy_path" for f in s["findings"])

    def test_catch_without_test_blocks(self):
        d = "+++ b/src/handler.py\n+    try:\n+        do()\n+    except Exception:\n+        pass\n"
        assert gate_decision(scan_diff(d))["block"] is True

    def test_catch_with_test_does_not_block(self):
        d = ("+++ b/src/handler.py\n+    try:\n+        do()\n+    except Exception:\n+        pass\n"
             "+++ b/tests/test_handler.py\n+def test_do_happy():\n+    assert do() == 1\n")
        assert gate_decision(scan_diff(d))["block"] is False


@pytest.mark.unit
class TestOptionalField:
    def test_optional_field_detected(self):
        d = "+++ b/schemas/order.schema.json\n+    \"discount\": {\"type\": \"number\"}\n+++ b/src/types.ts\n+  discount?: number\n"
        s = scan_diff(d)
        assert any(f["signal"] == "optional_field_in_shared_contract" for f in s["findings"])

    def test_optional_field_without_test_blocks(self):
        d = "+++ b/schemas/order.schema.json\n+    \"discount\": {\"type\": \"number\"}\n+++ b/src/types.ts\n+  discount?: number\n"
        assert gate_decision(scan_diff(d))["block"] is True


@pytest.mark.unit
class TestExternalStub:
    def test_stub_detected(self):
        d = "+++ b/tests/test_api.py\n+    client = MagicMock()\n+    responses.add('GET', url)\n"
        s = scan_diff(d)
        assert any(f["signal"] == "external_stub_without_real_run" for f in s["findings"])

    def test_stub_without_real_run_blocks(self):
        d = "+++ b/tests/test_api.py\n+    client = MagicMock()\n+    responses.add('GET', url)\n"
        assert gate_decision(scan_diff(d))["block"] is True

    def test_stub_with_integration_does_not_block(self):
        d = ("+++ b/tests/test_api.py\n+    client = MagicMock()\n+    responses.add('GET', url)\n"
             "+    @pytest.mark.integration\n+    def test_against_real_api(): ...\n")
        assert gate_decision(scan_diff(d))["block"] is False


@pytest.mark.unit
class TestWriteWithoutRoundTrip:
    def test_write_advisory_not_block(self):
        d = "+++ b/src/store.py\n+    path.write_text(data)\n"
        s = scan_diff(d)
        assert any(f["signal"] == "write_without_roundtrip" for f in s["findings"])
        assert gate_decision(s)["block"] is False


@pytest.mark.unit
class TestEndpointPrecondition:
    def test_precondition_change_advisory(self):
        d = "+++ b/api/orders.py\n+    if not authorized(user):\n+        abort(401)\n"
        s = scan_diff(d)
        assert any(f["signal"] == "endpoint_precondition_change" for f in s["findings"])


@pytest.mark.unit
class TestSurfaceWiring:
    def test_route_drift_detected(self):
        d = ("+++ b/server/domain/handler.mjs\n+  app.get('/api/catalog', catalogHandler)\n"
             "+++ b/src/shared/api/client.ts\n+  return fetch('/api/catalog')\n")
        s = scan_diff(d)
        assert any(f["signal"] == "surface_wiring_drift" for f in s["findings"])

    def test_surface_drift_advisory(self):
        d = ("+++ b/server/domain/handler.mjs\n+  app.get('/api/catalog', catalogHandler)\n"
             "+++ b/src/shared/api/client.ts\n+  return fetch('/api/catalog')\n")
        dr = gate_decision(scan_diff(d))
        assert dr["block"] is False
        assert any("surface_wiring_drift" in a for a in dr["advisories"])

    def test_registry_not_changed_hint(self):
        d = ("+++ b/server/domain/handler.mjs\n+  app.get('/api/catalog', catalogHandler)\n"
             "+++ b/src/shared/api/client.ts\n+  return fetch('/api/catalog')\n")
        dr = gate_decision(scan_diff(d))
        assert any("реестр маршрутов не менялся" in a for a in dr["advisories"])

    def test_registry_changed_no_hint(self):
        d = ("+++ b/server/domain/handler.mjs\n+  app.get('/api/catalog', catalogHandler)\n"
             "+++ b/src/shared/api/client.ts\n+  return fetch('/api/catalog')\n"
             "+++ b/server/domain/routes.mjs\n+  '/api/catalog',\n")
        dr = gate_decision(scan_diff(d))
        assert not any("реестр маршрутов не менялся" in a for a in dr["advisories"])


@pytest.mark.unit
class TestCleanDiff:
    def test_no_seams_no_block(self):
        assert gate_decision(scan_diff("+++ b/README.md\n+# docs\n"))["block"] is False
