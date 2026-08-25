"""Гранулярные тесты project_detector (мигрировано из test_project_detector_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import json
import tempfile

import pytest

from project_detector import (
    PROFILE_REL,
    Path,
    detect,
    load_or_detect,
)


@pytest.mark.unit
class TestNodeDetection:
    @pytest.fixture(autouse=True)
    def setup_node_repo(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "package.json").write_text(json.dumps({
                "dependencies": {"react": "^18", "next": "^14"},
                "devDependencies": {"typescript": "^5", "eslint": "^9"},
                "scripts": {"build": "next build", "lint": "eslint .", "test": "vitest",
                            "typecheck": "tsc --noEmit"}}),
                encoding="utf-8")
            (root / "package-lock.json").write_text("{}", encoding="utf-8")
            (root / ".github" / "workflows").mkdir(parents=True)
            self.prof = detect(root)
            self.stack = self.prof["stacks"][0]

    def test_node_detected_with_npm(self):
        assert self.stack["language"] == "node"
        assert self.stack["package_manager"] == "npm"

    def test_frameworks_next_react(self):
        assert {"next", "react"} <= set(self.stack["frameworks"])

    def test_commands_from_scripts(self):
        assert self.stack["commands"]["build"] == "npm run build"
        assert self.stack["commands"]["test"] == "npm run test"
        assert self.stack["commands"]["typecheck"] == "npm run typecheck"

    def test_install_command_npm_ci(self):
        assert self.stack.get("install_command") == "npm ci"

    def test_ci_detected(self):
        assert "github-actions" in self.prof["ci"]

    def test_status_draft(self):
        assert self.prof["status"] == "draft"


@pytest.mark.unit
class TestPythonPoetryDetection:
    @pytest.fixture(autouse=True)
    def setup_python_repo(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "pyproject.toml").write_text(
                "[tool.poetry]\nname='x'\n[tool.poetry.dependencies]\nfastapi='*'\npytest='*'\nmypy='*'\n",
                encoding="utf-8")
            (root / "tests").mkdir()
            self.prof = detect(root)
            self.stack = self.prof["stacks"][0]

    def test_python_detected_with_poetry(self):
        assert self.stack["language"] == "python"
        assert self.stack["package_manager"] == "poetry"

    def test_fastapi_in_frameworks(self):
        assert "fastapi" in self.stack["frameworks"]

    def test_test_and_typecheck_commands(self):
        assert self.stack["commands"]["test"] == "pytest"
        assert self.stack["commands"]["typecheck"] == "mypy ."


@pytest.mark.unit
class TestEmptyRepo:
    def test_empty_repo_undetermined(self):
        with tempfile.TemporaryDirectory() as td:
            prof = detect(Path(td))
            assert prof["stacks"] == []
            assert any("стек не определён" in u for u in prof["undetermined"])


@pytest.mark.unit
class TestJavaWrappers:
    def test_gradlew_preferred(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "build.gradle").write_text("plugins {}\n", encoding="utf-8")
            (root / "gradlew").write_text("#!/bin/sh\n", encoding="utf-8")
            s = detect(root)["stacks"][0]
            assert s["commands"]["build"] == "./gradlew build"
            assert s["commands"]["test"] == "./gradlew test"

    def test_mvn_fallback_without_wrapper(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "pom.xml").write_text("<project/>\n", encoding="utf-8")
            s = detect(root)["stacks"][0]
            assert s["commands"]["build"] == "mvn -q package"

    def test_mvnw_preferred(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "pom.xml").write_text("<project/>\n", encoding="utf-8")
            (root / "mvnw").write_text("#!/bin/sh\n", encoding="utf-8")
            s = detect(root)["stacks"][0]
            assert s["commands"]["test"] == "./mvnw -q test"


@pytest.mark.unit
class TestMonorepo:
    def test_pnpm_workspace_monorepo(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "package.json").write_text("{}", encoding="utf-8")
            (root / "pnpm-workspace.yaml").write_text("packages:\n  - 'packages/*'\n", encoding="utf-8")
            prof = detect(root)
            assert prof["monorepo"] is True
            assert "pnpm-workspace" in (prof.get("monorepo_reason") or "")

    def test_monorepo_undetermined_note(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "package.json").write_text("{}", encoding="utf-8")
            (root / "pnpm-workspace.yaml").write_text("packages:\n  - 'packages/*'\n", encoding="utf-8")
            prof = detect(root)
            assert any("монорепо" in u for u in prof["undetermined"])

    def test_apps_packages_dirs_monorepo(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "apps").mkdir()
            (root / "packages").mkdir()
            (root / "apps" / "package.json").write_text("{}", encoding="utf-8")
            (root / "packages" / "package.json").write_text("{}", encoding="utf-8")
            assert detect(root)["monorepo"] is True

    def test_single_package_json_not_monorepo(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "package.json").write_text(json.dumps({"scripts": {"build": "tsc"}}), encoding="utf-8")
            assert detect(root)["monorepo"] is False


@pytest.mark.unit
class TestCommandEvidence:
    def test_no_runner_commands_are_none(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
            s = detect(root)["stacks"][0]
            assert s["commands"]["test"] is None
            assert s["commands"]["lint"] is None
            assert s["command_evidence"] == {}

    def test_pytest_ini_ruff_toml_detected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
            (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
            (root / ".ruff.toml").write_text("line-length = 100\n", encoding="utf-8")
            s = detect(root)["stacks"][0]
            assert s["commands"]["test"] == "pytest"
            assert s["commands"]["lint"] == "ruff check ."
            assert s["command_evidence"]["test"] == "pytest.ini"
            assert s["command_evidence"]["lint"] == ".ruff.toml"


@pytest.mark.unit
class TestLoadOrDetect:
    def test_profile_written_with_manifest_hash(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".ai").mkdir()
            (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
            p1 = load_or_detect(root)
            assert (root / PROFILE_REL).is_file()
            assert p1.get("manifest_hash")

    def test_stale_cache_reread(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".ai").mkdir()
            (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
            p1 = load_or_detect(root)
            (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
            p2 = load_or_detect(root)
            assert p2["manifest_hash"] != p1["manifest_hash"]
            assert p2["stacks"][0]["commands"]["test"] == "pytest"

    def test_fresh_cache_returned_without_redetect(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".ai").mkdir()
            (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
            (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
            p2 = load_or_detect(root)
            assert load_or_detect(root)["manifest_hash"] == p2["manifest_hash"]
