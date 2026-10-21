"""Общий host-slot Kit: local и self_hosted_ci используют один wrapper/path.

Не меняет CI/доступы продуктов. Не оборачивает автоматически внешний runner.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import re
import stat
from collections.abc import Iterator, Mapping
import os
from pathlib import Path
import subprocess
import time

DEFAULT_LOCK = Path("/tmp/ai-ops-kit-heavy.lock")
_HEAVY = re.compile(r"\bpytest\b|\bvitest\b|\bplaywright\s+test\b|check-full\.sh|"
                    r"(?:npm|pnpm|yarn)\s+(?:run\s+)?(?:build|test|typecheck)|(?:^|/)tsc(?:\s|$)")


class ResourceBlocked(RuntimeError):
    pass


class InheritedSlotLost(ResourceBlocked):
    pass


def heavy_processes() -> list[dict[str, int | str]]:
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


def inherited_slot(path: str | Path | None = None, *,
                   environment: Mapping[str, str] | None = None) -> int | None:
    """Env alone никогда не разрешает skip lock: проверяем реальный fd/inode и flock."""
    try:
        import fcntl
        environment = os.environ if environment is None else environment
        path = Path(path or environment.get("AI_OPS_HOST_SLOT_PATH", str(DEFAULT_LOCK)))
        fd = int(environment["AI_OPS_HOST_SLOT_FD"])
        opened, expected = os.fstat(fd), Path(path).lstat()
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (expected.st_dev, expected.st_ino):
            return None
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except (ImportError, KeyError, ValueError, OSError):
        return None


def subprocess_kwargs(environment: Mapping[str, str] | None = None) -> dict[str, tuple[int, ...]]:
    """Передаёт реальный lease через subprocess, не снимая родительский flock."""
    fd = inherited_slot(environment=environment)
    return {"pass_fds": (fd,)} if fd is not None else {}


@contextlib.contextmanager
def host_slot(owner: str, kind: str, *, path: str | Path = DEFAULT_LOCK) -> Iterator[int]:
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



def execute(command, owner, kind, *, path=DEFAULT_LOCK, probe=heavy_processes):
    inherited = inherited_slot()
    if "AI_OPS_HOST_SLOT_FD" in os.environ and inherited is None:
        raise InheritedSlotLost("унаследованный fd потерян; нужен pass_fds, slot не освобождён")
    if inherited is not None and inherited_slot(path) == inherited:
        return subprocess.call(command, pass_fds=(inherited,))
    with host_slot(owner, kind, path=path) as fd:
        if probe():
            raise ResourceBlocked("ps наблюдает другой тяжёлый процесс; он не остановлен")
        # Этот fd сохраняет один и тот же flock через Bash/Python child; env без fd не годится.
        return subprocess.call(command, env={**os.environ, "AI_OPS_HOST_SLOT_FD": str(fd),
                                             "AI_OPS_HOST_SLOT_PATH": str(path)}, pass_fds=(fd,))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", default="kit-check")
    parser.add_argument("--kind", choices=("local", "self_hosted_ci"), default="local")
    parser.add_argument("--lock-path", type=Path)
    parser.add_argument("--verify-inherited", action="store_true")
    parser.add_argument("--wait-seconds", type=float, default=0)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.verify_inherited:
        return 0 if inherited_slot(args.lock_path) is not None else 2
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("нужна команда после --")
    deadline = time.monotonic() + max(0, args.wait_seconds)
    while True:
        try:
            return execute(command, args.owner, args.kind, path=args.lock_path or DEFAULT_LOCK)
        except InheritedSlotLost as exc:
            print(f"BLOCKED host-slot: {exc}", flush=True)
            return 2  # Never wait on the parent lease after a subprocess closed its fd.
        except (OSError, subprocess.SubprocessError, ResourceBlocked) as exc:
            print(f"BLOCKED host-slot: {exc}", flush=True)
            if time.monotonic() >= deadline:
                return 2
            time.sleep(min(5, max(0, deadline - time.monotonic())))


if __name__ == "__main__":
    raise SystemExit(main())
