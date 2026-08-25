"""Гранулярные тесты validate_event_catalog (миграция с селфтеста)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from validate_event_catalog import (
    PKG,
    check,
    scan_code,
    yaml,
)


@pytest.fixture(scope="module")
def valid_catalog():
    """Минимальный валидный каталог событий."""
    return {
        "schema_version": 1, "kind": "event-catalog", "events": [
            {"name": "object.version_created", "kind": "domain",
             "payload": ["objectId", "version"]},
            {"name": "task.completed", "kind": "domain", "payload": ["taskId"]},
            {"name": "object.version_saved", "kind": "audit",
             "maps_to": "object.version_created",
             "fields": ["actorId", "action", "result"]},
            {"name": "catalog.published", "kind": "analytics",
             "maps_to": "object.version_created"},
        ],
    }


@pytest.mark.unit
@pytest.mark.slow
class TestEventCatalogValidation:

    def test_valid_catalog_no_errors(self, valid_catalog):
        e, w = check(valid_catalog)
        assert e == []

    def test_duplicate_name_rejected(self):
        e, _ = check({"schema_version": 1, "kind": "event-catalog", "events": [
            {"name": "task.completed", "kind": "domain"},
            {"name": "task.completed", "kind": "domain"}]})
        assert any("дублирующееся" in x for x in e)

    def test_camelcase_grammar_rejected(self):
        e, _ = check({"schema_version": 1, "kind": "event-catalog",
                       "events": [{"name": "task.Complete", "kind": "domain"}]})
        assert any("грамматике" in x for x in e)

    def test_audit_without_maps_to_rejected(self):
        e, _ = check({"schema_version": 1, "kind": "event-catalog", "events": [
            {"name": "task.completed", "kind": "domain"},
            {"name": "task.complete", "kind": "audit"}]})
        assert any("нет maps_to" in x for x in e)

    def test_maps_to_nonexistent_domain_rejected(self):
        e, _ = check({"schema_version": 1, "kind": "event-catalog", "events": [
            {"name": "task.completed", "kind": "domain"},
            {"name": "task.done", "kind": "analytics", "maps_to": "task.nope"}]})
        assert any("нет такого domain" in x for x in e)

    def test_domain_with_audit_fields_rejected(self):
        e, _ = check({"schema_version": 1, "kind": "event-catalog", "events": [
            {"name": "object.opened", "kind": "domain",
             "fields": ["actorId", "action", "result"]}]})
        assert any("AuditEvent" in x for x in e)

    def test_standalone_without_reason_rejected(self):
        e, _ = check({"schema_version": 1, "kind": "event-catalog", "events": [
            {"name": "d.happened", "kind": "domain"},
            {"name": "sys.pinged", "kind": "audit", "standalone": True}]})
        assert any("standalone требует reason" in x for x in e)

    def test_scan_catches_unknown_literal(self):
        with tempfile.TemporaryDirectory() as td:
            code = Path(td) / "server.ts"
            code.write_text(
                'emit("object.version.save"); emit("object.version_created");',
                encoding="utf-8")
            drift = scan_code(["object.version_created"], [], [str(code)])
            assert any(d["literal"] == "object.version.save" for d in drift)

    def test_scan_canonical_name_not_in_drift(self):
        with tempfile.TemporaryDirectory() as td:
            code = Path(td) / "server.ts"
            code.write_text(
                'emit("object.version.save"); emit("object.version_created");',
                encoding="utf-8")
            drift = scan_code(["object.version_created"], [], [str(code)])
            assert all(d["literal"] != "object.version_created" for d in drift)

    def test_kit_example_is_valid(self):
        ex = PKG / "examples" / "event-catalog-demo" / "events.yaml"
        if ex.exists():
            e, _ = check(yaml.safe_load(ex.read_text(encoding="utf-8")))
            assert e == []
