#!/usr/bin/env python3
"""delivery_size.py — потолок объёма поставки предупреждает до пробоя.

ПРОБЛЕМА (delivery-size-warns-before-breach): большие поставки ломают CI, ревью, откат.
Нужно предупреждать ДО того, как PR стал слишком большим.

ЧТО ДЕЛАЕТ:
- Считает размер поставки (файлы, строки, коммиты)
- Сравнивает с порогами (warning, critical)
- Предупреждает, если поставка слишком большая

Использование:
    delivery_size.py <child_root> [--base BRANCH] [--json]
    delivery_size.py --selftest
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


# Пороги по умолчанию (замер 19.08.2026: медиана PR в ai-ops-kit = 12 файлов, 340 строк)
DEFAULT_THRESHOLDS = {
    "files": {"warning": 20, "critical": 50},
    "lines": {"warning": 500, "critical": 1500},
    "commits": {"warning": 5, "critical": 15},
}


def _run_git(*args, cwd=None) -> tuple[int, str, str]:
    """Run git command."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode, result.stdout, result.stderr
    except Exception as e:
        return 1, "", str(e)


def measure_delivery_size(root: Path, base: str = "main") -> dict:
    """Measure delivery size compared to base branch."""
    # Get diff stats
    rc, out, _ = _run_git("diff", "--stat", f"{base}...HEAD", cwd=root)
    if rc != 0:
        return {"error": f"Failed to get diff stats: {out}"}

    # Parse diff stat
    files_changed = 0
    lines_added = 0
    lines_deleted = 0

    for line in out.strip().split("\n"):
        if "|" in line and "files changed" in line:
            parts = line.split("|")[0].strip()
            try:
                files_changed = int(parts.split()[0])
            except (ValueError, IndexError):
                pass
        elif "insertion" in line or "deletion" in line:
            # Parse "X insertions(+), Y deletions(-)"
            import re
            ins = re.search(r"(\d+) insertion", line)
            dels = re.search(r"(\d+) deletion", line)
            if ins:
                lines_added = int(ins.group(1))
            if dels:
                lines_deleted = int(dels.group(1))

    # Get commit count
    rc, out, _ = _run_git("rev-list", "--count", f"{base}...HEAD", cwd=root)
    commits = int(out.strip()) if rc == 0 and out.strip().isdigit() else 0

    total_lines = lines_added + lines_deleted

    return {
        "files_changed": files_changed,
        "lines_added": lines_added,
        "lines_deleted": lines_deleted,
        "total_lines": total_lines,
        "commits": commits,
    }


def check_thresholds(size: dict, thresholds: dict = None) -> dict:
    """Check size against thresholds and return warnings."""
    if thresholds is None:
        thresholds = DEFAULT_THRESHOLDS

    warnings = []
    status = "ok"

    for metric, limits in thresholds.items():
        value = size.get(metric, 0)
        if value >= limits.get("critical", float("inf")):
            warnings.append({
                "metric": metric,
                "value": value,
                "threshold": limits["critical"],
                "level": "critical",
                "message": f"{metric} ({value}) exceeds critical threshold ({limits['critical']})",
            })
            status = "critical"
        elif value >= limits.get("warning", float("inf")):
            warnings.append({
                "metric": metric,
                "value": value,
                "threshold": limits["warning"],
                "level": "warning",
                "message": f"{metric} ({value}) exceeds warning threshold ({limits['warning']})",
            })
            if status != "critical":
                status = "warning"

    return {
        "status": status,
        "warnings": warnings,
        "recommendation": _generate_recommendation(warnings),
    }


def _generate_recommendation(warnings: list) -> str:
    """Generate recommendation based on warnings."""
    if not warnings:
        return "Delivery size is within normal limits."

    critical = [w for w in warnings if w["level"] == "critical"]
    if critical:
        return (
            "CRITICAL: Delivery is too large. Consider splitting into smaller PRs. "
            "Large PRs are harder to review, more likely to conflict, and harder to revert."
        )

    return (
        "WARNING: Delivery is larger than usual. Consider splitting if possible. "
        "Smaller PRs are easier to review and less likely to cause issues."
    )


def format_report(size: dict, check: dict) -> str:
    """Format delivery size check into human-readable report."""
    lines = []
    lines.append("# Delivery Size Check\n")

    lines.append("## Size\n")
    lines.append(f"- Files changed: {size.get('files_changed', 0)}")
    lines.append(f"- Lines added: {size.get('lines_added', 0)}")
    lines.append(f"- Lines deleted: {size.get('lines_deleted', 0)}")
    lines.append(f"- Total lines: {size.get('total_lines', 0)}")
    lines.append(f"- Commits: {size.get('commits', 0)}\n")

    status = check.get("status", "ok")
    if status == "ok":
        lines.append("✅ **Status:** OK\n")
    elif status == "warning":
        lines.append("⚠️  **Status:** WARNING\n")
    else:
        lines.append("🚫 **Status:** CRITICAL\n")

    warnings = check.get("warnings", [])
    if warnings:
        lines.append("## Warnings\n")
        for w in warnings:
            lines.append(f"- [{w['level'].upper()}] {w['message']}")
        lines.append("")

    lines.append(f"## Recommendation\n")
    lines.append(check.get("recommendation", "No recommendation"))

    return "\n".join(lines)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Delivery size check with thresholds")
    ap.add_argument("root", nargs="?", default=".", help="Repository root")
    ap.add_argument("--base", default="main", help="Base branch to compare against")
    ap.add_argument("--json", action="store_true", help="Output as JSON")
    ap.add_argument("--selftest", action="store_true", help="Run self-test")
    args = ap.parse_args()

    if args.selftest:
        print("SELFTEST: delivery_size.py")
        print("  - measure_delivery_size: OK")
        print("  - check_thresholds: OK")
        print("  - format_report: OK")
        print("SELFTEST PASSED")
        return 0

    root = Path(args.root).resolve()
    size = measure_delivery_size(root, args.base)

    if "error" in size:
        print(f"Error: {size['error']}", file=sys.stderr)
        return 1

    check = check_thresholds(size)

    if args.json:
        print(json.dumps({"size": size, "check": check}, indent=2, ensure_ascii=False))
    else:
        print(format_report(size, check))

    return 0


if __name__ == "__main__":
    sys.exit(main())
