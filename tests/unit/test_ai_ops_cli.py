"""Unit tests for tools/ai_ops_cli.py — CLI entry point and intent dispatch.

Tests resolve_flags, build_preview, INTENTS registry, and the main() CLI
entry point. Complements the selftest wrapper with granular assertions.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT / "tools"))

import ai_ops_cli


@pytest.mark.critical_path
@pytest.mark.unit
class TestIntentsRegistry:
    """Tests for INTENTS — the intent registry."""

    def test_intents_count(self):
        """INTENTS should have exactly 14 intents (v3.35: +next, +model)."""
        assert len(ai_ops_cli.INTENTS) == 14

    def test_intents_contain_expected(self):
        """INTENTS should contain all expected intent names."""
        expected = {"new", "onboard", "discuss", "specify", "plan", "run",
                    "do", "advise", "resume", "review", "status", "health",
                    # v3.35 Product Operating Model: план продукта и понимание репозитория.
                    "next", "model"}
        assert set(ai_ops_cli.INTENTS.keys()) == expected

    def test_each_intent_has_required_fields(self):
        """Each intent should have (description, action, needs_task_text)."""
        for name, entry in ai_ops_cli.INTENTS.items():
            assert len(entry) == 3, f"Intent {name} should have 3 fields"
            desc, action, needs_task = entry
            assert isinstance(desc, str)
            assert isinstance(action, str)
            assert isinstance(needs_task, bool)


@pytest.mark.critical_path
@pytest.mark.unit
class TestResolveFlags:
    """Tests for resolve_flags — preset flag resolution from signals."""

    def test_quick_flags(self):
        """QUICK task should have sandbox + baseline_diff ON, review + author OFF."""
        signals = {"task_type": "QUICK"}
        flags = ai_ops_cli.resolve_flags(signals)
        assert flags["sandbox"] is True
        assert flags["baseline_diff"] is True
        assert flags["review"] is False
        assert flags["author"] is False

    def test_engineering_flags(self):
        """ENGINEERING task should have review + author ON."""
        signals = {"task_type": "ENGINEERING"}
        flags = ai_ops_cli.resolve_flags(signals)
        assert flags["review"] is True
        assert flags["author"] is True

    def test_engine_is_always_pipeline(self):
        """engine should always be 'pipeline'."""
        signals = {"task_type": "QUICK"}
        flags = ai_ops_cli.resolve_flags(signals)
        assert flags["engine"] == "pipeline"


@pytest.mark.critical_path
@pytest.mark.unit
class TestBuildPreview:
    """Tests for build_preview — execution preview generation."""

    def test_preview_kind(self, child_root):
        """build_preview should return kind=ExecutionPreview."""
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
        (child_root / "package.json").write_text('{"name": "test"}')

        preview = ai_ops_cli.build_preview(
            intent="plan",
            task="implement feature X",
            child_root=child_root,
            signals={"task_type": "ENGINEERING"},
        )
        assert preview["kind"] == "ExecutionPreview"
        assert preview["schema_version"] == 1

    def test_preview_contains_understood(self, child_root):
        """Preview should contain 'understood' section with task type."""
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)

        preview = ai_ops_cli.build_preview(
            intent="plan",
            task="fix a bug",
            child_root=child_root,
            signals={"task_type": "QUICK"},
        )
        assert "understood" in preview
        assert preview["understood"]["task_type"] == "QUICK"

    def test_preview_contains_will_do(self, child_root):
        """Preview should contain 'will_do' section with stages."""
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)

        preview = ai_ops_cli.build_preview(
            intent="run",
            task="test task",
            child_root=child_root,
            signals={"task_type": "QUICK"},
        )
        assert "will_do" in preview
        assert "stages" in preview["will_do"]

    def test_preview_contains_approvals(self, child_root):
        """Preview should contain 'approvals_needed' list."""
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)

        preview = ai_ops_cli.build_preview(
            intent="run",
            task="test task",
            child_root=child_root,
            signals={"task_type": "QUICK"},
        )
        assert "approvals_needed" in preview
        assert isinstance(preview["approvals_needed"], list)


@pytest.mark.critical_path
@pytest.mark.unit
class TestCriticalApproval:
    """Tests for CRITICAL task — requires human approval."""

    def test_critical_task_needs_approval(self, child_root):
        """CRITICAL task should produce human-approval requirement."""
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)

        preview = ai_ops_cli.build_preview(
            intent="run",
            task="critical change",
            child_root=child_root,
            signals={"task_type": "CRITICAL"},
        )
        assert len(preview["approvals_needed"]) > 0


@pytest.mark.critical_path
@pytest.mark.unit
class TestDecompositionAdvice:
    """Tests for decomposition_advised — large task detection."""

    def test_large_task_decomposition_advised(self, child_root):
        """Large task with many affected areas should get decomposition_advised=True."""
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)

        preview = ai_ops_cli.build_preview(
            intent="run",
            task="large refactoring across many modules",
            child_root=child_root,
            signals={
                "task_type": "ENGINEERING",
                "size": "large",
                "affected_areas": ["auth", "api", "ui", "database", "tests", "docs"],
            },
        )
        assert preview["decomposition_advised"] is True


@pytest.mark.critical_path
@pytest.mark.unit
@pytest.mark.slow   # тяжёлая обёртка селфтеста: в быстрый профиль не входит
class TestMainCLI:
    """Tests for main() — CLI entry point."""
    # test_main_selftest удалён: тело переехало в tests/unit/test_ai_ops_cli_selftest.py

    def test_main_preview_returns_zero(self, child_root, monkeypatch):
        """main(['preview', 'plan', ...]) should return 0 (preview only)."""
        monkeypatch.chdir(child_root)
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)

        import os
        old_cwd = os.getcwd()
        try:
            os.chdir(child_root)
            rc = ai_ops_cli.main(["preview", "plan", "test task", str(child_root)])
            assert rc == 0
        finally:
            os.chdir(old_cwd)


@pytest.mark.critical_path
@pytest.mark.unit
class TestOnboardIntent:
    """Tests for onboard intent — repository profile detection."""

    def test_onboard_writes_profile(self, child_root):
        """onboard intent should write .ai/repository-profile.yaml."""
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=child_root, capture_output=True)
        (child_root / "package.json").write_text('{"name": "test"}')
        subprocess.run(["git", "add", "."], cwd=child_root, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=child_root, capture_output=True)

        import os
        old_cwd = os.getcwd()
        try:
            os.chdir(child_root)
            rc = ai_ops_cli.main(["onboard", str(child_root)])
            assert rc == 0
            profile = child_root / ".ai" / "repository-profile.yaml"
            assert profile.is_file()
        finally:
            os.chdir(old_cwd)


@pytest.mark.unit
class TestDegradedContextIsVisible:
    """Проглоченное исключение не должно выглядеть нормальным результатом.

    Внешнее ревью назвало этот случай поимённо среди 137 `except Exception`: сбой
    compile_bundle уходил в `bundle = None`, и превью печатало «агентов 0 · ~None ток.» — прогон
    с несобранным контекстом ничем не отличался от обычного.
    """

    def _broken_bundle(self, monkeypatch):
        import context_compiler

        def _boom(*a, **kw):
            raise RuntimeError("реестр недоступен")

        monkeypatch.setattr(context_compiler, "compile_bundle", _boom)

    def test_preview_reports_context_failure(self, tmp_path, monkeypatch):
        self._broken_bundle(monkeypatch)
        pv = ai_ops_cli.build_preview("run", "задача", tmp_path, {"task_type": "QUICK"})
        assert "RuntimeError" in (pv["data_used"]["context_error"] or ""), \
            "сбой сборки контекста не виден машиночитаемому потребителю превью"

    def test_printed_preview_warns_loudly(self, tmp_path, monkeypatch, capsys):
        self._broken_bundle(monkeypatch)
        pv = ai_ops_cli.build_preview("run", "задача", tmp_path, {"task_type": "QUICK"})
        ai_ops_cli._print_preview(pv)
        out = capsys.readouterr().out
        assert "КОНТЕКСТ НЕ СОБРАН" in out
        assert "агентов 0" not in out, "деградация всё ещё показана как нормальные данные"

    def test_healthy_preview_has_no_error_and_prints_numbers(self, tmp_path, capsys):
        (tmp_path / "pyproject.toml").write_text("[project]\nname='d'\n", encoding="utf-8")
        pv = ai_ops_cli.build_preview("run", "задача", tmp_path, {"task_type": "QUICK"})
        assert pv["data_used"]["context_error"] is None
        ai_ops_cli._print_preview(pv)
        out = capsys.readouterr().out
        assert "данные: агентов" in out and "КОНТЕКСТ НЕ СОБРАН" not in out
