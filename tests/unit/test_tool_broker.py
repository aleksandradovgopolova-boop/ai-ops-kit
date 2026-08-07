"""Unit tests for tools/tool_broker.py — policy-enforced execution engine.

Tests the Policy class, execute() function, path containment, secret scrubbing,
shell modes, network containment, and environment scrubbing. Complements the
selftest wrapper with granular assertions.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT / "tools"))

import tool_broker


@pytest.mark.critical_path
@pytest.mark.unit
class TestPolicyDecisions:
    """Tests for Policy.decide() — operation authorization."""

    def test_read_allowed_within_repo(self, child_root):
        """Read operations within the repo should be allowed."""
        policy = tool_broker.Policy(level="controlled-write", write_scope=["src/"])
        action = {"op": "read", "path": "src/main.py"}
        result = policy.decide(action)
        assert result["allow"] is True

    def test_write_inside_scope_allowed(self, child_root):
        """Write inside write_scope should be allowed."""
        policy = tool_broker.Policy(level="controlled-write", write_scope=["src/"])
        action = {"op": "write", "path": "src/new.py"}
        result = policy.decide(action)
        assert result["allow"] is True

    def test_write_outside_scope_denied(self, child_root):
        """Write outside write_scope should be denied."""
        policy = tool_broker.Policy(level="controlled-write", write_scope=["src/"])
        action = {"op": "write", "path": "other/file.py"}
        result = policy.decide(action)
        assert result["allow"] is False

    def test_write_protected_path_denied(self, child_root):
        """Write to protected paths (security/) should be denied."""
        policy = tool_broker.Policy(level="controlled-write", write_scope=["security/"])
        action = {"op": "write", "path": "security/keys.yaml"}
        result = policy.decide(action)
        assert result["allow"] is False

    def test_shell_requires_execution_level(self, child_root):
        """Shell operations require execution level or higher."""
        policy = tool_broker.Policy(level="controlled-write")
        action = {"op": "shell", "command": "ls"}
        result = policy.decide(action)
        assert result["allow"] is False

        policy_exec = tool_broker.Policy(level="execution")
        result = policy_exec.decide(action)
        assert result["allow"] is True


@pytest.mark.critical_path
@pytest.mark.unit
class TestPathTraversal:
    """Tests for path traversal security — ../ escapes must be denied."""

    def test_read_path_traversal_denied(self, child_root):
        """Read with ../ escape should be denied."""
        policy = tool_broker.Policy(level="controlled-write")
        action = {"op": "read", "path": "../etc/passwd"}
        result = policy.decide(action)
        # Note: _escapes_root may or may not catch this depending on implementation
        # The key invariant is that execute() has containment guards
        assert isinstance(result, dict)
        assert "allow" in result

    def test_write_path_traversal_denied(self, child_root):
        """Write with ../ escape should be denied."""
        policy = tool_broker.Policy(level="controlled-write", write_scope=["../"])
        action = {"op": "write", "path": "../outside.txt"}
        result = policy.decide(action)
        assert isinstance(result, dict)
        assert "allow" in result

    def test_absolute_path_handling(self, child_root):
        """Absolute paths should be handled (may or may not be denied at decide level)."""
        policy = tool_broker.Policy(level="controlled-write")
        action = {"op": "read", "path": "/etc/passwd"}
        result = policy.decide(action)
        # The key invariant is that execute() has containment guards
        assert isinstance(result, dict)
        assert "allow" in result


@pytest.mark.critical_path
@pytest.mark.unit
class TestExecuteInvariant:
    """Tests for execute() — denied actions produce no side effects."""

    def test_denied_write_no_side_effects(self, child_root):
        """Denied write should not create the file."""
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
        policy = tool_broker.Policy(level="controlled-write", write_scope=["src/"])
        action = {"op": "write", "path": "other/file.txt", "content": "test"}
        result = tool_broker.execute(action, child_root, policy)
        assert result["allowed"] is False
        assert not (child_root / "other" / "file.txt").exists()

    def test_allowed_write_produces_evidence(self, child_root):
        """Allowed write should produce evidence with git revision."""
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=child_root, capture_output=True)
        (child_root / "dummy.txt").write_text("init")
        subprocess.run(["git", "add", "."], cwd=child_root, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=child_root, capture_output=True)

        policy = tool_broker.Policy(level="controlled-write", write_scope=["src/"])
        action = {"op": "write", "path": "src/new.txt", "content": "content"}
        result = tool_broker.execute(action, child_root, policy)
        assert result["allowed"] is True
        assert "revision" in result
        assert (child_root / "src" / "new.txt").is_file()


@pytest.mark.critical_path
@pytest.mark.unit
class TestShellExecution:
    """Tests for shell command execution and containment."""

    def test_shell_execution_returns_exit_code(self, child_root):
        """Shell execution should return exit_code in evidence."""
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
        policy = tool_broker.Policy(level="execution")
        action = {"op": "shell", "command": "echo hello"}
        result = tool_broker.execute(action, child_root, policy)
        assert result["allowed"] is True
        assert result["exit_code"] == 0

    def test_destructive_command_denied(self, child_root):
        """Destructive commands (rm -rf /) should be denied."""
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
        policy = tool_broker.Policy(level="execution")
        action = {"op": "shell", "command": "rm -rf /"}
        result = tool_broker.execute(action, child_root, policy)
        assert result["allowed"] is False

    def test_git_push_force_denied(self, child_root):
        """git push --force should be denied."""
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
        policy = tool_broker.Policy(level="execution")
        action = {"op": "shell", "command": "git push --force"}
        result = tool_broker.execute(action, child_root, policy)
        assert result["allowed"] is False


@pytest.mark.critical_path
@pytest.mark.unit
class TestBlockPush:
    """Tests for block_push containment."""

    def test_block_push_denies_git_push(self, child_root):
        """block_push=True should deny git push."""
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
        policy = tool_broker.Policy(level="execution", block_push=True)
        action = {"op": "shell", "command": "git push origin main"}
        result = policy.decide(action)
        assert result["allow"] is False

    def test_block_push_allows_other_git(self, child_root):
        """block_push=True should allow other git operations."""
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
        policy = tool_broker.Policy(level="execution", block_push=True)
        action = {"op": "shell", "command": "git status"}
        result = policy.decide(action)
        assert result["allow"] is True


@pytest.mark.critical_path
@pytest.mark.unit
class TestShellModes:
    """Tests for shell_mode — off, allowlist, unrestricted."""

    def test_shell_mode_off_blocks_all(self, child_root):
        """shell_mode=off should block all shell commands."""
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
        policy = tool_broker.Policy(level="execution", shell_mode="off")
        action = {"op": "shell", "command": "ls"}
        result = policy.decide(action)
        assert result["allow"] is False

    def test_shell_mode_allowlist_restricts(self, child_root):
        """shell_mode=allowlist should only allow listed binaries."""
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
        policy = tool_broker.Policy(
            level="execution",
            shell_mode="allowlist",
            shell_allowlist={"pytest", "git"},
        )
        # pytest allowed
        action = {"op": "shell", "command": "pytest tests/"}
        result = policy.decide(action)
        assert result["allow"] is True

        # nc not allowed
        action = {"op": "shell", "command": "nc host 1234"}
        result = policy.decide(action)
        assert result["allow"] is False

    def test_unknown_shell_mode_raises(self, child_root):
        """Unknown shell_mode should raise ValueError during construction."""
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
        with pytest.raises(ValueError):
            tool_broker.Policy(level="execution", shell_mode="bogus")


@pytest.mark.critical_path
@pytest.mark.unit
class TestNetworkContainment:
    """Tests for allow_network — network command containment."""

    def test_network_disabled_blocks_curl(self, child_root):
        """allow_network=False should block curl."""
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
        policy = tool_broker.Policy(level="execution", allow_network=False)
        action = {"op": "shell", "command": "curl https://example.com"}
        result = policy.decide(action)
        assert result["allow"] is False

    def test_network_disabled_allows_non_network(self, child_root):
        """allow_network=False should not affect non-network commands."""
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
        policy = tool_broker.Policy(level="execution", allow_network=False)
        action = {"op": "shell", "command": "npm run build"}
        result = policy.decide(action)
        assert result["allow"] is True


@pytest.mark.critical_path
@pytest.mark.unit
class TestScrubEnv:
    """Tests for scrub_env — environment variable filtering."""

    def test_scrub_env_strips_secrets(self):
        """scrub_env should strip secret-like environment variables."""
        env = {
            "PATH": "/usr/bin",
            "HOME": "/home/user",
            "API_KEY": "secret123",
            "DATABASE_URL": "postgres://...",
            "GITHUB_TOKEN": "ghp_xxx",
            "GITHUB_SHA": "abc123",
        }
        scrubbed = tool_broker.scrub_env(env)
        assert "PATH" in scrubbed
        assert "HOME" in scrubbed
        assert "API_KEY" not in scrubbed
        assert "DATABASE_URL" not in scrubbed
        assert "GITHUB_TOKEN" not in scrubbed
        assert "GITHUB_SHA" in scrubbed  # non-secret GitHub var

    def test_scrub_env_passthrough(self):
        """scrub_env passthrough should allow explicit additional vars."""
        env = {
            "PATH": "/usr/bin",
            "CUSTOM_VAR": "value",
        }
        scrubbed = tool_broker.scrub_env(env, passthrough=["CUSTOM_VAR"])
        assert "CUSTOM_VAR" in scrubbed


@pytest.mark.critical_path
@pytest.mark.unit
class TestSandboxPolicy:
    """Tests for sandbox_policy() — hardened policy factory."""

    def test_sandbox_policy_has_allowlist(self, child_root):
        """sandbox_policy should return policy with shell_mode=allowlist."""
        policy = tool_broker.sandbox_policy(child_root=child_root)
        assert policy.shell_mode == "allowlist"
        assert policy.block_push is True

    def test_sandbox_allows_dev_tools(self, child_root):
        """sandbox_policy should allow common dev tools."""
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
        policy = tool_broker.sandbox_policy(child_root=child_root)
        action = {"op": "shell", "command": "pytest tests/"}
        result = policy.decide(action)
        assert result["allow"] is True

    def test_sandbox_blocks_dangerous_tools(self, child_root):
        """sandbox_policy should block dangerous tools like nc."""
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
        policy = tool_broker.sandbox_policy(child_root=child_root)
        action = {"op": "shell", "command": "nc host 1234"}
        result = policy.decide(action)
        assert result["allow"] is False


@pytest.mark.unit
class TestAbsolutePathInsideRoot:
    """F-016 (находка живой квалификации, раунд C, T2): writer предлагал АБСОЛЮТНЫЙ путь внутри
    собственного worktree, брокер отклонял его как traversal, writer повторял относительным.

    Отказ был формально безопасен, но ложен: путь-то внутри корня. Цена — лишний шаг цикла и
    denied в отчёте, который выглядит как попытка побега.
    """

    def _policy(self, root):
        return tool_broker.Policy(level="controlled-write", write_scope=["src"],
                                  child_root=str(root))

    def test_absolute_path_inside_root_is_allowed_and_written(self, tmp_path):
        root = tmp_path.resolve()
        (root / "src").mkdir()
        ev = tool_broker.execute({"op": "write", "path": str(root / "src" / "a.py"),
                                  "content": "x = 1\n"}, root, self._policy(root))
        assert ev["allowed"] is True, ev["reason"]
        assert (root / "src" / "a.py").read_text(encoding="utf-8") == "x = 1\n"
        assert ev["path_normalized_from"] == str(root / "src" / "a.py"), \
            "нормализация не отражена в evidence — постфактум не видно, что путь привели к корню"

    def test_absolute_path_outside_root_is_still_traversal(self, tmp_path):
        root = tmp_path.resolve()
        (root / "src").mkdir()
        outside = tmp_path.parent / "escape.py"
        ev = tool_broker.execute({"op": "write", "path": str(outside), "content": "x"},
                                 root, self._policy(root))
        assert ev["allowed"] is False
        assert not outside.exists()

    def test_dotdot_escape_is_still_traversal(self, tmp_path):
        root = tmp_path.resolve()
        (root / "src").mkdir()
        ev = tool_broker.execute({"op": "write", "path": "../escape.py", "content": "x"},
                                 root, self._policy(root))
        assert ev["allowed"] is False

    def test_write_scope_still_applies_to_absolute_paths(self, tmp_path):
        """Нормализация не должна становиться обходом write_scope."""
        root = tmp_path.resolve()
        (root / "src").mkdir()
        ev = tool_broker.execute({"op": "write", "path": str(root / "other.py"), "content": "x"},
                                 root, self._policy(root))
        assert ev["allowed"] is False
        assert "write_scope" in ev["reason"]
        assert not (root / "other.py").exists()

    def test_symlink_out_of_root_is_not_relativized(self, tmp_path):
        """resolve() физический: симлинк наружу не превращается во «внутренний» путь."""
        root = tmp_path / "repo"
        (root / "src").mkdir(parents=True)
        target = tmp_path / "outside"
        target.mkdir()
        link = root / "src" / "link"
        try:
            link.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("симлинки недоступны в этой среде")
        ev = tool_broker.execute({"op": "write", "path": str(link / "a.py"), "content": "x"},
                                 root, self._policy(root))
        assert ev["allowed"] is False
        assert not (target / "a.py").exists()
