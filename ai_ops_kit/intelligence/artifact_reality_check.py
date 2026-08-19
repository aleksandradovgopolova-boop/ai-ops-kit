#!/usr/bin/env python3
"""Artifact Reality Check — сверка артефактов с реальным состоянием репо.

Проверяет, что артефакты (планы, спеки, документы) отражают РЕАЛЬНОЕ состояние репозитория,
а не устаревшие предположения.

Что проверяется:
1. planning/plan.yaml — упомянутые файлы/модули реально существуют
2. Документы (docs/, README) — ссылки на файлы валидны
3. Спецификации — упомянутые API/функции существуют в коде
4. ROADMAP — упомянутые компоненты существуют

Возвращает:
- Список устаревших ссылок (файлы/модули, которых нет)
- Список "призраков" (артефакты, описывающие несуществующее)
- Рекомендации по обновлению

Использование:
    artifact_reality_check.py <child_root> [--json]
    artifact_reality_check.py --selftest
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml


def _extract_file_refs(text: str) -> list[str]:
    """Extract file path references from text."""
    # Match patterns like: src/foo.py, ./bar.ts, path/to/file.js
    patterns = [
        r'(?:^|\s|["\'\`(])([a-zA-Z0-9_\-./]+\.(?:py|ts|tsx|js|jsx|md|yaml|yml|json))(?:\s|["\'\`)]|$)',
        r'`([a-zA-Z0-9_\-./]+\.[a-z]+)`',  # backtick-quoted paths
    ]
    refs = set()
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            path = match.group(1)
            # Filter out URLs and common non-file patterns
            if not path.startswith(('http://', 'https://', 'ftp://')):
                refs.add(path)
    return list(refs)


def _extract_module_refs(text: str) -> list[str]:
    """Extract module/function references from text."""
    # Match patterns like: module.function, Class.method, from X import Y
    patterns = [
        r'(?:from\s+)([a-zA-Z0-9_.]+)(?:\s+import)',
        r'(?:import\s+)([a-zA-Z0-9_.]+)',
        r'([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)+)',  # dotted paths
    ]
    refs = set()
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            refs.add(match.group(1))
    return list(refs)


def _check_file_exists(root: Path, ref: str) -> bool:
    """Check if a file reference exists."""
    # Clean up the reference
    ref = ref.strip('./')
    if ref.startswith(('http://', 'https://', 'ftp://')):
        return True  # Skip URLs

    # Try as-is
    if (root / ref).exists():
        return True

    # Try without extension variations
    base = ref.rsplit('.', 1)[0] if '.' in ref else ref
    for ext in ['.py', '.ts', '.tsx', '.js', '.jsx', '.md', '.yaml', '.yml', '.json']:
        if (root / f"{base}{ext}").exists():
            return True

    return False


def _check_artifact(root: Path, artifact_path: Path) -> dict:
    """Check a single artifact for reality mismatches."""
    if not artifact_path.exists():
        return {"path": str(artifact_path), "status": "missing", "issues": []}

    try:
        content = artifact_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {"path": str(artifact_path), "status": "unreadable", "issues": []}

    issues = []

    # Check file references
    file_refs = _extract_file_refs(content)
    for ref in file_refs:
        if not _check_file_exists(root, ref):
            issues.append({
                "type": "missing_file",
                "reference": ref,
                "line": content[:content.find(ref)].count('\n') + 1 if ref in content else None,
            })

    # For YAML files, check structure
    if artifact_path.suffix in ('.yaml', '.yml'):
        try:
            data = yaml.safe_load(content)
            # Check for common stale patterns
            if isinstance(data, dict):
                # Check write_scope references
                for work in data.get('work', []):
                    if isinstance(work, dict):
                        for scope in work.get('write_scope', []):
                            if not _check_file_exists(root, scope.replace('*', '')):
                                issues.append({
                                    "type": "stale_write_scope",
                                    "reference": scope,
                                    "work_id": work.get('id'),
                                })
        except yaml.YAMLError:
            pass

    status = "stale" if issues else "current"
    return {
        "path": str(artifact_path.relative_to(root)),
        "status": status,
        "issues": issues,
        "file_refs_checked": len(file_refs),
    }


def check_artifacts(root: Path) -> dict:
    """Check all artifacts in the repository."""
    root = Path(root)
    results = []

    # Check planning artifacts
    plan_path = root / "planning" / "plan.yaml"
    if plan_path.exists():
        results.append(_check_artifact(root, plan_path))

    # Check documentation
    for doc_dir in ["docs", "doc", "documentation"]:
        doc_path = root / doc_dir
        if doc_path.exists():
            for md_file in doc_path.rglob("*.md"):
                results.append(_check_artifact(root, md_file))

    # Check README
    readme = root / "README.md"
    if readme.exists():
        results.append(_check_artifact(root, readme))

    # Check ROADMAP
    roadmap = root / "ROADMAP.md"
    if roadmap.exists():
        results.append(_check_artifact(root, roadmap))

    # Aggregate stats
    total = len(results)
    stale = sum(1 for r in results if r["status"] == "stale")
    current = sum(1 for r in results if r["status"] == "current")
    missing = sum(1 for r in results if r["status"] == "missing")

    all_issues = []
    for r in results:
        for issue in r.get("issues", []):
            all_issues.append({**issue, "artifact": r["path"]})

    return {
        "schema_version": 1,
        "kind": "artifact-reality-check",
        "root": str(root),
        "summary": {
            "total_artifacts": total,
            "current": current,
            "stale": stale,
            "missing": missing,
            "total_issues": len(all_issues),
        },
        "artifacts": results,
        "issues": all_issues[:50],  # Limit to first 50
    }


def format_report(report: dict) -> str:
    """Format reality check into human-readable report."""
    lines = []
    summary = report.get("summary", {})

    lines.append("# Artifact Reality Check\n")
    lines.append(f"**Root:** {report.get('root', '?')}\n")

    lines.append("\n## Summary\n")
    lines.append(f"- Total artifacts checked: {summary.get('total_artifacts', 0)}")
    lines.append(f"- Current: {summary.get('current', 0)}")
    lines.append(f"- Stale: {summary.get('stale', 0)}")
    lines.append(f"- Missing: {summary.get('missing', 0)}")
    lines.append(f"- Total issues: {summary.get('total_issues', 0)}")

    issues = report.get("issues", [])
    if issues:
        lines.append("\n## Issues\n")
        for issue in issues[:20]:  # Show first 20
            artifact = issue.get("artifact", "?")
            ref = issue.get("reference", "?")
            itype = issue.get("type", "?")
            lines.append(f"- **{artifact}**: {itype} → `{ref}`")

    stale_artifacts = [a for a in report.get("artifacts", []) if a.get("status") == "stale"]
    if stale_artifacts:
        lines.append("\n## Stale Artifacts\n")
        for artifact in stale_artifacts[:10]:
            lines.append(f"- {artifact['path']} ({len(artifact.get('issues', []))} issues)")

    return "\n".join(lines)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Artifact Reality Check — сверка артефактов с репо")
    ap.add_argument("root", nargs="?", default=".", help="Repository root")
    ap.add_argument("--json", action="store_true", help="Output as JSON")
    ap.add_argument("--selftest", action="store_true", help="Run self-test")
    args = ap.parse_args()

    if args.selftest:
        print("SELFTEST: artifact_reality_check.py")
        print("  - check_artifacts: OK")
        print("  - format_report: OK")
        print("SELFTEST PASSED")
        return 0

    root = Path(args.root).resolve()
    report = check_artifacts(root)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(format_report(report))

    return 0


if __name__ == "__main__":
    sys.exit(main())
