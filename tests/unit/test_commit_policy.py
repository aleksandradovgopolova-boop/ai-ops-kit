"""Гранулярные тесты commit_policy (мигрировано из test_commit_policy_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.engops.commit_policy import (
    Path,
    ZONE_KIT_CONFIG,
    ZONE_KIT_MANAGED,
    ZONE_PRODUCT,
    ZONE_RUNTIME,
    check_commit,
    policy_from_config,
    protected_from_config,
    summary_line,
    zone_of,
)


def _rules(v, key="violations"):
    return {x["rule"] for x in v[key]}


@pytest.mark.unit
class TestCheckCommitBasic:
    def test_normal_product_commit_allowed(self):
        good = check_commit(["src/app.py", "tests/test_app.py"],
                            "feat(app): считать ретраи по WI-12; доказано selftest", workitem="WI-12")
        assert good["allowed"] and not good["violations"]

    def test_zone_mixing_managed_product_blocked(self):
        mixed = check_commit([".ai/managed/tools/x.py", "src/app.py"],
                             "chore: WI-1 обновление + правка, selftest")
        assert not mixed["allowed"] and "zone_mixing" in _rules(mixed)

    def test_zone_mixing_kit_config_product_blocked(self):
        cfg_mixed = check_commit([".ai-ops.yaml", "src/app.py"],
                                 "chore: WI-1 конфиг и код, selftest")
        assert "zone_mixing" in _rules(cfg_mixed)

    def test_managed_plus_kit_config_allowed_pair(self):
        kit_only = check_commit([".ai/managed/tools/x.py", ".ai-ops.yaml"],
                                "chore(ai-ops): update kit 3.9.1 -> 3.18.0 по WI-9, doctor OK")
        assert kit_only["allowed"]

    def test_runtime_artifact_blocked(self):
        rt = check_commit([".ai/runtime/last-update-report.json"],
                          "chore: WI-2 отчёт прогона, selftest")
        assert "runtime_artifacts" in _rules(rt)

    def test_worktree_artifact_blocked(self):
        wt = check_commit([".ai/worktrees/task-x/file.py"],
                          "chore: WI-2 worktree, selftest")
        assert "runtime_artifacts" in _rules(wt)


@pytest.mark.unit
class TestForbiddenFiles:
    def test_env_forbidden(self):
        env = check_commit([".env"], "chore: WI-3 окружение, selftest")
        assert "forbidden_file" in _rules(env)

    def test_env_example_allowed(self):
        assert "forbidden_file" not in _rules(
            check_commit([".env.example"], "docs: WI-3 пример env, selftest"))

    def test_private_key_forbidden(self):
        assert "forbidden_file" in _rules(
            check_commit(["deploy/server.pem"], "chore: WI-3 ключ, selftest"))

    def test_id_rsa_forbidden(self):
        assert "forbidden_file" in _rules(
            check_commit([".ssh/id_rsa"], "chore: WI-3 ключ, selftest"))


@pytest.mark.unit
class TestSecretsInMessage:
    def test_literal_secret_blocked(self):
        sec = check_commit(["src/a.py"],
                           "fix(auth): WI-4 ключ sk-abcdefghijklmnopqrstuvwx попал в конфиг, selftest")
        assert "secret_in_message" in _rules(sec)

    def test_ghp_token_blocked(self):
        assert "secret_in_message" in _rules(check_commit(
            ["a.py"], "chore: WI-4 отозвать ghp_abcdefghijklmnopqrstuvwxyz012345, selftest"))

    def test_env_ref_not_secret(self):
        assert "secret_in_message" not in _rules(check_commit(
            ["a.py"], "chore(cfg): WI-4 брать ключ через env:ANTHROPIC_API_KEY, selftest"))


@pytest.mark.unit
class TestProtectedPaths:
    def test_protected_without_approval_blocked(self):
        prot = check_commit([".github/workflows/ci.yml"],
                            "ci: WI-5 поправить матрицу, selftest",
                            protected_paths=[".github/workflows/"])
        assert "protected_without_approval" in _rules(prot)

    def test_protected_with_approval_allowed(self):
        assert check_commit([".github/workflows/ci.yml"],
                            "ci: WI-5 поправить матрицу, selftest",
                            protected_paths=[".github/workflows/"],
                            approvals=["AR-1"])["allowed"]


@pytest.mark.unit
class TestAdvisories:
    def test_placeholder_message_blocked(self):
        ph = check_commit(["src/a.py"], "wip")
        assert "placeholder_message" in _rules(ph)

    def test_quick_no_advisories(self):
        assert check_commit(["src/a.py"], "почистить лог", task_type="QUICK")["advisories"] == []

    def test_no_workitem_evidence_advisories(self):
        soft = check_commit(["src/a.py"], "рефакторинг вынес хелпер наружу")
        assert soft["allowed"] and {"no_workitem", "no_evidence"} <= _rules(soft, "advisories")

    def test_enforce_block_escalates_advisories(self):
        assert not check_commit(["src/a.py"], "рефакторинг вынес хелпер наружу",
                                policy={"enforce": "block"})["allowed"]

    def test_large_commit_advisory(self):
        big = check_commit([f"src/m{i}.py" for i in range(50)],
                           "feat: WI-6 большая правка, selftest")
        assert "large_commit" in _rules(big, "advisories")

    def test_broad_scope_advisory(self):
        broad = check_commit(["a/x", "b/x", "c/x", "d/x", "e/x"],
                             "feat: WI-7 широкая правка, selftest")
        assert "broad_scope" in _rules(broad, "advisories")

    def test_root_files_not_counted_as_dirs(self):
        assert "broad_scope" not in _rules(check_commit(
            ["VERSION", "CHANGELOG.md", "README.md", "ROADMAP.md", "AGENTS.md", "FILE_INDEX.md",
             "tools/x.py", "rules/core/y.md"],
            "release(3.19.0): WI-7 срез 1, selftest"), "advisories")

    def test_dirs_counted_with_root_files(self):
        assert "broad_scope" in _rules(check_commit(
            ["VERSION", "a/x", "b/x", "c/x", "d/x", "e/x"],
            "feat: WI-7 правка, selftest"), "advisories")

    def test_empty_commit_blocked(self):
        assert "empty_commit" in _rules(check_commit([], "feat: WI-8, selftest"))


@pytest.mark.unit
class TestZones:
    def test_zones_deterministic(self):
        assert zone_of(".ai/managed/tools/x.py") == ZONE_KIT_MANAGED
        assert zone_of(".ai-ops.yaml") == ZONE_KIT_CONFIG
        assert zone_of(".ai/runtime/x.json") == ZONE_RUNTIME
        assert zone_of("src/app.ts") == ZONE_PRODUCT


@pytest.mark.unit
class TestPolicyConfig:
    def test_no_config_defaults(self, tmp_path):
        assert policy_from_config(tmp_path) == {}

    def test_config_read(self, tmp_path):
        (tmp_path / ".ai-ops.yaml").write_text(
            "engineering_operating_model:\n  commit:\n    enforce: block\n    max_files: 5\n"
            "protected_paths: [.github/workflows/]\n", encoding="utf-8")
        p = policy_from_config(tmp_path)
        assert p.get("enforce") == "block" and p.get("max_files") == 5

    def test_protected_paths_from_config(self, tmp_path):
        (tmp_path / ".ai-ops.yaml").write_text(
            "engineering_operating_model:\n  commit:\n    enforce: block\n    max_files: 5\n"
            "protected_paths: [.github/workflows/]\n", encoding="utf-8")
        assert protected_from_config(tmp_path) == [".github/workflows/"]

    def test_summary_reflects_config(self, tmp_path):
        (tmp_path / ".ai-ops.yaml").write_text(
            "engineering_operating_model:\n  commit:\n    enforce: block\n    max_files: 5\n"
            "protected_paths: [.github/workflows/]\n", encoding="utf-8")
        assert "enforce=block" in summary_line(tmp_path)

    def test_malformed_config_does_not_crash(self, tmp_path):
        (tmp_path / ".ai-ops.yaml").write_text("{{ битый yaml", encoding="utf-8")
        assert policy_from_config(tmp_path) == {}
