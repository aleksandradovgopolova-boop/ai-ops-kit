#!/usr/bin/env python3
"""refusal_paths.py — проверка веток отказа: названный флаг существует, причина верна.

ПРОБЛЕМА (refusal-paths-say-the-truth): кит печатает советы с флагами/командами, которых нет.
Пользователь копирует строку — получает ошибку. Совет, который нельзя выполнить, ХУЖЕ отсутствия.

ЧТО ПРОВЕРЯЕТ:
- Все упомянутые в отказах флаги CLI существуют
- Все упомянутые команды существуют
- Причины отказов не содержат сырых traceback

Использование:
    refusal_paths.py <child_root> [--json]
    refusal_paths.py --selftest
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def check_refusal_paths(root: Path) -> dict:
    """Check that refusal paths mention real flags and commands."""
    issues = []

    # Check CLI flags mentioned in error messages
    cli_path = root / "ai_ops_kit" / "cli" / "ai_ops_cli.py"
    if cli_path.exists():
        content = cli_path.read_text(encoding="utf-8")
        # Find all --flag definitions
        defined_flags = set(re.findall(r'--([a-z0-9-]+)', content))

        # Check error messages for mentioned flags
        error_patterns = [
            r'unrecognized arguments: --([a-z0-9-]+)',
            r'invalid choice: \'([a-z0-9-]+)\'',
            r'unknown flag: --([a-z0-9-]+)',
        ]

        for pattern in error_patterns:
            for match in re.finditer(pattern, content):
                flag = match.group(1)
                if flag not in defined_flags:
                    issues.append({
                        "type": "undefined_flag",
                        "flag": flag,
                        "context": "CLI error message mentions undefined flag",
                    })

    # Check for raw tracebacks in error messages
    engops_path = root / "ai_ops_kit" / "engops"
    if engops_path.exists():
        for py_file in engops_path.glob("*.py"):
            content = py_file.read_text(encoding="utf-8")
            if "Traceback (most recent call last)" in content:
                # Check if it's in a string literal (error message)
                if re.search(r'["\'].*Traceback.*["\']', content, re.DOTALL):
                    issues.append({
                        "type": "raw_traceback",
                        "file": str(py_file.relative_to(root)),
                        "context": "Error message contains raw traceback",
                    })

    return {
        "schema_version": 1,
        "kind": "refusal-paths-check",
        "issues": issues,
        "total_issues": len(issues),
        "status": "pass" if not issues else "fail",
    }


def format_report(report: dict) -> str:
    """Format check results into human-readable report."""
    lines = []
    lines.append("# Refusal Paths Check\n")

    if report["status"] == "pass":
        lines.append("✅ All refusal paths are valid\n")
    else:
        lines.append(f"❌ Found {report['total_issues']} issue(s)\n")
        for issue in report["issues"]:
            lines.append(f"- **{issue['type']}**: {issue.get('flag', issue.get('file', '?'))}")
            lines.append(f"  {issue['context']}\n")

    return "\n".join(lines)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Check refusal paths validity")
    ap.add_argument("root", nargs="?", default=".", help="Repository root")
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
    report = check_refusal_paths(root)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(format_report(report))

    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
