"""Гранулярные тесты gitio (мигрировано из test_gitio_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ai_ops_kit.shared.gitio import git


@pytest.mark.unit
class TestGit:
    def test_not_a_repo(self, tmp_path):
        rc, out, err = git(tmp_path, "rev-parse", "--is-inside-work-tree")
        assert rc != 0 and isinstance(out, str) and isinstance(err, str)

    def test_init_and_commit(self, tmp_path):
        for a in (("init", "-q"), ("config", "user.email", "t@t"), ("config", "user.name", "t")):
            git(tmp_path, *a)
        (tmp_path / "f").write_text("x", encoding="utf-8")
        git(tmp_path, "add", "-A")
        git(tmp_path, "commit", "-q", "-m", "i")
        rc, out, _ = git(tmp_path, "rev-parse", "--abbrev-ref", "HEAD")
        assert rc == 0 and bool(out)

    def test_timeout_parameter(self, tmp_path):
        for a in (("init", "-q"), ("config", "user.email", "t@t"), ("config", "user.name", "t")):
            git(tmp_path, *a)
        (tmp_path / "f").write_text("x", encoding="utf-8")
        git(tmp_path, "add", "-A")
        git(tmp_path, "commit", "-q", "-m", "i")
        rc, _, _ = git(tmp_path, "status", "--porcelain", timeout=30)
        assert rc == 0


# ── #1575: EPERM от killpg на macOS ─────────────────────────────────────────────────────────────
#
# На macOS сигнал группе, в которой остался только неубранный (zombie) лидер, даёт EPERM, а не
# ESRCH. Git, завершившийся ровно между таймаутом и killpg, ронял `PermissionError` вместо
# `TimeoutExpired`. Тесты детерминированы: «macOS» изображает подменённый killpg.

def _spawn_python(monkeypatch, code):
    import sys

    from ai_ops_kit.shared import gitio
    actual = gitio.subprocess.Popen

    def spawn(command, **kwargs):
        return actual([sys.executable, "-c", code], **kwargs)
    monkeypatch.setattr(gitio.subprocess, "Popen", spawn)


def _macos_killpg_after_exit(monkeypatch):
    """killpg, который сам убивает лидера, ждёт, пока тот станет zombie, и отвечает EPERM."""
    import os
    import signal
    import time

    from ai_ops_kit.shared import gitio
    real_kill = os.kill

    def killpg(pid, sig):
        try:
            real_kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        time.sleep(0.2)                      # лидер завершён, но ещё не убран
        raise PermissionError(1, "Operation not permitted")
    monkeypatch.setattr(gitio.os, "killpg", killpg)


@pytest.mark.unit
class TestRawGroupKillpgEperm:
    def test_timeout_survives_eperm_from_exited_group(self, tmp_path, monkeypatch):
        import subprocess

        from ai_ops_kit.shared import gitio
        _spawn_python(monkeypatch, "import time; time.sleep(30)")
        _macos_killpg_after_exit(monkeypatch)
        with pytest.raises(subprocess.TimeoutExpired):
            gitio.raw_group(["status"], cwd=tmp_path, timeout=0.3)

    def test_completed_call_survives_eperm_from_exited_group(self, tmp_path, monkeypatch):
        from ai_ops_kit.shared import gitio
        _spawn_python(monkeypatch, "print('ok')")
        _macos_killpg_after_exit(monkeypatch)
        result = gitio.raw_group(["status"], cwd=tmp_path, timeout=10)
        assert result.returncode == 0 and result.stdout == "ok\n"

    def test_eperm_on_live_group_is_not_swallowed(self, tmp_path, monkeypatch):
        """EPERM при ЖИВОМ ребёнке — настоящий отказ, его прятать нельзя."""
        from ai_ops_kit.shared import gitio
        _spawn_python(monkeypatch, "import time; time.sleep(3)")

        def killpg(pid, sig):
            raise PermissionError(1, "Operation not permitted")
        monkeypatch.setattr(gitio.os, "killpg", killpg)
        with pytest.raises(PermissionError):
            gitio.raw_group(["status"], cwd=tmp_path, timeout=0.2)

    def test_timeout_survives_eperm_while_group_is_exiting(self, tmp_path, monkeypatch):
        """Замер macOS: EPERM приходит, когда poll() ещё None, а через миг ребёнок уже вышел."""
        import os
        import signal
        import subprocess
        import threading

        from ai_ops_kit.shared import gitio
        _spawn_python(monkeypatch, "import time; time.sleep(30)")
        real_kill = os.kill

        def killpg(pid, sig):
            threading.Timer(0.1, real_kill, (pid, signal.SIGKILL)).start()   # выйдет чуть позже
            raise PermissionError(1, "Operation not permitted")
        monkeypatch.setattr(gitio.os, "killpg", killpg)
        with pytest.raises(subprocess.TimeoutExpired):
            gitio.raw_group(["status"], cwd=tmp_path, timeout=0.3)
