#!/usr/bin/env python3
"""Prepare an isolated dependency environment, then delegate to existing setup.

Only stdlib is imported. Experimental macOS/Linux entry from a reviewed checkout;
does not download the kit, change system Python or execute models.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import venv


SOURCE = Path(__file__).resolve().parents[1]
MESSAGES = {
    "prepare": {"ru": "Готовлю отдельное окружение", "en": "Preparing an isolated environment"},
    "install": {"ru": "Ставлю существующую зависимость requirements.txt",
                "en": "Installing the existing requirements.txt dependency"},
    "setup": {"ru": "Запускаю существующий setup; его сообщения пока на русском",
              "en": "Running existing setup; its messages are currently in Russian"},
    "demo": {"ru": "Запускаю существующий offline-пример без модели",
             "en": "Running the existing offline example without a model"},
    "activate": {"ru": "Активируйте для команд в этой терминальной сессии",
                 "en": "Activate for commands in this terminal session"},
    "failed": {"ru": "Подготовка/установка не завершена", "en": "Preparation/installation did not complete"},
}


def say(key, language, detail=""):
    print(MESSAGES[key][language] + (": " + str(detail) if detail else ""), flush=True)


def command(argv, **kwargs):
    kwargs.setdefault("timeout", 60)
    kwargs.setdefault("check", True)
    return subprocess.run(argv, **kwargs)


@contextmanager
def environment_lock(directory):
    # Kernel lock is released on crash; no age-based takeover or stale lock removal.
    import fcntl
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / "prepare.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Environment preparation already running / Окружение уже готовится") from None
        yield
    finally:
        os.close(descriptor)


def requirement(source):
    entries = [line.split("#", 1)[0].strip() for line in (source / "requirements.txt").read_text().splitlines()]
    entries = [line for line in entries if line]
    if len(entries) != 1 or not re.fullmatch(r"pyyaml>=\d+\.\d+\.\d+", entries[0], re.I):
        raise RuntimeError("Unsupported requirements; review bootstrap / Изменились зависимости: проверьте bootstrap")
    return entries[0].split(">=", 1)[1]


def dependency_ready(python, minimum):
    probe = ("import importlib.metadata as m, yaml; "
             "v=m.version('pyyaml').split('.'); "
             "assert tuple(map(int,v[:3])) >= tuple(map(int,__import__('sys').argv[1].split('.'))) ")
    result = subprocess.run([str(python), "-I", "-c", probe, minimum],
                            capture_output=True, text=True, timeout=15)
    return result.returncode == 0


def prepare_environment(source, *, wheelhouse=None, language="ru"):
    minimum = requirement(source)
    directory = source / ".ai/runtime/bootstrap/venv"
    marker = directory / "ai-ops-bootstrap.json"
    if directory.is_symlink() or marker.is_symlink():
        raise RuntimeError("Environment/marker is a symlink / Окружение или маркер — симлинк")
    if directory.exists():
        if not marker.is_file() or json.loads(marker.read_text()).get("kind") != "ai-ops-bootstrap-env":
            raise RuntimeError("Existing environment is not owned by bootstrap / Каталог окружения не принадлежит bootstrap")
    else:
        directory.mkdir()
        marker.write_text(json.dumps({"kind": "ai-ops-bootstrap-env", "schema_version": 1}) + "\n")
    say("prepare", language, directory)
    if not (directory / "pyvenv.cfg").is_file():
        venv.EnvBuilder(with_pip=True, system_site_packages=False).create(directory)
    python = directory / "bin/python3"
    # Check isolation before pip can write: never install into a global/user site.
    command([str(python), "-I", "-c",
             "import sys,pathlib; assert sys.prefix != sys.base_prefix; "
             "assert pathlib.Path(sys.prefix).resolve()==pathlib.Path(sys.argv[1]).resolve(); "
             "assert not any(p in sys.path for p in __import__('site').getsitepackages([sys.base_prefix]))",
             str(directory)], capture_output=True, text=True)
    if not dependency_ready(python, minimum):
        say("install", language, wheelhouse if wheelhouse is not None else "PyPI")
        argv = [str(python), "-I", "-m", "pip", "--isolated", "install",
                "--disable-pip-version-check", "--only-binary=:all:"]
        if wheelhouse is not None:
            argv.extend(["--no-index", "--find-links", str(wheelhouse)])
        command([*argv, "-r", str(source / "requirements.txt")])
        if not dependency_ready(python, minimum):
            raise RuntimeError("Dependency check failed / Проверка зависимости не прошла")
    return python


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path, nargs="?", help="Existing Git project / Существующий Git-проект")
    parser.add_argument("--demo", action="store_true", help="Try the existing isolated offline sample / Попробовать на временном sample")
    parser.add_argument("--language", choices=("ru", "en"), default="ru", help="Bootstrap messages only / Язык сообщений подготовки")
    parser.add_argument("--wheelhouse", type=Path, help="Optional trusted local wheel cache; no package index / Доверенный локальный кеш wheel, без индекса")
    args = parser.parse_args(argv)
    if args.demo == (args.project is not None):
        parser.error("Choose project OR --demo / Укажите проект ИЛИ --demo")
    try:
        if sys.version_info < (3, 12) or sys.platform not in ("darwin", "linux"):
            raise RuntimeError("Requires Python 3.12+ on macOS/Linux / Нужен Python 3.12+ на macOS/Linux")
        command(["git", "--version"], capture_output=True, text=True)
        if args.demo:
            entry = SOURCE / "examples/first-session/demo.py"
            if not entry.is_file():
                raise RuntimeError("Sample entry missing / Нет точки входа примера")
            extra = []
        else:
            project = args.project.resolve()
            if not project.is_dir():
                raise RuntimeError("Project directory missing / Нет каталога проекта")
            inside = command(["git", "-C", str(project), "rev-parse", "--is-inside-work-tree"],
                             capture_output=True, text=True)
            if inside.stdout.strip() != "true":
                raise RuntimeError("Target is not a Git worktree / Проект не является рабочей копией Git")
            command(["git", "-C", str(project), "rev-parse", "--verify", "HEAD"], capture_output=True, text=True)
            entry, extra = SOURCE / "installer/ai_ops.py", ["setup", str(project)]
        if args.wheelhouse is not None and not args.wheelhouse.is_dir():
            raise RuntimeError("Wheel cache directory missing / Нет каталога кеша wheel")
        for part in (SOURCE / ".ai", SOURCE / ".ai/runtime", SOURCE / ".ai/runtime/bootstrap"):
            if part.is_symlink():
                raise RuntimeError("Environment parent is a symlink / Родитель окружения — симлинк")
        with environment_lock(SOURCE / ".ai/runtime/bootstrap"):
            python = prepare_environment(SOURCE, wheelhouse=args.wheelhouse, language=args.language)
            say("demo" if args.demo else "setup", args.language)
            env = dict(os.environ, AI_OPS_PYTHON=str(python), PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1")
            for key in ("PYTHONPATH", "PYTHONHOME"):
                env.pop(key, None)
            # setup keeps its own 150s budget and logs; this wrapper adds no workflow.
            result = command([str(python), str(entry), *extra],
                             env=env, timeout=180, check=False)
            if result.returncode != 0:
                say("failed", args.language, f"exit {result.returncode}")
                return result.returncode
        say("activate", args.language, "source " + shlex.quote(str(python.parent / "activate")))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        say("failed", args.language, error)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
