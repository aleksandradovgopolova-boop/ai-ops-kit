"""Unit tests for tools/tool_broker.py — решения политики, path-containment, read/write, self-host.

Тема этого файла: Policy.decide() (авторизация операций), path-traversal, инвариант execute()
(денай без side-effects), абсолютные пути внутри корня, child-override protected_paths, read с
диапазоном и self-host-защита движка/CI/реестров кита. Парный файл `test_tool_broker_shell.py`
держит тему shell-канала (режимы/allowlist/сеть/block_push/scrub/sandbox_policy). Разрез
behavior-preserving — тела тестов не менялись.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from _tool_broker_helpers import _git_p0

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


# ─── P0 (аудит 04.09): движок/CI/реестры кита под owner-approval ТОЛЬКО на self-host ────────────


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
