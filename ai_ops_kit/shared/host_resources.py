"""Один POSIX host-slot для cooperating local и self-hosted CI запусков.

Путь не зависит от checkout, git-common-dir или TMPDIR executor. Внешний runner
должен использовать тот же wrapper/path; native ps — наблюдение, не distributed lock.
"""
from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

DEFAULT_LOCK = Path("/tmp/ai-ops-kit-heavy.lock")
_HEAVY = re.compile(r"\bpytest\b|\bvitest\b|\bplaywright\s+test\b|check-full\.sh|"
                    r"(?:npm|pnpm|yarn)\s+(?:run\s+)?(?:build|test|typecheck)|(?:^|/)tsc(?:\s|$)")


class ResourceBlocked(RuntimeError):
    pass


class InheritedSlotLost(ResourceBlocked):
    pass


def heavy_processes():
    """Read-only ps; возвращает только PID и класс, без command/env/секретов."""
    result = subprocess.run(["ps", "-axo", "pid=,ppid=,command="], capture_output=True,
                            text=True, timeout=10, check=True)
    rows = [line.split(None, 2) for line in result.stdout.splitlines() if len(line.split(None, 2)) == 3]
    parents = {int(pid): int(ppid) for pid, ppid, _ in rows}
    ignored, current = set(), os.getpid()
    while current and current not in ignored:
        ignored.add(current)
        current = parents.get(current, 0)
    return [{"pid": int(pid), "class": "observed_heavy_command"}
            for pid, _, command in rows if int(pid) not in ignored and _HEAVY.search(command)
            and "-m ai_ops_kit.devtools.host_resource_cli" not in command]


def inherited_slot(path=None, *, environment=None):
    """Env alone никогда не разрешает skip lock: проверяем реальный fd/inode и flock."""
    try:
        import fcntl
        environment = os.environ if environment is None else environment
        path = Path(path or environment.get("AI_OPS_HOST_SLOT_PATH", DEFAULT_LOCK))
        fd = int(environment["AI_OPS_HOST_SLOT_FD"])
        opened, expected = os.fstat(fd), Path(path).lstat()
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (expected.st_dev, expected.st_ino):
            return None
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except (ImportError, KeyError, ValueError, OSError):
        return None


def subprocess_kwargs(environment=None):
    """Передаёт реальный lease через subprocess, не снимая родительский flock."""
    fd = inherited_slot(environment=environment)
    return {"pass_fds": (fd,)} if fd is not None else {}


@contextlib.contextmanager
def host_slot(owner, kind, *, path=DEFAULT_LOCK):
    """Nonblocking flock; чужой inode не удаляется. Crash закрывает fd штатно."""
    if not owner or kind not in {"local", "self_hosted_ci"} or not Path(path).is_absolute():
        raise ResourceBlocked("нужны owner, kind и общий absolute lock path")
    try:
        import fcntl
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    except (ImportError, OSError) as exc:
        raise ResourceBlocked("общий host-slot недоступен; права не менялись") from exc
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ResourceBlocked("host-slot не regular file")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ResourceBlocked("host-slot занят; действующая чужая блокировка сохранена") from exc
        os.ftruncate(fd, 0)
        os.write(fd, json.dumps({"owner": owner, "kind": kind, "pid": os.getpid()}).encode())
        os.fsync(fd)
        yield fd
    finally:
        os.close(fd)
