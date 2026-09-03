"""Гранулярные тесты evidence_collector (мигрировано из test_evidence_collector_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import subprocess

import pytest

from ai_ops_kit.engine import tool_broker
from ai_ops_kit.gates.evidence_collector import (
    Path,
    collect,
    project_detector,
)


@pytest.fixture
def git_repo(tmp_path):
    """Минимальный git-репозиторий для тестов."""
    root = tmp_path
    subprocess.run(["git", "-C", str(root), "init", "-q"])
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t"])
    subprocess.run(["git", "-C", str(root), "config", "user.name", "t"])
    (root / "f").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"])
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "i"])
    return root


@pytest.fixture
def policy():
    return tool_broker.Policy(level="execution")


@pytest.fixture
def broker():
    return tool_broker


@pytest.mark.unit
class TestCollectAllPass:
    def test_gate_pass(self, git_repo, policy):
        prof = {"stacks": [{"language": "demo", "commands": {
            "build": "true", "lint": "true", "typecheck": None, "test": "python3 -c \"pass\""}}]}
        r = collect(prof, git_repo, policy, broker=tool_broker)
        ge = r["gate_evidence"]["implementation_verification"]
        assert ge["status"] == "pass"

    def test_provided_contains_passed_flags(self, git_repo, policy):
        prof = {"stacks": [{"language": "demo", "commands": {
            "build": "true", "lint": "true", "typecheck": None, "test": "python3 -c \"pass\""}}]}
        r = collect(prof, git_repo, policy, broker=tool_broker)
        ge = r["gate_evidence"]["implementation_verification"]
        assert {"build_passed", "lint_passed", "tests_passed"} <= set(ge["provided"])

    def test_tested_revision_flag(self, git_repo, policy):
        prof = {"stacks": [{"language": "demo", "commands": {
            "build": "true", "lint": "true", "typecheck": None, "test": "python3 -c \"pass\""}}]}
        r = collect(prof, git_repo, policy, broker=tool_broker)
        ge = r["gate_evidence"]["implementation_verification"]
        assert "tested_revision" in ge["provided"] and r["revision"]

    def test_typecheck_none_not_run(self, git_repo, policy):
        prof = {"stacks": [{"language": "demo", "commands": {
            "build": "true", "lint": "true", "typecheck": None, "test": "python3 -c \"pass\""}}]}
        r = collect(prof, git_repo, policy, broker=tool_broker)
        assert r["checks"]["typecheck"]["status"] == "not_run"
        ge = r["gate_evidence"]["implementation_verification"]
        assert "typecheck_passed" not in ge["provided"]

    def test_structural_evidence_schema(self, git_repo, policy):
        prof = {"stacks": [{"language": "demo", "commands": {
            "build": "true", "lint": "true", "typecheck": None, "test": "python3 -c \"pass\""}}]}
        r = collect(prof, git_repo, policy, broker=tool_broker)
        assert r["schema_evidence"]["build"]["exit_code"] == 0
        assert r["schema_evidence"]["build"]["command"] == "true"
        assert r["schema_evidence"]["build"]["revision"] == r["revision"]


@pytest.mark.unit
class TestCollectFailure:
    def test_command_failure_gate_fail(self, git_repo, policy):
        prof = {"stacks": [{"language": "demo", "commands": {
            "build": "true", "lint": "false", "typecheck": None, "test": "true"}}]}
        r = collect(prof, git_repo, policy, broker=tool_broker)
        ge = r["gate_evidence"]["implementation_verification"]
        assert ge["status"] == "fail"

    def test_lint_failure_no_flag_and_blocker(self, git_repo, policy):
        prof = {"stacks": [{"language": "demo", "commands": {
            "build": "true", "lint": "false", "typecheck": None, "test": "true"}}]}
        r = collect(prof, git_repo, policy, broker=tool_broker)
        ge = r["gate_evidence"]["implementation_verification"]
        assert "lint_passed" not in ge["provided"]
        assert any("lint" in b for b in ge.get("blockers", []))


@pytest.mark.unit
class TestGateEvidenceValidation:
    def test_evidence_valid_by_schema(self, git_repo, policy):
        from ai_ops_kit.gates import gate_executor
        prof = {"stacks": [{"language": "demo", "commands": {
            "build": "true", "lint": "true", "typecheck": None, "test": "python3 -c \"pass\""}}]}
        r = collect(prof, git_repo, policy, broker=tool_broker)
        assert gate_executor.validate_evidence(r["gate_evidence"]) == []


@pytest.mark.unit
class TestDestructiveCommand:
    def test_destructive_command_denied(self, git_repo, policy):
        prof = {"stacks": [{"language": "demo", "commands": {
            "build": "rm -rf /", "lint": None, "typecheck": None, "test": None}}]}
        r = collect(prof, git_repo, policy, broker=tool_broker)
        assert r["checks"]["build"]["status"] == "fail"
        assert any(run.get("denied") for run in r["checks"]["build"]["runs"])


@pytest.mark.unit
class TestProjectDetector:
    def test_detect_and_collect(self, git_repo, policy):
        (git_repo / "pyproject.toml").write_text(
            "[tool.poetry]\nname='x'\n[tool.poetry.dependencies]\npytest='*'\n", encoding="utf-8")
        (git_repo / "tests").mkdir()
        prof = project_detector.detect(git_repo)
        r = collect(prof, git_repo, policy, broker=tool_broker)
        assert r["checks"]["test"]["status"] in ("pass", "fail", "warn")
        assert r["checks"]["test"].get("runs")


@pytest.mark.unit
class TestPytestExit5:
    def test_no_tests_warn_not_fail(self, git_repo, policy):
        prof = {"stacks": [{"language": "demo", "commands": {
            "build": "true", "lint": None, "typecheck": None,
            "test": "bash -c 'exit 5'  # pytest"}}]}
        r = collect(prof, git_repo, policy, broker=tool_broker)
        assert r["checks"]["test"]["status"] == "warn"

    def test_no_tests_no_passed_flag_no_blocker(self, git_repo, policy):
        prof = {"stacks": [{"language": "demo", "commands": {
            "build": "true", "lint": None, "typecheck": None,
            "test": "bash -c 'exit 5'  # pytest"}}]}
        r = collect(prof, git_repo, policy, broker=tool_broker)
        ge = r["gate_evidence"]["implementation_verification"]
        assert "tests_passed" not in ge["provided"]
        assert not any("test" in b for b in ge.get("blockers", []))


@pytest.mark.unit
class TestPolyglot:
    def test_real_test_passes_alongside_pytest_exit5(self, git_repo, policy):
        prof = {"stacks": [
            {"language": "node", "commands": {"build": None, "lint": None, "typecheck": None, "test": "true"}},
            {"language": "python", "commands": {"build": None, "lint": None, "typecheck": None,
                                                "test": "bash -c 'exit 5'  # pytest"}}]}
        r = collect(prof, git_repo, policy, broker=tool_broker)
        ge = r["gate_evidence"]["implementation_verification"]
        assert "tests_passed" in ge["provided"]
        assert r["checks"]["test"]["status"] == "pass"


@pytest.mark.unit
class TestProgressiveVerification:
    @pytest.fixture
    def repo_with_modules(self, git_repo):
        (git_repo / "module_a.py").write_text("def func_a(): return 1\n", encoding="utf-8")
        (git_repo / "module_b.py").write_text("def func_b(): return 2\n", encoding="utf-8")
        (git_repo / "tests").mkdir(exist_ok=True)
        (git_repo / "tests" / "test_a.py").write_text(
            "import module_a\ndef test_a(): assert module_a.func_a() == 1\n", encoding="utf-8")
        (git_repo / "tests" / "test_b.py").write_text(
            "import module_b\ndef test_b(): assert module_b.func_b() == 2\n", encoding="utf-8")
        return git_repo

    def test_without_changed_files_no_verification(self, repo_with_modules, policy):
        prof = {"stacks": [{"language": "python", "commands": {
            "build": None, "lint": None, "typecheck": None,
            "test": "python3 -m pytest tests/"}}]}
        r = collect(prof, repo_with_modules, policy, broker=tool_broker)
        assert r.get("verification") is None

    def test_with_changed_files_verification_info(self, repo_with_modules, policy):
        prof = {"stacks": [{"language": "python", "commands": {
            "build": None, "lint": None, "typecheck": None,
            "test": "python3 -m pytest tests/"}}]}
        r = collect(prof, repo_with_modules, policy, changed_files=["module_a.py"], broker=tool_broker)
        v = r.get("verification")
        assert v is not None

    def test_with_changed_files_tier_affected(self, repo_with_modules, policy):
        prof = {"stacks": [{"language": "python", "commands": {
            "build": None, "lint": None, "typecheck": None,
            "test": "python3 -m pytest tests/"}}]}
        r = collect(prof, repo_with_modules, policy, changed_files=["module_a.py"], broker=tool_broker)
        v = r.get("verification")
        assert v.get("tier") == "affected"

    def test_with_changed_files_affected_tests(self, repo_with_modules, policy):
        prof = {"stacks": [{"language": "python", "commands": {
            "build": None, "lint": None, "typecheck": None,
            "test": "python3 -m pytest tests/"}}]}
        r = collect(prof, repo_with_modules, policy, changed_files=["module_a.py"], broker=tool_broker)
        v = r.get("verification")
        assert "tests/test_a.py" in (v.get("affected_tests") or [])
