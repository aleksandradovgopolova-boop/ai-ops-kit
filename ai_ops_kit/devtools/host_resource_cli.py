"""Общий host-slot Kit: local и self_hosted_ci используют один wrapper/path.

Не меняет CI/доступы продуктов. Не оборачивает автоматически внешний runner.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import time

from ai_ops_kit.shared import host_resources as resources


def execute(command, owner, kind, *, path=resources.DEFAULT_LOCK, probe=resources.heavy_processes):
    inherited = resources.inherited_slot()
    if "AI_OPS_HOST_SLOT_FD" in os.environ and inherited is None:
        raise resources.InheritedSlotLost("унаследованный fd потерян; нужен pass_fds, slot не освобождён")
    if inherited is not None and resources.inherited_slot(path) == inherited:
        return subprocess.call(command, pass_fds=(inherited,))
    with resources.host_slot(owner, kind, path=path) as fd:
        if probe():
            raise resources.ResourceBlocked("ps наблюдает другой тяжёлый процесс; он не остановлен")
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
        return 0 if resources.inherited_slot(args.lock_path) is not None else 2
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("нужна команда после --")
    deadline = time.monotonic() + max(0, args.wait_seconds)
    while True:
        try:
            return execute(command, args.owner, args.kind, path=args.lock_path or resources.DEFAULT_LOCK)
        except resources.InheritedSlotLost as exc:
            print(f"BLOCKED host-slot: {exc}", flush=True)
            return 2  # Never wait on the parent lease after a subprocess closed its fd.
        except (OSError, subprocess.SubprocessError, resources.ResourceBlocked) as exc:
            print(f"BLOCKED host-slot: {exc}", flush=True)
            if time.monotonic() >= deadline:
                return 2
            time.sleep(min(5, max(0, deadline - time.monotonic())))


if __name__ == "__main__":
    raise SystemExit(main())
