"""Адаптер commit-msg: Git/сообщение → существующий CommitContract.

Shell отвечает за окружение и exec; предметные решения остаются в Python.
"""
from __future__ import annotations

import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys

from ai_ops_kit.engops import commit_policy
from ai_ops_kit.lifecycle import active_work


def staged_files(root: Path) -> list[str]:
    """NUL сохраняет пробелы, переводы строк и имена, похожие на опции."""
    override = os.environ.get("COMMIT_CONTRACT_FILES")
    if override:
        # Прежний тестовый шов; реальный hook всегда читает индекс Git.
        return override.split()
    result = subprocess.run(
        ["git", "-C", str(root), "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"],
        capture_output=True, check=True,
    )
    return [os.fsdecode(name) for name in result.stdout.split(b"\0") if name]


def warn_claims(root: Path, files: list[str]) -> None:
    """Координация advisory, как в прежнем hook; verdict от неё не зависит."""
    if os.environ.get("COMMIT_CONTRACT_SKIP_CLAIMS"):
        return
    try:
        registry = active_work.shared_registry_path(root)
        if not registry.is_file():
            return
        areas = sorted({name.split("/", 1)[0] + ("/" if "/" in name else "") for name in files})
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            active_work.check_cmd(registry, areas)
        for line in output.getvalue().splitlines():
            if "пересечений по зонам" not in line:
                print(line)
    except (OSError, ValueError, RuntimeError, active_work.ActiveWorkCorrupt):
        # Недоступная координация никогда не отключает сам CommitContract.
        pass


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or not Path(argv[0]).is_file():
        print("commit-contract: не передан файл сообщения коммита — хук вызван не со стадии commit-msg.",
              file=sys.stderr)
        return 2
    root = Path.cwd()
    try:
        files = staged_files(root)
        if not files:
            return 0  # merge/amend без изменений индекса
        message = "\n".join(line for line in Path(argv[0]).read_text(encoding="utf-8").splitlines()
                            if not line.startswith("#") and line.strip())
    except (OSError, UnicodeError, subprocess.CalledProcessError) as exc:
        print(f"CommitContract НЕ ВЫПОЛНЕН: индекс/сообщение не прочитаны ({type(exc).__name__}).",
              file=sys.stderr)
        return 1
    warn_claims(root, files)
    verdict = commit_policy.check_commit(
        files, message, protected_paths=commit_policy.protected_from_config(root),
        policy=commit_policy.policy_from_config(root),
    )
    print(commit_policy._fmt(verdict))
    return 0 if verdict["allowed"] else 1


if __name__ == "__main__":
    sys.exit(main())
