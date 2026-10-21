"""Local kit iteration checks; shared selection policy also powers child evidence collection."""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from ai_ops_kit.gates import verification_tiers
from ai_ops_kit.shared import lifecycle_store as receipts
from ai_ops_kit.devtools import host_resource_cli as host_resources


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
        "test": shlex.join([sys.executable, "-m", "pytest", "tests/", "-q",
                            "-m", "not nightly and not release_gate"])}}]}
    result = verification_tiers.select_tests(changed, str(root), lifecycle_intent=args.intent, profile=profile)
    if result["full_command"]:
        release = args.intent == "release_candidate"
        result["full_profile"] = "full-current-python" if release else "pr-current-python"
        result["full_argv"] = ["bash", "scripts/check-full.sh", *([] if release else ["--pr"])]
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    if args.plan_only:
        return 0
    if not result["full_command"]:
        ruff = shutil.which("ruff")
        if not ruff:
            print("BLOCKED: ruff недоступен; обязательная статическая проверка не исполнена")
            return 2
        def lint():
            code = subprocess.call([ruff, "check", "."], cwd=root, **host_resources.subprocess_kwargs())
            return {"status": "PASS" if code == 0 else "FAIL", "exit_code": code}
        lint_receipt = receipts.run(root, "lint", [ruff, "check", "."], lint,
                                    lambda: receipts.python_context(root))
        print(json.dumps(lint_receipt, ensure_ascii=False, indent=2), file=sys.stderr)
        if lint_receipt["status"] != "PASS":
            return 1
    if result["tier"] == "skip":
        print(json.dumps({"status": "SKIP", "check": "product-tests", "reason": result["note"]}), file=sys.stderr)
        return 0
    command = (result["full_argv"] if result["full_command"] else
               shlex.split(result["targeted_command"]))
    def execute():
        code = subprocess.call(command, cwd=root, env={**os.environ, "PYTHON": sys.executable,
                                                       "PYTHONDONTWRITEBYTECODE": "1"},
                               **host_resources.subprocess_kwargs())
        return {"status": "PASS" if code == 0 else "FAIL", "exit_code": code}
    receipt = receipts.run(root, "impact-tests", command, execute, lambda: receipts.python_context(root),
                           scope=result.get("full_profile", "local"),
                           output_contract=receipts.PYTEST_OUTPUTS)
    print(json.dumps(receipt, ensure_ascii=False, indent=2), file=sys.stderr)
    if receipt["status"] == "PASS":
        return 0
    if receipt["status"] == "BLOCKED":
        return 2
    return receipt["exit_code"] if isinstance(receipt.get("exit_code"), int) and receipt["exit_code"] else 1


if __name__ == "__main__":
    sys.exit(main())
