#!/usr/bin/env python3
"""Reproduce local installation and repository understanding without model calls.

Run from any directory. Retains its isolated sample and actual command outputs in
a new temporary directory. Never installs into a supplied/user repository.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    if sys.version_info < (3, 12):
        raise SystemExit("Python 3.12+ required / Требуется Python 3.12+")
    try:
        import yaml  # noqa: F401 — dependency preflight before creating a repository
    except ImportError:
        raise SystemExit("Install requirements.txt in a venv first / Сначала установите requirements.txt в venv") from None
    source = Path(__file__).resolve().parents[2]
    scratch = Path(tempfile.mkdtemp(prefix="ai-ops-first-session-"))
    project = scratch / "greeting-sample"
    shutil.copytree(Path(__file__).parent / "sample", project,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    logs = scratch / "evidence"
    logs.mkdir()
    # An allowlist avoids inheriting credentials, provider settings, global Git
    # hooks/signing, HOME and CODEX_HOME from the person running the example.
    env = {
        "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", os.defpath),
        "HOME": str(scratch / "home"),
        "CODEX_HOME": str(scratch / "codex-home"),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    Path(env["HOME"]).mkdir()
    Path(env["CODEX_HOME"]).mkdir()
    print(f"Sample and actual outputs / Пример и реальный вывод: {scratch}", flush=True)
    commands = []

    def run(label, *argv):
        result = subprocess.run(argv, cwd=project, env=env, capture_output=True,
                                text=True, encoding="utf-8", timeout=120)
        commands.append({"step": label, "argv": list(argv), "returncode": result.returncode})
        (logs / f"{label}.stdout.txt").write_text(result.stdout, encoding="utf-8")
        (logs / f"{label}.stderr.txt").write_text(result.stderr, encoding="utf-8")
        (logs / "commands.json").write_text(json.dumps(commands, indent=2) + "\n", encoding="utf-8")
        if result.returncode:
            raise RuntimeError(f"{label}: exit {result.returncode}; see / см. {logs}")
        return result.stdout

    run("01-git-init", "git", "init", "-q", "-b", "main")
    run("02-git-add", "git", "add", "README.md", "pyproject.toml", "greeting.py", "tests/test_greeting.py")
    run("03-git-commit", "git", "-c", "user.name=AI Ops Sample", "-c",
        "user.email=sample@example.invalid", "commit", "-qm", "chore: seed synthetic sample")
    original = {p: (project / p).read_bytes() for p in ("README.md", "pyproject.toml", "greeting.py", "tests/test_greeting.py")}
    run("04-sample-test", sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v")
    run("05-install", sys.executable, str(source / "installer/ai_ops.py"), "init", str(project))
    cli = str(project / "ai-ops")
    run("06-doctor", cli, "doctor")
    run("07-onboard", cli, "onboard")
    model = json.loads(run("08-model", cli, "model", "--json"))
    if model.get("kind") != "repository-understanding" or not model.get("evidence", {}).get("tree_readable"):
        raise RuntimeError("Missing repository understanding / Не получен разбор репозитория")
    if "python" not in (model.get("reconstructed", {}).get("languages", {}).get("value") or []):
        raise RuntimeError("Python not detected / Python не определён")
    checksums = json.loads((project / ".ai/managed/.checksums.json").read_text())
    # Integrity is checked by doctor; verify the key delivered paths independently.
    for relative in (".ai-ops.yaml", "ai-ops", ".ai/managed/commands/task/ai-run.md", ".ai/repository-profile.yaml"):
        if not (project / relative).is_file():
            raise RuntimeError(f"Missing delivered file / Нет файла: {relative}")
    for relative, content in original.items():
        if (project / relative).read_bytes() != content:
            raise RuntimeError(f"Sample source changed / Изменён исходник: {relative}")
    run("09-sample-test-after", sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v")
    questions = model.get("ask", {}).get("questions", [])
    summary = {
        "scope": "offline installation and repository understanding; no task execution",
        "kit_version": (source / "VERSION").read_text().strip(),
        "sample_source_sha256": {p: hashlib.sha256(b).hexdigest() for p, b in original.items()},
        "commands_passed": len(commands),
        "checksums_document_present": isinstance(checksums, dict),
        "languages": model.get("reconstructed", {}).get("languages"),
        "owner_questions": len(questions),
        "task_executed": False,
    }
    (logs / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"PASS: {len(commands)} local commands; sample test passed before/after; source unchanged.")
    print(f"Installation checked; project context saved; owner questions: {len(questions)}.")
    print("Проверено: установка и контекст проекта. Исходники не изменены; задача не исполнялась.")
    print("No model/provider CLI invoked / Модели и CLI провайдеров не запускались.")
    print(f"Evidence / Доказательства: {logs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
