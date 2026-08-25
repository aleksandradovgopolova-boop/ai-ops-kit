"""Granular tests for validate_standalone_engine (migrated from selftest)."""
from __future__ import annotations

import pytest

from validate_standalone_engine import (  # noqa: F401
    PKG,
    Path,
    build_managed,
    missing_closure,
    run_standalone,
    subprocess,
    tempfile,
)


@pytest.fixture
def engine_env():
    """Build managed layer and create a child repo for standalone runs."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        managed = root / ".ai" / "managed"
        n = build_managed(PKG, managed)

        child = root / "childrepo"
        child.mkdir()
        subprocess.run(["git", "-C", str(child), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(child), "config", "user.email", "t@t"], check=True)
        subprocess.run(["git", "-C", str(child), "config", "user.name", "t"], check=True)
        (child / "src").mkdir()
        (child / "pyproject.toml").write_text("[tool.poetry]\n", encoding="utf-8")
        (child / "f").write_text("x", encoding="utf-8")
        subprocess.run(["git", "-C", str(child), "add", "-A"], check=True)
        subprocess.run(
            ["git", "-C", str(child), "commit", "-q", "-m", "init"], check=True
        )

        yield root, managed, child


@pytest.mark.unit
@pytest.mark.slow
class TestBuildManaged:
    """Building the managed layer."""

    def test_managed_layer_built_from_managed_set(self, engine_env):
        _, managed, _ = engine_env
        assert (managed / "tools" / "ai_ops_run.py").exists()

    def test_runtime_closure_complete(self, engine_env):
        _, managed, _ = engine_env
        miss = missing_closure(managed)
        assert not miss

    def test_engine_present_in_managed(self, engine_env):
        _, managed, _ = engine_env
        assert (managed / "tools" / "ai_ops_run.py").exists()


@pytest.mark.unit
@pytest.mark.slow
class TestRunStandalone:
    """Running the standalone engine pipeline."""

    def test_standalone_produces_valid_report(self, engine_env):
        _, managed, child = engine_env
        rep = run_standalone(managed, child)
        assert rep is not None and rep.get("kind") == "execution-pipeline"

    def test_standalone_real_commit_on_ai_ops_branch(self, engine_env):
        _, managed, child = engine_env
        rep = run_standalone(managed, child)
        commit = rep.get("commit") or {}
        assert (
            isinstance(commit.get("sha"), str)
            and len(commit.get("sha") or "") == 40
            and (commit.get("branch") or "").startswith("ai-ops/")
        )

    def test_standalone_evidence_on_exact_sha(self, engine_env):
        _, managed, child = engine_env
        rep = run_standalone(managed, child)
        commit = rep.get("commit") or {}
        assert commit.get("evidence_on_exact_sha") is True

    def test_standalone_ready_for_pr(self, engine_env):
        _, managed, child = engine_env
        rep = run_standalone(managed, child)
        assert rep.get("ready_for_pr") is True

    def test_standalone_containment_active(self, engine_env):
        _, managed, child = engine_env
        rep = run_standalone(managed, child)
        assert (rep.get("containment") or {}).get("block_push") is True
        assert (rep.get("containment") or {}).get("sandbox") is True

    def test_standalone_file_written_in_child(self, engine_env):
        _, managed, child = engine_env
        run_standalone(managed, child)
        assert (
            child / ".ai" / "worktrees" / "standalone-add" / "src" / "add.py"
        ).exists()


@pytest.mark.unit
@pytest.mark.slow
class TestCompleteness:
    """Detecting missing engine files."""

    def test_completeness_catches_missing_engine_file(self, engine_env):
        _, managed, _ = engine_env
        (managed / "tools" / "tool_broker.py").unlink()
        assert "tools/tool_broker.py" in missing_closure(managed)
