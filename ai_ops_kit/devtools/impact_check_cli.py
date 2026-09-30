"""Local kit iteration checks; shared selection policy also powers child evidence collection."""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

from ai_ops_kit.gates import verification_tiers


def changed_paths(root: Path, base: str | None) -> list[str]:
    """Include committed base diff, index, worktree and untracked files (including deletions)."""
    commands = [["git", "diff", "--no-renames", "--name-only", "-z", "HEAD"],
                ["git", "ls-files", "--others", "--exclude-standard", "-z"]]
    if base:
        commands.append(["git", "diff", "--no-renames", "--name-only", "-z", f"{base}...HEAD"])
    paths = set()
    for command in commands:
        output = subprocess.check_output(command, cwd=root)
        paths.update(p for p in output.decode().split("\0") if p)
    return sorted(paths)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--base", help="git comparison ref; local changes are always included")
    parser.add_argument("--intent", choices=("draft", "ready_for_review", "merge_candidate", "release_candidate"), default="draft")
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        changed = changed_paths(root, args.base)
    except (subprocess.CalledProcessError, OSError) as exc:
        print(f"Cannot determine complete change scope: {exc}", file=sys.stderr)
        return 2
    profile = {"stacks": [{"language": "python", "commands": {
        "test": shlex.join([sys.executable, "-m", "pytest", "tests/", "-q"])}}]}
    result = verification_tiers.select_tests(changed, str(root), lifecycle_intent=args.intent, profile=profile)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    if args.plan_only or result["tier"] == "skip":
        return 0
    if result["full_command"]:
        return subprocess.call(["bash", "scripts/check-full.sh"], cwd=root,
                               env={**os.environ, "PYTHON": sys.executable, "PYTHONDONTWRITEBYTECODE": "1"})
    # Targeted commands here are generated solely by the simple pytest rewriter.
    return subprocess.call(shlex.split(result["targeted_command"]), cwd=root,
                           env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})


if __name__ == "__main__":
    sys.exit(main())
