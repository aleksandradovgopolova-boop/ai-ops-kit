"""Гранулярные тесты validate_duties (миграция с селфтеста)."""
from __future__ import annotations

import pytest

from validate_duties import (
    PKG,
    check,
    yaml,
)


@pytest.fixture(scope="module")
def valid_duties():
    """Минимальная валидная декларация обязанностей."""
    return {
        "schema_version": 1, "kind": "robin-duties", "owner": "team-lead",
        "duties": [{"id": "d1", "description": "x", "owner": "team-lead",
                     "trigger": {"type": "cron", "schedule": "0 9 * * MON"},
                     "inputs": ["a"], "output": {"artifact": "digest", "destination": "team-chat"}}],
    }


@pytest.mark.unit
@pytest.mark.slow
class TestDutiesValidation:

    def test_valid_declaration_no_errors(self, valid_duties):
        assert check(valid_duties) == []

    def test_no_cron_duty_rejected(self):
        no_cron = {"schema_version": 1, "kind": "robin-duties", "owner": "t",
                    "duties": [{"id": "d1", "description": "x", "owner": "t",
                                 "trigger": {"type": "event", "event": "chat-question"},
                                 "inputs": ["a"],
                                 "output": {"artifact": "answer", "destination": "team-chat"}}]}
        assert any("минимально обязательной" in e for e in check(no_cron))

    def test_cron_without_schedule_rejected(self):
        cron_no_sched = {"schema_version": 1, "kind": "robin-duties", "owner": "t",
                          "duties": [{"id": "d1", "description": "x", "owner": "t",
                                       "trigger": {"type": "cron"},
                                       "inputs": ["a"],
                                       "output": {"artifact": "digest", "destination": "team-chat"}}]}
        assert any("требует schedule" in e for e in check(cron_no_sched))

    def test_prod_destination_rejected(self):
        prod_dest = {"schema_version": 1, "kind": "robin-duties", "owner": "t",
                      "duties": [{"id": "d1", "description": "x", "owner": "t",
                                   "trigger": {"type": "cron", "schedule": "0 9 * * *"},
                                   "inputs": ["a"],
                                   "output": {"artifact": "x", "destination": "prod-db"}}]}
        assert any("read-mostly" in e for e in check(prod_dest))

    def test_promoted_memory_destination_rejected(self):
        curated_dest = {"schema_version": 1, "kind": "robin-duties", "owner": "t",
                         "duties": [{"id": "d1", "description": "x", "owner": "t",
                                      "trigger": {"type": "cron", "schedule": "0 9 * * *"},
                                      "inputs": ["a"],
                                      "output": {"artifact": "x",
                                                  "destination": "promoted/knowledge"}}]}
        assert any("человек" in e for e in check(curated_dest))

    def test_duplicate_id_rejected(self):
        dup = {"schema_version": 1, "kind": "robin-duties", "owner": "t",
                "duties": [
                    {"id": "d1", "description": "x", "owner": "t",
                     "trigger": {"type": "cron", "schedule": "0 9 * * *"},
                     "inputs": ["a"],
                     "output": {"artifact": "d", "destination": "chat"}},
                    {"id": "d1", "description": "y", "owner": "t",
                     "trigger": {"type": "event", "event": "e"},
                     "inputs": ["a"],
                     "output": {"artifact": "d", "destination": "chat"}}]}
        assert any("дублирующийся" in e for e in check(dup))

    def test_kit_example_is_valid(self):
        ex = PKG / "runtime" / "robin" / "duties.example.yaml"
        if ex.exists():
            assert check(yaml.safe_load(ex.read_text(encoding="utf-8"))) == []
