"""Granular tests for validate_surface_wiring (migrated from selftest)."""
from __future__ import annotations

import pytest

from validate_surface_wiring import (  # noqa: F401
    check,
)


@pytest.mark.unit
@pytest.mark.slow
class TestValidateSurfaceWiring:
    """Validation of API surface wiring consistency."""

    def test_consistent_surface_no_errors(self):
        clean = {
            "core": ["/api/catalog"],
            "wrappers": {
                "prod": ["/api/catalog"],
                "dev": ["/api/catalog"],
                "serverless": ["/api/catalog"],
            },
            "client": ["/api/catalog"],
        }
        assert check(clean)["errors"] == []

    def test_drift_core_route_not_mounted(self):
        drift = {
            "core": ["/api/catalog"],
            "wrappers": {"prod": [], "dev": []},
            "client": ["/api/catalog"],
        }
        e = check(drift)["errors"]
        assert any("НЕ смонтирован" in x for x in e)

    def test_drift_client_path_unserved(self):
        drift = {
            "core": ["/api/catalog"],
            "wrappers": {"prod": [], "dev": []},
            "client": ["/api/catalog"],
        }
        e = check(drift)["errors"]
        assert any("не обслуживается ни одной" in x for x in e)

    def test_partial_drift_dev_forgotten(self):
        partial = {
            "core": ["/api/catalog"],
            "wrappers": {"prod": ["/api/catalog"], "dev": []},
            "client": ["/api/catalog"],
        }
        assert any("'dev'" in x for x in check(partial)["errors"])

    def test_prefix_mount_covers_nested_path(self):
        pref = {
            "core": [],
            "wrappers": {"prod": ["/api/catalog"]},
            "client": ["/api/catalog/123"],
        }
        assert check(pref)["errors"] == []

    def test_mounted_but_not_called_is_advisory(self):
        unused = {
            "core": ["/api/catalog"],
            "wrappers": {"prod": ["/api/catalog", "/api/legacy"]},
            "client": ["/api/catalog"],
        }
        u = check(unused)
        assert u["errors"] == []
        assert any("/api/legacy" in a for a in u["advisories"])

    def test_manifest_not_object_is_error(self):
        assert check(None)["errors"] != []
