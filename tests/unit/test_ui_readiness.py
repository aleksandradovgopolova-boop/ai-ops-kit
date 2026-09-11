"""Гранулярные тесты ui_readiness (мигрировано из test_ui_readiness_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import tempfile

import pytest

from ai_ops_kit.ui.ui_readiness import (
    Path,
    assess,
    check,
    script_template,
    should_run_ui_evidence,
)


@pytest.mark.unit
class TestShouldRunUiEvidence:
    def test_tsx_change_ui_on(self):
        r, _ = should_run_ui_evidence(["src/features/x.tsx"])
        assert r is True

    def test_non_ui_change_ui_off(self):
        r, _ = should_run_ui_evidence(["server/api.py"])
        assert r is False

    def test_visual_task_ui_on(self):
        r, _ = should_run_ui_evidence(["docs/readme.md"], {"task_type": "VISUAL"})
        assert r is True

    def test_storybook_file_ui_on(self):
        r, _ = should_run_ui_evidence([".storybook/main.ts"])
        assert r is True


@pytest.mark.unit
class TestAssess:
    def test_empty_repo_maturity_absent(self):
        with tempfile.TemporaryDirectory() as td:
            a = assess(td)
            assert a["storybook_maturity"] == "absent"

    def test_empty_repo_check_valid_no_deps(self):
        with tempfile.TemporaryDirectory() as td:
            a = assess(td)
            assert check(a) == []
            assert a["installs_dependencies"] is False

    def test_storybook_dir_no_script_configured(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / ".storybook").mkdir()
            (Path(td) / "package.json").write_text('{"name":"x"}', encoding="utf-8")
            a = assess(td)
            assert a["storybook_maturity"] == "configured"

    def test_dep_and_build_script_runnable(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "package.json").write_text(
                '{"devDependencies":{"storybook":"^8"},"scripts":{"build-storybook":"storybook build -o storybook-static"}}',
                encoding="utf-8")
            a = assess(td)
            assert a["storybook_maturity"] == "runnable"

    def test_preview_workflow_absent_by_default(self):
        """Честный факт: превью в PR не доставлено, пока файла workflow нет в дереве дочки."""
        with tempfile.TemporaryDirectory() as td:
            assert assess(td)["preview_workflow"] is False

    def test_preview_workflow_detected_when_delivered(self):
        """Доставлен workflow превью -> assess это ВИДИТ (факт из дерева), а `_fmt` называет «ВКЛЮЧЕНО».

        Мутация: убрать поле preview_workflow из assess -> ui-status не отличит доставленное превью
        от недоставленного, тест краснеет."""
        from ai_ops_kit.ui.ui_readiness import _fmt
        with tempfile.TemporaryDirectory() as td:
            wf = Path(td) / ".github" / "workflows"
            wf.mkdir(parents=True)
            (wf / "ai-ops-storybook-preview.yml").write_text("name: x\n", encoding="utf-8")
            a = assess(td)
            assert a["preview_workflow"] is True
            assert "ВКЛЮЧЕНО" in _fmt(a), "ui-status не показал доставленное превью как включённое"


@pytest.mark.unit
class TestCheck:
    def test_installs_dependencies_true_error(self):
        errors = check({
            "kind": "UIReadiness",
            "storybook_maturity": "absent",
            "installs_dependencies": True,
            "evidence_status": {},
        })
        assert any("не ставит зависимости" in x for x in errors)


@pytest.mark.unit
class TestScriptTemplate:
    def test_no_deps_warning(self):
        assert "_note" in script_template()
