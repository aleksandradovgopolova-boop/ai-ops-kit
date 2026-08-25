"""Гранулярные тесты branch_policy (мигрировано из test_branch_policy_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import os
import shutil
import tempfile

import pytest

from gitio import git  # noqa: F401

from branch_policy import (
    DEFAULTS,
    Path,
    assess,
    check_branch,
    is_protected,
    policy_from_config,
    read_state,
    summary_line,
)


def _rules(v, key="violations"):
    return {x["rule"] for x in v[key]}


@pytest.mark.unit
class TestCheckBranchPure:
    def test_fresh_branch_allowed(self):
        good = check_branch("ai-ops/WI-12", "main", behind_count=0, workitems=["WI-12"],
                            base_behind_upstream=0)
        assert good["allowed"] and not good["advisories"]

    def test_direct_commit_to_main_blocked(self):
        prot = check_branch("main", "main", behind_count=0, base_behind_upstream=0)
        assert "direct_commit_to_protected_ref" in _rules(prot)

    def test_release_protected_by_glob(self):
        assert is_protected("release/2026.08", DEFAULTS["protected_refs"])

    def test_normal_branch_not_protected(self):
        assert not is_protected("feature/x", DEFAULTS["protected_refs"])

    def test_main_allowed_when_not_engine_delivery(self):
        assert check_branch("main", "main", 0, engine_delivery=False, base_behind_upstream=0)["allowed"]

    def test_branch_without_prefix_blocked(self):
        named = check_branch("hotfix-quick", "main", behind_count=0, base_behind_upstream=0)
        assert "branch_naming" in _rules(named)

    def test_drift_25_advisory(self):
        drift = check_branch("ai-ops/WI-1", "main", behind_count=25, base_behind_upstream=0)
        assert "base_drift" in _rules(drift, "advisories") and drift["allowed"]

    def test_drift_234_stale(self):
        stale = check_branch("ai-ops/WI-1", "main", behind_count=234, base_behind_upstream=0)
        assert "base_stale" in _rules(stale, "advisories")

    def test_stale_threshold_suppresses_drift(self):
        stale = check_branch("ai-ops/WI-1", "main", behind_count=234, base_behind_upstream=0)
        assert "base_drift" not in _rules(stale, "advisories")

    def test_enforce_block_turns_drift_to_block(self):
        assert not check_branch("ai-ops/WI-1", "main", 234, base_behind_upstream=0,
                                policy={"enforce": "block"})["allowed"]

    def test_unmeasured_drift_unavailable(self):
        unavail = check_branch("ai-ops/WI-1", "main", behind_count=None, base_behind_upstream=None)
        assert {"base_drift", "base_sync"} == {x["rule"] for x in unavail["unavailable"]}
        assert unavail["behind_count"] is None and not unavail["advisories"]

    def test_base_behind_upstream_advisory(self):
        unsynced = check_branch("ai-ops/WI-1", "main", behind_count=0, base_behind_upstream=7)
        assert "base_not_synced" in _rules(unsynced, "advisories")

    def test_multi_workitem_advisory(self):
        multi = check_branch("ai-ops/WI-1", "main", 0, workitems=["WI-1", "WI-2"], base_behind_upstream=0)
        assert "multi_workitem" in _rules(multi, "advisories")

    def test_old_branch_stale_advisory(self):
        old = check_branch("ai-ops/WI-1", "main", 0, base_behind_upstream=0, branch_age_days=30)
        assert "stale_branch" in _rules(old, "advisories")

    def test_unmeasured_age_no_advisory(self):
        assert "stale_branch" not in _rules(
            check_branch("ai-ops/WI-1", "main", 0, base_behind_upstream=0, branch_age_days=None),
            "advisories")

    def test_custom_prefix_respected(self):
        assert check_branch("run/WI-1", "main", 0, base_behind_upstream=0,
                            policy={"branch_prefix": "run/"})["allowed"]

    def test_custom_protected_refs_respected(self):
        assert "direct_commit_to_protected_ref" in _rules(check_branch(
            "trunk", "trunk", 0, base_behind_upstream=0,
            policy={"protected_refs": ["trunk"], "branch_prefix": "ai-ops/"}))


@pytest.fixture
def git_repo():
    """Настоящий git-репозиторий для интеграционных тестов."""
    if not shutil.which("git"):
        pytest.skip("git не найден в PATH")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        env_backup = os.environ.get("GIT_CONFIG_GLOBAL")
        os.environ["GIT_CONFIG_GLOBAL"] = os.devnull
        try:
            git(root, "init", "-q", "-b", "main")
            git(root, "config", "user.email", "t@t")
            git(root, "config", "user.name", "t")
            (root / "a.txt").write_text("1", encoding="utf-8")
            git(root, "add", "-A")
            git(root, "commit", "-q", "-m", "base: первый коммит")
            git(root, "checkout", "-q", "-b", "ai-ops/WI-77")
            (root / "b.txt").write_text("2", encoding="utf-8")
            git(root, "add", "-A")
            git(root, "commit", "-q", "-m", "feat: правка по WI-77")
            git(root, "checkout", "-q", "main")
            for i in range(2):
                (root / f"m{i}.txt").write_text("x", encoding="utf-8")
                git(root, "add", "-A")
                git(root, "commit", "-q", "-m", f"base: коммит {i}")
            git(root, "checkout", "-q", "ai-ops/WI-77")
            yield root
        finally:
            if env_backup is None:
                os.environ.pop("GIT_CONFIG_GLOBAL", None)
            else:
                os.environ["GIT_CONFIG_GLOBAL"] = env_backup


@pytest.mark.unit
class TestGitEnvironment:
    def test_branch_read(self, git_repo):
        st = read_state(git_repo, "main")
        assert st["branch"] == "ai-ops/WI-77"

    def test_behind_count_computed(self, git_repo):
        st = read_state(git_repo, "main")
        assert st["behind_count"] == 2

    def test_workitem_extracted(self, git_repo):
        st = read_state(git_repo, "main")
        assert st["workitems"] == ["WI-77"]

    def test_branch_age_measured(self, git_repo):
        st = read_state(git_repo, "main")
        assert st["branch_age_days"] is not None and st["branch_age_days"] < 1

    def test_no_upstream_unavailable(self, git_repo):
        st = read_state(git_repo, "main")
        assert st["base_behind_upstream"] is None

    def test_assess_allowed(self, git_repo):
        v = assess(git_repo, "main")
        assert v["allowed"]

    def test_summary_line_honest(self, git_repo):
        assert "отстаёт от 'main' на 2" in summary_line(git_repo, "main")

    def test_nonexistent_base_unavailable(self, git_repo):
        st2 = read_state(git_repo, "nonexistent-base")
        assert st2["behind_count"] is None

    def test_summary_nonexistent_base_honest(self, git_repo):
        assert "unavailable" in summary_line(git_repo, "nonexistent-base")


@pytest.mark.unit
class TestNonGitDirectory:
    def test_non_git_all_unavailable(self, tmp_path):
        st = read_state(tmp_path, "main")
        assert st["branch"] is None and st["behind_count"] is None

    def test_summary_non_git_honest(self, tmp_path):
        assert "unavailable" in summary_line(tmp_path)


@pytest.mark.unit
class TestPolicyFromConfig:
    def test_no_config_defaults(self, tmp_path):
        assert policy_from_config(tmp_path) == {}

    def test_config_read_from_yaml(self, tmp_path):
        (tmp_path / ".ai-ops.yaml").write_text(
            "engineering_operating_model:\n  branch:\n    enforce: block\n"
            "    base_drift_advisory: 5\n    protected_refs: [trunk]\n", encoding="utf-8")
        p = policy_from_config(tmp_path)
        assert p.get("enforce") == "block" and p.get("protected_refs") == ["trunk"]

    def test_malformed_config_does_not_crash(self, tmp_path):
        (tmp_path / ".ai-ops.yaml").write_text("{{ битый", encoding="utf-8")
        assert policy_from_config(tmp_path) == {}
