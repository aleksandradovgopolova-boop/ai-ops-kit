"""Тесты plan_fragments — добавление работ в план вкладками-фрагментами."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from ai_ops_kit.planning.plan_fragments import (
    ALLOWED_STATUSES,
    FragmentError,
    assemble,
    check_conflicts,
    create_fragment,
    incoming_dir,
    plan_path,
    read_fragments,
    validate_fragment,
)


# ── валидация фрагмента ──────────────────────────────────────────────────────


class TestValidateFragment:
    def test_valid_minimal(self):
        data = {
            "id": "my-new-work",
            "title": "Do something",
            "type": "engineering",
            "goal": "checks-that-run",
            "status": "todo",
            "owner_role": "engineer",
            "value": "high",
            "write_scope": ["tests/"],
        }
        assert validate_fragment(data) == []

    def test_valid_full(self):
        data = {
            "id": "full-work",
            "title": "Do everything",
            "type": "engineering",
            "goal": "checks-that-run",
            "status": "in_progress",
            "owner_role": "engineer",
            "value": "medium",
            "write_scope": ["tests/"],
            "depends_on": ["other-work"],
            "reason": "Because",
            "branch": "lane-x",
            "finding": "docs/something.md",
            "evidence": "tests/test_x.py",
            "affects": {"delivery_operations": True},
        }
        assert validate_fragment(data) == []

    def test_missing_required_fields(self):
        data = {"id": "incomplete"}
        errors = validate_fragment(data)
        assert len(errors) == 1
        assert "отсутствуют обязательные поля" in errors[0]

    def test_id_not_slug(self):
        data = {
            "id": "My Work",
            "title": "T",
            "type": "engineering",
            "goal": "g",
            "status": "todo",
            "owner_role": "engineer",
            "value": "high",
            "write_scope": [],
        }
        errors = validate_fragment(data)
        assert any("slug" in e for e in errors)

    def test_status_done_rejected(self):
        data = {
            "id": "done-work",
            "title": "T",
            "type": "engineering",
            "goal": "g",
            "status": "done",
            "owner_role": "engineer",
            "value": "high",
            "write_scope": [],
        }
        errors = validate_fragment(data)
        assert any("status" in e and "done" in e for e in errors)

    def test_status_dropped_rejected(self):
        data = {
            "id": "dropped-work",
            "title": "T",
            "type": "engineering",
            "goal": "g",
            "status": "dropped",
            "owner_role": "engineer",
            "value": "high",
            "write_scope": [],
        }
        errors = validate_fragment(data)
        assert any("dropped" in e for e in errors)

    def test_write_scope_not_list(self):
        data = {
            "id": "bad-scope",
            "title": "T",
            "type": "engineering",
            "goal": "g",
            "status": "todo",
            "owner_role": "engineer",
            "value": "high",
            "write_scope": "tests/",
        }
        errors = validate_fragment(data)
        assert any("write_scope" in e for e in errors)

    def test_unknown_fields(self):
        data = {
            "id": "extra-fields",
            "title": "T",
            "type": "engineering",
            "goal": "g",
            "status": "todo",
            "owner_role": "engineer",
            "value": "high",
            "write_scope": [],
            "assignee": "bot",  # запрещённое поле
        }
        errors = validate_fragment(data)
        assert any("неизвестные поля" in e for e in errors)


# ── чтение фрагментов ────────────────────────────────────────────────────────


class TestReadFragments:
    def test_empty_dir(self, tmp_path: Path):
        inc = tmp_path / "planning" / "incoming"
        inc.mkdir(parents=True)
        frags, errors = read_fragments(tmp_path)
        assert frags == []
        assert errors == []

    def test_no_dir(self, tmp_path: Path):
        frags, errors = read_fragments(tmp_path)
        assert frags == []
        assert errors == []

    def test_reads_valid_fragment(self, tmp_path: Path):
        inc = tmp_path / "planning" / "incoming"
        inc.mkdir(parents=True)
        frag = {
            "id": "test-work",
            "title": "Test",
            "type": "engineering",
            "goal": "g",
            "status": "todo",
            "owner_role": "engineer",
            "value": "high",
            "write_scope": ["tests/"],
        }
        (inc / "test-work.yaml").write_text(yaml.dump(frag))

        frags, errors = read_fragments(tmp_path)
        assert len(frags) == 1
        assert errors == []
        assert frags[0]["id"] == "test-work"

    def test_invalid_yaml_reported(self, tmp_path: Path):
        inc = tmp_path / "planning" / "incoming"
        inc.mkdir(parents=True)
        (inc / "bad.yaml").write_text(":\n  :\n  - [invalid")

        frags, errors = read_fragments(tmp_path)
        assert frags == []
        assert len(errors) == 1
        assert "невалидный YAML" in errors[0]

    def test_invalid_fragment_excluded(self, tmp_path: Path):
        inc = tmp_path / "planning" / "incoming"
        inc.mkdir(parents=True)
        # Валидный
        good = {
            "id": "good",
            "title": "G",
            "type": "engineering",
            "goal": "g",
            "status": "todo",
            "owner_role": "engineer",
            "value": "high",
            "write_scope": [],
        }
        (inc / "good.yaml").write_text(yaml.dump(good))
        # Невалидный (status: done)
        bad = dict(good, id="bad", status="done")
        (inc / "bad.yaml").write_text(yaml.dump(bad))

        frags, errors = read_fragments(tmp_path)
        assert len(frags) == 1
        assert frags[0]["id"] == "good"
        assert len(errors) == 1


# ── конфликты ────────────────────────────────────────────────────────────────


class TestCheckConflicts:
    def test_no_conflicts(self, tmp_path: Path):
        # Минимальный plan.yaml без работ
        plan = tmp_path / "planning"
        plan.mkdir(parents=True)
        (plan / "plan.yaml").write_text(yaml.dump({"schema_version": 1, "work": []}))
        hist = tmp_path / "history"
        hist.mkdir(parents=True)
        (hist / "plan-history.yaml").write_text(yaml.dump({"work": []}))

        frags = [{"id": "new-work", "title": "T"}]
        assert check_conflicts(frags, tmp_path) == []

    def test_conflict_with_plan(self, tmp_path: Path):
        plan = tmp_path / "planning"
        plan.mkdir(parents=True)
        (plan / "plan.yaml").write_text(
            yaml.dump({"work": [{"id": "existing-work"}]})
        )

        frags = [{"id": "existing-work"}]
        errors = check_conflicts(frags, tmp_path)
        assert len(errors) == 1
        assert "уже есть" in errors[0]

    def test_duplicate_within_fragments(self, tmp_path: Path):
        plan = tmp_path / "planning"
        plan.mkdir(parents=True)
        (plan / "plan.yaml").write_text(yaml.dump({"work": []}))

        frags = [{"id": "dup"}, {"id": "dup"}]
        errors = check_conflicts(frags, tmp_path)
        assert any("дубликат" in e for e in errors)


# ── сборка ───────────────────────────────────────────────────────────────────


class TestAssemble:
    def _setup_plan(self, tmp_path: Path, work: list | None = None):
        plan = tmp_path / "planning"
        plan.mkdir(parents=True)
        (plan / "plan.yaml").write_text(
            yaml.dump({"schema_version": 1, "work": work or []})
        )
        hist = tmp_path / "history"
        hist.mkdir(parents=True)
        (hist / "plan-history.yaml").write_text(yaml.dump({"work": []}))

    def test_assemble_empty(self, tmp_path: Path):
        self._setup_plan(tmp_path)
        (tmp_path / "planning" / "incoming").mkdir(parents=True)

        result = assemble(tmp_path)
        assert result["added"] == []
        assert result["errors"] == []

    def test_assemble_adds_fragment(self, tmp_path: Path):
        self._setup_plan(tmp_path)
        inc = tmp_path / "planning" / "incoming"
        inc.mkdir(parents=True)

        frag = {
            "id": "new-work",
            "title": "New work item",
            "type": "engineering",
            "goal": "checks-that-run",
            "status": "todo",
            "owner_role": "engineer",
            "value": "high",
            "write_scope": ["tests/"],
        }
        (inc / "new-work.yaml").write_text(yaml.dump(frag))

        result = assemble(tmp_path)
        assert result["added"] == ["new-work"]
        assert result["fragments_removed"] == 1
        assert result["errors"] == []

        # Проверяем, что работа добавлена в plan.yaml
        plan_data = yaml.safe_load((tmp_path / "planning" / "plan.yaml").read_text())
        ids = [w["id"] for w in plan_data["work"]]
        assert "new-work" in ids

        # Фрагмент удалён
        assert not (inc / "new-work.yaml").exists()

    def test_assemble_rejects_conflict(self, tmp_path: Path):
        self._setup_plan(tmp_path, work=[{"id": "existing"}])
        inc = tmp_path / "planning" / "incoming"
        inc.mkdir(parents=True)

        frag = {
            "id": "existing",
            "title": "Dup",
            "type": "engineering",
            "goal": "g",
            "status": "todo",
            "owner_role": "engineer",
            "value": "high",
            "write_scope": [],
        }
        (inc / "existing.yaml").write_text(yaml.dump(frag))

        result = assemble(tmp_path)
        assert result["added"] == []
        assert len(result["errors"]) > 0

    def test_assemble_multiple_fragments(self, tmp_path: Path):
        self._setup_plan(tmp_path)
        inc = tmp_path / "planning" / "incoming"
        inc.mkdir(parents=True)

        for i in range(3):
            frag = {
                "id": f"work-{i}",
                "title": f"Work {i}",
                "type": "engineering",
                "goal": "g",
                "status": "todo",
                "owner_role": "engineer",
                "value": "high",
                "write_scope": ["tests/"],
            }
            (inc / f"work-{i}.yaml").write_text(yaml.dump(frag))

        result = assemble(tmp_path)
        assert len(result["added"]) == 3
        assert result["fragments_removed"] == 3


# ── создание фрагмента ────────────────────────────────────────────────────────


class TestCreateFragment:
    def test_creates_file(self, tmp_path: Path):
        frag = {
            "id": "my-work",
            "title": "My work",
            "type": "engineering",
            "goal": "g",
            "status": "todo",
            "owner_role": "engineer",
            "value": "high",
            "write_scope": ["tests/"],
        }
        path = create_fragment(frag, tmp_path)
        assert path.exists()
        assert path.name == "my-work.yaml"

        data = yaml.safe_load(path.read_text())
        assert data["id"] == "my-work"

    def test_rejects_invalid(self, tmp_path: Path):
        with pytest.raises(FragmentError):
            create_fragment({"id": "bad"}, tmp_path)
