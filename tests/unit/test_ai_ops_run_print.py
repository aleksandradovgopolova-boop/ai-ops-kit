"""Юнит-тесты ai_ops_run: человеко-читаемый вывод прогона (print_human/_print_pipeline)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]

from ai_ops_kit.engine import ai_ops_run


@pytest.mark.critical_path
@pytest.mark.unit
class TestPrintPipeline:
    """Tests for _print_pipeline — pipeline report formatting."""

    def test_error_report(self, capsys):
        """Error report -> prints error message."""
        report = {
            "kind": "execution-pipeline",
            "status": "error",
            "workitem_id": "test-err",
            "error": "something broke",
        }
        ai_ops_run._print_pipeline(report)
        captured = capsys.readouterr()
        assert "ОШИБКА" in captured.out
        assert "something broke" in captured.out

    def test_ready_report(self, capsys):
        """Ready report -> prints READY_FOR_PR."""
        report = {
            "kind": "execution-pipeline",
            "status": "done",
            "workitem_id": "test-ok",
            "ready_for_pr": True,
            "provider": "mock",
            "runtime": "claude-code",
            "loop": {"stopped": "done", "steps": 3, "applied_writes": 2, "denied": 0},
            "commit": {"sha": "abc123def456", "branch": "ai-ops/test",
                       "evidence_on_exact_sha": True, "tree_clean_before_checks": True},
            "gates": {"evaluated": ["tests", "lint"], "unmet": [], "blocked": False},
            "lifecycle": {"concurrency_preflight": {"conflicts": []}},
        }
        ai_ops_run._print_pipeline(report)
        captured = capsys.readouterr()
        assert "READY_FOR_PR" in captured.out
        assert "abc123def456" in captured.out

    def test_not_ready_report(self, capsys):
        """Not-ready report -> prints NOT_READY."""
        report = {
            "kind": "execution-pipeline",
            "status": "done",
            "workitem_id": "test-nr",
            "ready_for_pr": False,
            "provider": "mock",
            "runtime": "claude-code",
            "loop": {"stopped": "budget", "steps": 40, "applied_writes": 5, "denied": 1},
            "gates": {"evaluated": ["tests"], "unmet": ["tests"], "blocked": True},
        }
        ai_ops_run._print_pipeline(report)
        captured = capsys.readouterr()
        assert "NOT_READY" in captured.out

    def test_report_with_context_bundle(self, capsys):
        """Report with context_bundle -> prints context info."""
        report = {
            "kind": "execution-pipeline",
            "status": "done",
            "workitem_id": "test-ctx",
            "ready_for_pr": True,
            "provider": "mock",
            "runtime": "claude-code",
            "loop": {"stopped": "done", "steps": 1, "applied_writes": 0, "denied": 0},
            "gates": {"evaluated": [], "unmet": [], "blocked": False},
            "context_bundle": {
                "estimated_tokens": 500,
                "context_budget": 10000,
                "overflow": False,
                "agents": ["agent1"],
                "excluded_count": 3,
            },
        }
        ai_ops_run._print_pipeline(report)
        captured = capsys.readouterr()
        assert "500" in captured.out
        assert "10000" in captured.out

    def test_report_with_spec_coverage(self, capsys):
        """Report with spec_coverage -> prints spec info."""
        report = {
            "kind": "execution-pipeline",
            "status": "done",
            "workitem_id": "test-spec",
            "ready_for_pr": True,
            "provider": "mock",
            "runtime": "claude-code",
            "loop": {"stopped": "done", "steps": 1, "applied_writes": 0, "denied": 0},
            "gates": {"evaluated": [], "unmet": [], "blocked": False},
            "spec_coverage": {
                "level": 0,
                "level_name": "L0-minimal",
                "escalated_from": None,
                "blocking_missing": [],
                "needs_human": [],
            },
        }
        ai_ops_run._print_pipeline(report)
        captured = capsys.readouterr()
        assert "L0-minimal" in captured.out

    def test_report_with_exemptions(self, capsys):
        """Report with exemptions -> prints them."""
        report = {
            "kind": "execution-pipeline",
            "status": "done",
            "workitem_id": "test-ex",
            "ready_for_pr": True,
            "provider": "mock",
            "runtime": "claude-code",
            "loop": {"stopped": "done", "steps": 1, "applied_writes": 0, "denied": 0},
            "gates": {"evaluated": [], "unmet": [], "blocked": False},
            "exemptions": ["security_scan", "perf_bench"],
        }
        ai_ops_run._print_pipeline(report)
        captured = capsys.readouterr()
        assert "security_scan" in captured.out
        assert "perf_bench" in captured.out

    def test_report_with_not_yet(self, capsys):
        """Report with not_yet items -> prints them."""
        report = {
            "kind": "execution-pipeline",
            "status": "done",
            "workitem_id": "test-ny",
            "ready_for_pr": False,
            "provider": "mock",
            "runtime": "claude-code",
            "loop": {"stopped": "done", "steps": 1, "applied_writes": 0, "denied": 0},
            "gates": {"evaluated": [], "unmet": ["tests"], "blocked": True},
            "not_yet": ["need live proposer", "tests not passing"],
        }
        ai_ops_run._print_pipeline(report)
        captured = capsys.readouterr()
        assert "need live proposer" in captured.out

    # P1 (аудит «непесочный дефолт + сеть ON»): поза изоляции ВИДНА, а не молчит. Дефолт НЕ флипаем —
    # находка закрывается честностью: пониженную изоляцию называем человеку, но ТОЛЬКО когда прогон
    # реально работал (были правки), не на dry-run/preview.
    @staticmethod
    def _iso_report(*, sandboxed, network="on", applied_writes=2, sha="abc123def456"):
        commit = {"sha": sha, "branch": "ai-ops/test", "evidence_on_exact_sha": True,
                  "tree_clean_before_checks": True, "changed_files": ["a.py"]} if sha else {}
        return {
            "kind": "execution-pipeline", "status": "done", "workitem_id": "test-iso",
            "ready_for_pr": True, "provider": "claude-cli", "runtime": "claude-code",
            "loop": {"stopped": "done", "steps": 2, "applied_writes": applied_writes, "denied": 0},
            "commit": commit,
            "gates": {"evaluated": ["tests"], "unmet": [], "blocked": False},
            "isolation": {"worktree": None, "sandboxed": sandboxed, "network": network},
        }

    def test_no_sandbox_real_work_prints_posture_note(self, capsys):
        """(а) sandbox=False + реальные правки -> отчёт несёт sandboxed=False и печатается честная нота."""
        report = self._iso_report(sandboxed=False, network="on", applied_writes=2)
        assert report["isolation"]["sandboxed"] is False
        ai_ops_run._print_pipeline(report)
        out = capsys.readouterr().out
        assert "без песочницы" in out
        assert "sandbox off" in out
        assert "сеть доступна модельному shell" in out
        assert "run-sandboxed.sh" in out

    def test_sandbox_on_no_posture_note(self, capsys):
        """(б) sandbox=True -> пониженной изоляции нет, ноты нет."""
        report = self._iso_report(sandboxed=True, network="restricted", applied_writes=2)
        ai_ops_run._print_pipeline(report)
        out = capsys.readouterr().out
        assert "без песочницы" not in out

    def test_no_sandbox_but_no_work_no_note(self, capsys):
        """(в) dry-run/preview (без записей и коммита) -> ноту не сыплем, даже если sandbox off."""
        report = self._iso_report(sandboxed=False, network="on", applied_writes=0, sha=None)
        ai_ops_run._print_pipeline(report)
        out = capsys.readouterr().out
        assert "без песочницы" not in out

    def test_posture_note_fail_closed_without_field(self, capsys):
        """Fail-closed: убрать isolation.sandboxed -> поза снова невидима (ноты нет)."""
        report = self._iso_report(sandboxed=False, network="on", applied_writes=2)
        report["isolation"].pop("sandboxed")
        ai_ops_run._print_pipeline(report)
        out = capsys.readouterr().out
        assert "без песочницы" not in out


@pytest.mark.critical_path
@pytest.mark.unit
class TestPrintHuman:
    """Tests for print_human — human-readable report output."""

    def test_print_human_no_crash(self, child_root):
        """print_human should not crash on pipeline reports."""
        report = {
            "kind": "execution-pipeline",
            "status": "done",
            "workitem_id": "test",
            "loop": {"stopped": "done"},
            "gates": {"blocked": False, "unmet_gates": []},
        }
        # Should not raise
        ai_ops_run.print_human(report)

    def test_print_human_controller_report(self, capsys):
        """print_human on controller report -> prints tracks and gates."""
        report = {
            "kind": "run-report",
            "workitem_id": "ctl-test",
            "status": "planned",
            "base_workflow": "quick-fix",
            "execution": "planned",
            "runtime": "claude-code",
            "required_tracks": ["IMPL", "TEST"],
            "conditional_tracks": ["DOCS"],
            "gates": ["base_build", "lint"],
            "skipped_tracks": [{"track": "PERF", "reason": "not needed"}],
        }
        ai_ops_run.print_human(report)
        captured = capsys.readouterr()
        assert "ctl-test" in captured.out
        assert "planned" in captured.out
        assert "IMPL" in captured.out

    def test_print_human_minimal_blocked_report_does_not_crash(self, capsys):
        """Минимальный отчёт отказа active-work (без base_workflow/треков) НЕ роняет вывод.
        Замер поля 01.09.2026: печать такого отчёта падала KeyError('base_workflow') — прогон
        завершался, а print_human ронял процесс. Теперь печатает коротко: id, статус, причину."""
        report = {"schema_version": 1, "kind": "run-report", "workitem_id": "mat-ready",
                  "status": "blocked", "blocked_by": "active-work",
                  "error": "работа не начата: заявку держит другая сессия"}
        ai_ops_run.print_human(report)          # НЕ должно бросать KeyError
        out = capsys.readouterr().out
        assert "mat-ready" in out and "blocked" in out
        assert "active-work" in out

    def test_print_human_pipeline_delegates(self, capsys):
        """print_human on pipeline kind -> delegates to _print_pipeline."""
        report = {
            "kind": "execution-pipeline",
            "status": "error",
            "workitem_id": "pipe-err",
            "error": "test error",
        }
        ai_ops_run.print_human(report)
        captured = capsys.readouterr()
        assert "pipeline" in captured.out
