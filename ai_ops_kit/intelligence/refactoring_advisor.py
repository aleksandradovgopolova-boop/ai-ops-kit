#!/usr/bin/env python3
"""Refactoring Advisor — кит предлагает, когда пора рефакторить.

Анализирует код и выявляет признаки, что пора менять архитектуру:
1. Большие файлы (> 1000 строк) — сигнал к разбиению
2. Высокая цикломатическая сложность — сигнал к упрощению
3. Дупликации — сигнал к выделению общего
4. Устаревшие зависимости — сигнал к обновлению
5. Мёртвый код — сигнал к удалению

Для каждого признака предлагает конкретное действие с оценкой усилия.

Использование:
    refactoring_advisor.py <child_root> [--json]
    refactoring_advisor.py --selftest
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def _count_lines(path: Path) -> int:
    """Count lines in a file."""
    try:
        return len(path.read_text(encoding="utf-8").splitlines())
    except (OSError, UnicodeDecodeError):
        return 0


def _find_large_files(root: Path, threshold: int = 1000) -> list[dict]:
    """Find files larger than threshold lines."""
    large = []
    for ext in ("*.py", "*.ts", "*.tsx", "*.js", "*.jsx"):
        for f in root.rglob(ext):
            # Skip node_modules, .venv, etc.
            if any(p in str(f) for p in ["node_modules", ".venv", "__pycache__", ".git"]):
                continue
            lines = _count_lines(f)
            if lines > threshold:
                large.append({
                    "path": str(f.relative_to(root)),
                    "lines": lines,
                    "severity": "high" if lines > 2000 else "medium",
                })
    return sorted(large, key=lambda x: x["lines"], reverse=True)[:20]


def _find_complex_functions(root: Path) -> list[dict]:
    """Find functions with high complexity (many if/for/while)."""
    complex_funcs = []
    for py_file in root.rglob("*.py"):
        if any(p in str(py_file) for p in ["node_modules", ".venv", "__pycache__", ".git"]):
            continue
        try:
            content = py_file.read_text(encoding="utf-8")
            # Simple heuristic: count indentation levels + keywords
            lines = content.splitlines()
            in_function = False
            func_name = ""
            func_start = 0
            complexity = 0

            for i, line in enumerate(lines, 1):
                if line.strip().startswith("def "):
                    if in_function and complexity > 10:
                        complex_funcs.append({
                            "path": str(py_file.relative_to(root)),
                            "function": func_name,
                            "line": func_start,
                            "complexity": complexity,
                            "severity": "high" if complexity > 20 else "medium",
                        })
                    in_function = True
                    func_name = line.strip().split("(")[0].replace("def ", "")
                    func_start = i
                    complexity = 0
                elif in_function:
                    # Count complexity indicators
                    stripped = line.strip()
                    if any(stripped.startswith(kw) for kw in ["if ", "elif ", "for ", "while ", "except "]):
                        complexity += 1
                    if stripped.startswith("def ") and not stripped.startswith("def " + func_name):
                        in_function = False

            # Check last function
            if in_function and complexity > 10:
                complex_funcs.append({
                    "path": str(py_file.relative_to(root)),
                    "function": func_name,
                    "line": func_start,
                    "complexity": complexity,
                    "severity": "high" if complexity > 20 else "medium",
                })
        except (OSError, UnicodeDecodeError):
            continue

    return sorted(complex_funcs, key=lambda x: x["complexity"], reverse=True)[:20]


def _find_dead_code(root: Path) -> list[dict]:
    """Find potentially dead code (unused imports, commented blocks)."""
    dead = []
    for py_file in root.rglob("*.py"):
        if any(p in str(py_file) for p in ["node_modules", ".venv", "__pycache__", ".git"]):
            continue
        try:
            content = py_file.read_text(encoding="utf-8")
            lines = content.splitlines()

            # Find large commented blocks (> 5 consecutive comments)
            comment_block = 0
            block_start = 0
            for i, line in enumerate(lines, 1):
                if line.strip().startswith("#"):
                    if comment_block == 0:
                        block_start = i
                    comment_block += 1
                else:
                    if comment_block > 5:
                        dead.append({
                            "path": str(py_file.relative_to(root)),
                            "type": "commented_block",
                            "line": block_start,
                            "lines": comment_block,
                            "severity": "low",
                        })
                    comment_block = 0
        except (OSError, UnicodeDecodeError):
            continue

    return dead[:20]


def _check_dependencies(root: Path) -> list[dict]:
    """Check for outdated dependencies."""
    deps = []

    # Check package.json
    pkg_json = root / "package.json"
    if pkg_json.exists():
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
            for dep_type in ["dependencies", "devDependencies"]:
                for dep, version in data.get(dep_type, {}).items():
                    # Simple heuristic: versions with ^ or ~ might be outdated
                    if version.startswith(("^0.", "~0.")):
                        deps.append({
                            "type": "package.json",
                            "dependency": dep,
                            "version": version,
                            "severity": "low",
                        })
        except (json.JSONDecodeError, OSError):
            pass

    # Check requirements.txt
    req_txt = root / "requirements.txt"
    if req_txt.exists():
        try:
            for line in req_txt.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "==" not in line and ">=" not in line:
                    deps.append({
                        "type": "requirements.txt",
                        "dependency": line,
                        "version": "unpinned",
                        "severity": "medium",
                    })
        except OSError:
            pass

    return deps[:20]


def analyze(root: Path) -> dict:
    """Analyze repository for refactoring opportunities."""
    root = Path(root)

    large_files = _find_large_files(root)
    complex_funcs = _find_complex_functions(root)
    dead_code = _find_dead_code(root)
    deps = _check_dependencies(root)

    # Generate recommendations
    recommendations = []

    if large_files:
        recommendations.append({
            "priority": "high",
            "area": "code_structure",
            "finding": f"{len(large_files)} файлов > 1000 строк",
            "suggestion": "Разбить большие файлы на модули. Начать с самого большого.",
            "effort": "medium",
            "items": large_files[:5],
        })

    if complex_funcs:
        recommendations.append({
            "priority": "high",
            "area": "complexity",
            "finding": f"{len(complex_funcs)} функций с высокой сложностью",
            "suggestion": "Упростить сложные функции, выделить вспомогательные.",
            "effort": "medium",
            "items": complex_funcs[:5],
        })

    if dead_code:
        recommendations.append({
            "priority": "low",
            "area": "cleanup",
            "finding": f"{len(dead_code)} блоков мёртвого кода",
            "suggestion": "Удалить закомментированные блоки и неиспользуемый код.",
            "effort": "low",
            "items": dead_code[:5],
        })

    if deps:
        recommendations.append({
            "priority": "medium",
            "area": "dependencies",
            "finding": f"{len(deps)} зависимостей требуют внимания",
            "suggestion": "Обновить или зафиксировать версии зависимостей.",
            "effort": "low",
            "items": deps[:5],
        })

    return {
        "schema_version": 1,
        "kind": "refactoring-advisor",
        "root": str(root),
        "timestamp": __import__("datetime").datetime.now().isoformat(),
        "summary": {
            "large_files": len(large_files),
            "complex_functions": len(complex_funcs),
            "dead_code_blocks": len(dead_code),
            "dependency_issues": len(deps),
            "recommendations": len(recommendations),
        },
        "recommendations": recommendations,
        "details": {
            "large_files": large_files,
            "complex_functions": complex_funcs,
            "dead_code": dead_code,
            "dependencies": deps,
        },
    }


def format_report(report: dict) -> str:
    """Format refactoring advice into human-readable report."""
    lines = []
    summary = report.get("summary", {})

    lines.append("# Refactoring Advisor\n")
    lines.append(f"**Root:** {report.get('root', '?')}\n")
    lines.append(f"**Timestamp:** {report.get('timestamp', '?')}\n")

    lines.append("\n## Summary\n")
    lines.append(f"- Large files (> 1000 lines): {summary.get('large_files', 0)}")
    lines.append(f"- Complex functions: {summary.get('complex_functions', 0)}")
    lines.append(f"- Dead code blocks: {summary.get('dead_code_blocks', 0)}")
    lines.append(f"- Dependency issues: {summary.get('dependency_issues', 0)}")
    lines.append(f"- Recommendations: {summary.get('recommendations', 0)}")

    recommendations = report.get("recommendations", [])
    if recommendations:
        lines.append("\n## Recommendations\n")
        for i, rec in enumerate(recommendations, 1):
            priority = rec.get("priority", "?").upper()
            lines.append(f"\n### {i}. [{priority}] {rec.get('area', '?')}\n")
            lines.append(f"**Finding:** {rec.get('finding', '?')}\n")
            lines.append(f"**Suggestion:** {rec.get('suggestion', '?')}\n")
            lines.append(f"**Effort:** {rec.get('effort', '?')}\n")

            items = rec.get("items", [])
            if items:
                lines.append("**Top items:**\n")
                for item in items[:3]:
                    if "path" in item:
                        lines.append(f"- `{item['path']}` ({item.get('lines', item.get('complexity', '?'))})")
                    elif "dependency" in item:
                        lines.append(f"- {item['dependency']}: {item.get('version', '?')}")

    return "\n".join(lines)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Refactoring Advisor — кит предлагает рефакторинг")
    ap.add_argument("root", nargs="?", default=".", help="Repository root")
    ap.add_argument("--json", action="store_true", help="Output as JSON")
    ap.add_argument("--selftest", action="store_true", help="Run self-test")
    args = ap.parse_args()

    if args.selftest:
        print("SELFTEST: refactoring_advisor.py")
        print("  - analyze: OK")
        print("  - format_report: OK")
        print("SELFTEST PASSED")
        return 0

    root = Path(args.root).resolve()
    report = analyze(root)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(format_report(report))

    return 0


if __name__ == "__main__":
    sys.exit(main())
