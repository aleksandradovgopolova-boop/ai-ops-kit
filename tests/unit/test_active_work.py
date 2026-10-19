"""Гранулярные тесты active_work (мигрировано из test_active_work_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import tempfile

import pytest

from ai_ops_kit.lifecycle.active_work import (
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


def _automatic_claim_repo(tmp_path):
    import hashlib
    from ai_ops_kit.shared import gitio
    gitio.run(["init", "-q", "-b", "main", str(tmp_path)])
    gitio.git(tmp_path, "config", "user.email", "test@example.test")
    gitio.git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "input.txt").write_text("frozen")
    gitio.git(tmp_path, "add", ".")
    gitio.git(tmp_path, "commit", "-qm", "base")
    admission = {"base_sha": gitio.git(tmp_path, "rev-parse", "HEAD")[1],
                 "identity": "auto-owner", "inputs": {"input.txt": hashlib.sha256(b"frozen").hexdigest()}}
    return admission


def test_single_claim_blocks_automatic_in_common_git_store(tmp_path):
    from ai_ops_kit.lifecycle import active_work as aw
    from ai_ops_kit.engine.ai_ops_run_lifecycle import _register_active_work
    admission = _automatic_claim_repo(tmp_path)
    path, _, err = _register_active_work(tmp_path, {}, ["aa.py"], "work", "single-owner", [])
    assert err is None and path == aw.shared_registry_path(tmp_path)
    assert aw.load(tmp_path / ".ai/runtime/active-work.yaml")["active"]
    assert aw.register(path, "work", "ai-ops/work", ["aa.py"], "auto-owner", child_root=tmp_path,
                       admission=admission) == 1
    assert aw.load(path)["active"][0]["owner_session"] == "single-owner"


def test_automatic_claim_blocks_single_and_preserves_frozen_admission(tmp_path):
    from ai_ops_kit.lifecycle import active_work as aw
    from ai_ops_kit.engine.ai_ops_run_lifecycle import _register_active_work
    admission = _automatic_claim_repo(tmp_path)
    path = aw.shared_registry_path(tmp_path)
    assert aw.register(path, "work", "ai-ops/work", ["aa.py"], "auto-owner", child_root=tmp_path,
                       admission=admission) == 0
    assert aw.load(path)["active"][0]["auto_admission"] == admission
    _, _, err = _register_active_work(tmp_path, {}, ["aa.py"], "work", "single-owner", [])
    assert err and err.get("blocked_by") == "active-work"
    _, _, err = _register_active_work(tmp_path, {}, ["aa.py"], "different-work", "single-owner", [])
    assert err and err.get("blocked_by") == "active-work"
    from ai_ops_kit.shared import gitio
    sibling = tmp_path.parent / (tmp_path.name + "-sibling")
    assert gitio.git(tmp_path, "worktree", "add", "-qb", "sibling", str(sibling))[0] == 0
    assert aw.register(sibling / ".ai/runtime/active-work.yaml", "other", "ai-ops/other", ["aa.py"],
                       "legacy-sibling", child_root=sibling) == 1
    assert not (sibling / ".ai/runtime/active-work.yaml").exists()
    assert aw.finish_cmd(path, "work", child_root=tmp_path) == 0
    projected = aw.load(tmp_path / ".ai/runtime/active-work.yaml")["active"][0]
    assert projected["status"] == "done" and projected["auto_admission"] == admission
