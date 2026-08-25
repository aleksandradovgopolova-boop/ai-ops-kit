"""Гранулярные тесты active_work (мигрировано из test_active_work_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import tempfile

import pytest

from active_work import (
    ActiveWorkCorrupt,
    Path,
    classify,
    finish_cmd,
    load,
    register,
)


@pytest.fixture
def work_file():
    """Временный файл реестра активных работ."""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td) / "active-work.yaml"


@pytest.mark.unit
class TestRegister:
    def test_register_adds_work_entry(self, work_file):
        register(
            work_file, "dashboard-editing", "feature/dashboard-editing",
            ["dashboard-editor", "session-context"], "session-1",
            contracts=["schemas/dashboard.schema.json"], at="2026-07-15",
        )
        data = load(work_file)
        assert any(w["id"] == "dashboard-editing" for w in data["active"])

    def test_register_in_main_branch_returns_error(self, work_file):
        assert register(work_file, "x", "main", ["a"], "s") == 1

    def test_register_without_areas_returns_error(self, work_file):
        assert register(work_file, "x", "feature/x", [], "s") == 1

    def test_register_cyclic_dependency_returns_error(self, work_file):
        register(work_file, "a", "feature/a", ["za"], "s", depends=["b"], at="2026-07-15")
        assert register(work_file, "b", "feature/b", ["zb"], "s", depends=["a"], at="2026-07-15") == 1


@pytest.mark.unit
class TestClassify:
    @pytest.fixture(autouse=True)
    def setup_work(self, work_file):
        register(
            work_file, "dashboard-editing", "feature/dashboard-editing",
            ["dashboard-editor", "session-context"], "session-1",
            contracts=["schemas/dashboard.schema.json"], at="2026-07-15",
        )
        self.work_file = work_file

    def test_area_conflict_detected(self):
        conflicts = classify(
            load(self.work_file)["active"],
            {"id": "new", "affected_areas": ["session-context", "catalog"]},
        )
        assert any(c["kind"] == "area" and "session-context" in c["detail"] for c in conflicts)

    def test_contract_conflict_detected(self):
        conflicts = classify(
            load(self.work_file)["active"],
            {"id": "new", "affected_areas": ["x"],
             "shared_contracts": ["schemas/dashboard.schema.json"]},
        )
        assert any(c["kind"] == "contract" for c in conflicts)

    def test_dependency_on_active_work_detected(self):
        conflicts = classify(
            load(self.work_file)["active"],
            {"id": "new", "affected_areas": ["x"], "depends_on": ["dashboard-editing"]},
        )
        assert any(c["kind"] == "dependency" for c in conflicts)

    def test_non_overlapping_returns_empty(self):
        conflicts = classify(
            load(self.work_file)["active"],
            {"id": "new", "affected_areas": ["catalog", "api"]},
        )
        assert conflicts == []

    def test_work_does_not_conflict_with_itself(self):
        conflicts = classify(
            load(self.work_file)["active"],
            {"id": "dashboard-editing", "affected_areas": ["dashboard-editor"]},
        )
        assert conflicts == []


@pytest.mark.unit
class TestFinishAndCorrupt:
    def test_finished_work_does_not_conflict(self, work_file):
        register(
            work_file, "dashboard-editing", "feature/dashboard-editing",
            ["dashboard-editor", "session-context"], "session-1",
            contracts=["schemas/dashboard.schema.json"], at="2026-07-15",
        )
        finish_cmd(work_file, "dashboard-editing")
        conflicts = classify(
            load(work_file)["active"],
            {"id": "new", "affected_areas": ["dashboard-editor"]},
        )
        assert all(c["id"] != "dashboard-editing" for c in conflicts)

    def test_save_is_atomic_no_temp_leftover(self, work_file):
        register(
            work_file, "dashboard-editing", "feature/dashboard-editing",
            ["dashboard-editor", "session-context"], "session-1",
            contracts=["schemas/dashboard.schema.json"], at="2026-07-15",
        )
        assert work_file.is_file()
        assert not work_file.with_suffix(work_file.suffix + ".tmp").exists()

    def test_empty_registry_raises_corrupt(self, work_file):
        work_file.write_text("", encoding="utf-8")
        with pytest.raises(ActiveWorkCorrupt):
            load(work_file)

    def test_malformed_yaml_raises_corrupt(self, work_file):
        work_file.write_text("kind: active-work\nactive: [ :::\n", encoding="utf-8")
        with pytest.raises(ActiveWorkCorrupt):
            load(work_file)

    def test_missing_registry_returns_fresh(self, work_file):
        data = load(work_file)
        assert data["active"] == []
