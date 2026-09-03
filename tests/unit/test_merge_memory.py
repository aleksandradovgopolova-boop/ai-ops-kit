"""Гранулярные тесты merge_memory (мигрировано из test_merge_memory_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import tempfile

import pytest

from ai_ops_kit.lifecycle.merge_memory import (
    Path,
    record,
)


@pytest.fixture
def td():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.mark.unit
class TestRecordValidation:
    def test_empty_summary_returns_error(self, td):
        assert record(td, "wi-1", "") == 1

    def test_without_human_confirmed_blocked(self, td):
        """Без human_confirmed self-ingested запись НЕ создаётся (анти-самоотравление)."""
        rc = record(td, "wi-0", "Правка без подтверждения куратора.", at="2026-07-15")
        f = Path(td) / "lessons-learned" / "2026-07-15-wi-0.md"
        assert rc == 1
        assert not f.exists()


@pytest.mark.unit
class TestRecordWithHumanConfirmed:
    @pytest.fixture(autouse=True)
    def setup_record(self, td):
        self.td = td
        self.rc = record(
            td, "wi-1", "Добавлено редактирование дашборда после создания.",
            areas=["dashboard-editor", "session-context"],
            decisions="dashboard хранит source_session_id",
            lessons="теряется связь artifact<->session; добавить версионирование",
            at="2026-07-15", human_confirmed=True,
        )
        self.f = Path(td) / "lessons-learned" / "2026-07-15-wi-1.md"

    def test_file_created(self):
        assert self.rc == 0
        assert self.f.exists()

    def test_contains_summary(self):
        txt = self.f.read_text(encoding="utf-8")
        assert "редактирование дашборда" in txt

    def test_contains_areas(self):
        txt = self.f.read_text(encoding="utf-8")
        assert "dashboard-editor" in txt

    def test_contains_decisions(self):
        txt = self.f.read_text(encoding="utf-8")
        assert "source_session_id" in txt

    def test_contains_lessons(self):
        txt = self.f.read_text(encoding="utf-8")
        assert "версионирование" in txt

    def test_references_decisions_registry(self):
        txt = self.f.read_text(encoding="utf-8")
        assert "decisions/registry.yaml" in txt


@pytest.mark.unit
class TestGovernanceFailClosed:
    def test_enforcement_crash_blocks_record(self, td):
        """governance enforcement упал -> BLOCKED, файл НЕ создан (fail-closed)."""
        from ai_ops_kit.security import security_enforcement as _se
        _orig = _se.enforce_memory_entry
        _se.enforce_memory_entry = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            rc = record(td, "wi-crash", "правка", at="2026-07-15", human_confirmed=True)
        finally:
            _se.enforce_memory_entry = _orig
        f = Path(td) / "lessons-learned" / "2026-07-15-wi-crash.md"
        assert rc == 1
        assert not f.exists()
