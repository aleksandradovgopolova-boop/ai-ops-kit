"""Гранулярные тесты ui_readiness (мигрировано из test_ui_readiness_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import tempfile

import pytest

from ui_readiness import (
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
