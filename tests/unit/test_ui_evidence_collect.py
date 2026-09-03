"""Гранулярные тесты ui_evidence_collect (мигрировано из test_ui_evidence_collect_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import tempfile

import pytest

from ai_ops_kit.ui.ui_evidence_collect import (
    Path,
    collect,
    is_ui_stack,
    json,
)


@pytest.mark.unit
class TestIsUiStack:
    def test_python_only_not_ui(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "pyproj").mkdir()
            assert is_ui_stack(root) is False

    def test_package_json_with_storybook_is_ui(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "package.json").write_text(json.dumps({
                "scripts": {"ui-evidence": "bash scripts/ui-evidence.sh"},
                "devDependencies": {"@storybook/react-vite": "^8"}}), encoding="utf-8")
            assert is_ui_stack(root) is True

    def test_package_json_without_storybook_not_ui(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "package.json").write_text(json.dumps({"dependencies": {"react": "^18"}}), encoding="utf-8")
            assert is_ui_stack(root) is False


@pytest.mark.unit
class TestCollect:
    def test_collect_without_npm_meta_written(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "package.json").write_text(json.dumps({
                "scripts": {"ui-evidence": "bash scripts/ui-evidence.sh"},
                "devDependencies": {"@storybook/react-vite": "^8"}}), encoding="utf-8")
            res = collect(root, "abc123def", run_npm=False)
            assert res["skipped"] is False

    def test_meta_commit_sha_binding(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "package.json").write_text(json.dumps({
                "scripts": {"ui-evidence": "bash scripts/ui-evidence.sh"},
                "devDependencies": {"@storybook/react-vite": "^8"}}), encoding="utf-8")
            collect(root, "abc123def", run_npm=False)
            meta = json.loads((root / ".ai" / "ui-evidence" / "meta.json").read_text())
            assert meta["commit_sha"] == "abc123def"

    def test_collect_without_commit_sha_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "package.json").write_text(json.dumps({
                "scripts": {"ui-evidence": "bash scripts/ui-evidence.sh"},
                "devDependencies": {"@storybook/react-vite": "^8"}}), encoding="utf-8")
            assert collect(root, None, run_npm=False)["skipped"] is True
