#!/usr/bin/env python3
"""merge_lifecycle.py — управление переходом PR -> main -> release -> deployed.

ПРОБЛЕМА (заявка #151, внешнее ревью 19.08.2026): кит управляет работой ДО запроса на слияние,
но не управляет переходом `PR -> main -> release -> deployed`. `gh pr merge --auto` ждёт только
обязательных проверок, но если их не настроено — PR сливается немедленно при красных проверках.

РЕШЕНИЕ: явные состояния и доказательство КАЖДОГО перехода.

Состояния жизненного цикла:
  draft -> ready_for_review -> verified -> approved -> merged -> released -> deployed -> observed

Каждый переход требует доказательства:
  - verified: все проверки зелёные
  - approved: есть approval от владельца
  - merged: слит, ПОТОМУ ЧТО условия X/Y/Z были истинны
  - released: выпущена версия
  - deployed: выкатано на прод
  - observed: наблюдается в продакшене

Использование:
    merge_lifecycle.py <child_root> check-merge <pr_url>    # проверить готовность к слиянию
    merge_lifecycle.py <child_root> status <pr_url>         # показать статус PR
    merge_lifecycle.py --selftest
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run_gh(*args, cwd=None) -> tuple[int, str, str]:
    """Run gh CLI command."""
    try:
        result = subprocess.run(
            ["gh", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode, result.stdout, result.stderr
    # Узкий тип (фаза 0, 19.08.2026): запуск может не состояться (нет бинаря, права, битый
    # симлинк) или не уложиться в timeout. Любое ДРУГОЕ исключение здесь — дефект вызова, и он
    # обязан всплыть, а не превратиться в «rc=1» и молча стать «команда не сработала».
    # Тип ошибки НАЗЫВАЕТСЯ в тексте: «не смогли запустить» и «команда вернула ошибку» —
    # разные ответы, и по голому str(e) их не различить.
    except (OSError, subprocess.SubprocessError) as e:
        return 1, "", f"{type(e).__name__}: {e}"


def check_required_checks(root: Path) -> dict:
    """Check if required checks are configured for the repository."""
    # Get default branch
    rc, out, _ = _run_gh("repo", "view", "--json", "defaultBranchRef", cwd=root)
    if rc != 0:
        return {"error": "Failed to get default branch"}

    try:
        data = json.loads(out)
        branch = data.get("defaultBranchRef", {}).get("name", "main")
    except (json.JSONDecodeError, KeyError):
        branch = "main"

    # Get branch protection rules
    rc, out, _ = _run_gh(
        "api", f"repos/{{owner}}/{{repo}}/branches/{branch}/protection",
        cwd=root
    )

    if rc != 0:
        return {
            "configured": False,
            "branch": branch,
            "message": "No branch protection rules configured. `gh pr merge --auto` will merge immediately.",
        }

    try:
        protection = json.loads(out)
        required_checks = protection.get("required_status_checks", {})
        checks = required_checks.get("contexts", [])
        strict = required_checks.get("strict", False)

        return {
            "configured": True,
            "branch": branch,
            "required_checks": checks,
            "strict": strict,
            "count": len(checks),
        }
    except (json.JSONDecodeError, KeyError) as e:
        return {"error": f"Failed to parse protection rules: {e}"}


def check_pr_status(root: Path, pr_url: str) -> dict:
    """Check PR status and readiness for merge."""
    # Extract PR number from URL
    try:
        pr_number = pr_url.rstrip("/").split("/")[-1]
    except (IndexError, AttributeError):
        return {"error": f"Invalid PR URL: {pr_url}"}

    # Get PR details
    rc, out, _ = _run_gh(
        "pr", "view", pr_number,
        "--json", "number,title,state,statusCheckRollup,reviewDecision,mergeable",
        cwd=root
    )

    if rc != 0:
        return {"error": f"Failed to get PR {pr_number}"}

    try:
        pr = json.loads(out)
    except json.JSONDecodeError:
        return {"error": "Failed to parse PR data"}

    # Analyze status
    checks = pr.get("statusCheckRollup", []) or []
    total_checks = len(checks)
    passed_checks = sum(1 for c in checks if c.get("conclusion") == "SUCCESS")
    failed_checks = sum(1 for c in checks if c.get("conclusion") in ("FAILURE", "ERROR"))
    pending_checks = total_checks - passed_checks - failed_checks

    review_decision = pr.get("reviewDecision", "")
    mergeable = pr.get("mergeable", "")

    # Determine lifecycle state
    state = pr.get("state", "UNKNOWN")
    if state == "MERGED":
        lifecycle_state = "merged"
    elif state == "CLOSED":
        lifecycle_state = "closed"
    elif mergeable == "CONFLICTING":
        lifecycle_state = "conflicting"
    elif failed_checks > 0:
        lifecycle_state = "failing"
    elif pending_checks > 0:
        lifecycle_state = "pending"
    elif passed_checks == total_checks and total_checks > 0:
        if review_decision == "APPROVED":
            lifecycle_state = "approved"
        else:
            lifecycle_state = "verified"
    else:
        lifecycle_state = "draft"

    # Check merge readiness
    can_merge = (
        lifecycle_state in ("approved", "verified")
        and mergeable == "MERGEABLE"
        and failed_checks == 0
        and pending_checks == 0
    )

    return {
        "pr_number": int(pr_number),
        "title": pr.get("title", ""),
        "state": state,
        "lifecycle_state": lifecycle_state,
        "mergeable": mergeable,
        "review_decision": review_decision,
        "checks": {
            "total": total_checks,
            "passed": passed_checks,
            "failed": failed_checks,
            "pending": pending_checks,
        },
        "can_merge": can_merge,
        "merge_blocked_reason": None if can_merge else _merge_blocked_reason(lifecycle_state, mergeable, failed_checks, pending_checks),
    }


def _merge_blocked_reason(lifecycle_state: str, mergeable: str, failed: int, pending: int) -> str:
    """Determine why merge is blocked."""
    if lifecycle_state == "conflicting":
        return "Merge conflicts must be resolved"
    if failed > 0:
        return f"{failed} check(s) failing"
    if pending > 0:
        return f"{pending} check(s) still pending"
    if lifecycle_state == "draft":
        return "PR is in draft state"
    if mergeable != "MERGEABLE":
        return f"PR is not mergeable ({mergeable})"
    return "Unknown reason"


def format_status(status: dict) -> str:
    """Format PR status into human-readable output."""
    lines = []

    if "error" in status:
        return f"Error: {status['error']}"

    lines.append(f"# PR #{status['pr_number']}: {status['title']}\n")
    lines.append(f"**State:** {status['state']}")
    lines.append(f"**Lifecycle:** {status['lifecycle_state']}")
    lines.append(f"**Mergeable:** {status['mergeable']}")
    lines.append(f"**Review:** {status['review_decision']}\n")

    checks = status.get("checks", {})
    lines.append("## Checks\n")
    lines.append(f"- Total: {checks.get('total', 0)}")
    lines.append(f"- Passed: {checks.get('passed', 0)}")
    lines.append(f"- Failed: {checks.get('failed', 0)}")
    lines.append(f"- Pending: {checks.get('pending', 0)}\n")

    if status.get("can_merge"):
        lines.append("✅ **Ready to merge**\n")
    else:
        reason = status.get("merge_blocked_reason", "Unknown")
        lines.append(f"🚫 **Merge blocked:** {reason}\n")

    return "\n".join(lines)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Merge lifecycle management")
    ap.add_argument("root", nargs="?", default=".", help="Repository root")
    ap.add_argument("command", nargs="?", choices=["check-merge", "status", "check-required"],
                    help="Command to run")
    ap.add_argument("pr_url", nargs="?", help="PR URL (for check-merge/status)")
    ap.add_argument("--json", action="store_true", help="Output as JSON")
    ap.add_argument("--selftest", action="store_true", help="Run self-test")
    args = ap.parse_args()

    if args.selftest:
        # ЧЕСТНЫЙ --selftest (фаза 0, 19.08.2026). Здесь печаталась строка о пройденном
        # селфтесте и три строки «... : OK» — без единого вызова проверяемых функций. То есть
        # модуль УТВЕРЖДАЛ проверку, которой не было: ровно класс «объявлено, но не
        # исполняется», против которого стоит весь кит (ср. R-31/R-32 — две фиктивные проверки
        # в валидаторах). Образец честной формы — devtools/mutation_probe.py: модуль объясняет
        # себя и называет, где лежат его настоящие проверки. Правило репозитория (AGENTS.md):
        # тест модуля живёт в tests/, а не в продакшн-модуле, который едет в child-репозиторий.
        print(__doc__)
        print("Проверки модуля — в tests/unit/ (AGENTS.md: selftest не живёт в продакшн-модуле).")
        return 0

    root = Path(args.root).resolve()

    if args.command == "check-required":
        result = check_required_checks(root)
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            if result.get("configured"):
                print(f"✅ Required checks configured for branch '{result['branch']}'")
                print(f"   Checks: {', '.join(result['required_checks'])}")
                print(f"   Strict: {result['strict']}")
            else:
                print(f"⚠️  {result.get('message', 'No required checks configured')}")
        return 0

    elif args.command in ("check-merge", "status"):
        if not args.pr_url:
            print("Error: PR URL required", file=sys.stderr)
            return 1
        result = check_pr_status(root, args.pr_url)
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(format_status(result))
        return 0

    else:
        ap.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
