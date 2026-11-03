#!/usr/bin/env python3
"""Black-box bootstrap compatibility probe. Only temporary Git projects; no models.

Called explicitly by pipeline-e2e on its Python matrix, including draft PRs.
Network is needed only for the existing PyYAML dependency from PyPI.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import venv


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheelhouse", type=Path, help="Optional trusted wheel cache for offline replay")
    args = parser.parse_args(argv)
    extra = ["--wheelhouse", str(args.wheelhouse.resolve())] if args.wheelhouse else []
    source = Path(__file__).resolve().parents[2]
    scratch = Path(tempfile.mkdtemp(prefix="ai-ops-bootstrap-probe-"))
    checkout, project = scratch / "kit source", scratch / "sample project"
    logs = scratch / "evidence"
    logs.mkdir()
    env = {
        "PATH": os.environ.get("PATH", os.defpath),
        "HOME": str(scratch / "home"),
        "CODEX_HOME": str(scratch / "codex-home"),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    Path(env["HOME"]).mkdir()
    Path(env["CODEX_HOME"]).mkdir()
    print(f"Bootstrap probe evidence: {logs}", flush=True)
    commands = []

    def run(label, argv, cwd=scratch):
        result = subprocess.run(argv, cwd=cwd, env=env, capture_output=True,
                                text=True, timeout=240)
        (logs / f"{label}.stdout.txt").write_text(result.stdout, encoding="utf-8")
        (logs / f"{label}.stderr.txt").write_text(result.stderr, encoding="utf-8")
        commands.append({"step": label, "argv": list(map(str, argv)), "returncode": result.returncode})
        (logs / "commands.json").write_text(json.dumps(commands, indent=2) + "\n")
        if result.returncode:
            raise RuntimeError(f"{label}: exit {result.returncode}\n{result.stdout}\n{result.stderr}")
        return result.stdout

    run("clone", ["git", "clone", "--no-hardlinks", str(source), str(checkout)])
    run("source-remote", ["git", "remote", "set-url", "origin",
                          "https://github.com/aleksandradovgopolova-boop/ai-ops-kit.git"], checkout)
    shutil.copytree(source / "examples/first-session/sample", project,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (project / "AGENTS.md").write_text("Preserve owner instructions.\n")
    (project / ".ai/custom").mkdir(parents=True)
    (project / ".ai/custom/owner.txt").write_text("Preserve owner policy.\n")
    (project / ".claude").mkdir()
    (project / ".claude/settings.json").write_text(json.dumps({"owner_key": "preserve"}))
    run("git-init", ["git", "init", "-q", "-b", "main"], project)
    for key, value in (("user.name", "AI Ops Sample"), ("user.email", "sample@example.invalid"),
                       ("commit.gpgsign", "false")):
        run(key, ["git", "config", key, value], project)
    originals = ("README.md", "pyproject.toml", "greeting.py", "tests/test_greeting.py",
                 "AGENTS.md", ".ai/custom/owner.txt")
    run("git-add", ["git", "add", *originals, ".claude/settings.json"], project)
    run("seed", ["git", "commit", "-qm", "chore: seed bootstrap sample"], project)
    (project / "private-notes.txt").write_text("Untracked local notes.\n")
    saved = {p: (project / p).read_bytes() for p in (*originals, "private-notes.txt")}
    before = run("head-before", ["git", "rev-parse", "HEAD"], project).strip()
    venv.EnvBuilder(with_pip=False).create(scratch / "starter")
    starter = scratch / "starter/bin/python3"
    run("dependency-absent", [str(starter), "-I", "-c",
                             "import importlib.util; assert importlib.util.find_spec('yaml') is None"])
    for language in ("en", "ru"):
        run("setup-" + language, [str(starter), str(checkout / "installer/bootstrap.py"),
                                  str(project), "--language", language, *extra])
        assert all((project / p).read_bytes() == data for p, data in saved.items())
        assert json.loads((project / ".claude/settings.json").read_text())["owner_key"] == "preserve"
        assert not run("notes-tracked-" + language, ["git", "ls-files", "private-notes.txt"], project).strip()
    assert run("head-after", ["git", "rev-parse", "HEAD"], project).strip() != before
    activate = checkout / ".ai/runtime/bootstrap/venv/bin/activate"
    run("activation-doctor", ["/bin/bash", "-c", 'source "$1"; cd "$2"; ./ai-ops doctor',
                              "activation-proof", str(activate), str(project)])
    demo = run("demo", [str(starter), str(checkout / "installer/bootstrap.py"), "--demo", "--language", "en", *extra])
    assert "PASS: 9 local commands" in demo
    report = {"python": sys.version.split()[0], "platform": sys.platform,
              "source_head": run("source-head", ["git", "rev-parse", "HEAD"], source).strip(),
              "cold_dependency_absent": True, "setup_languages": ["en", "ru"],
              "dependency_source": "trusted wheelhouse" if args.wheelhouse else "PyPI",
              "source_sha256": {p: hashlib.sha256(b).hexdigest() for p, b in saved.items()},
              "owner_settings_preserved": True, "untracked_notes_not_committed": True,
              "activation_doctor": "passed", "demo": "passed", "model_calls": 0}
    (logs / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)
    return 0


def test_bootstrap_compatibility():
    """Run the real cold setup/retry/activation/demo proof through pytest in CI."""
    assert main([]) == 0


if __name__ == "__main__":
    raise SystemExit(main())
