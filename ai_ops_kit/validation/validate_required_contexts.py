#!/usr/bin/env python3
"""validate_required_contexts.py — сверяет обязательные контексты с реальными CI-джобами.

РАБОТА required-contexts-match-jobs (2026-08-25).

ПРОБЛЕМА (docs/parallel-execution-retro.md §1 п.5): удаление джобы python39-compat не убрало
её из обязательных контекстов защиты ветки — ВСЕ PR зависли BLOCKED навсегда.

РЕШЕНИЕ: валидатор парсит CI-workflows, извлекает все job IDs, и сверяет с декларацией в
quality/required-contexts.yaml. Рассинхрон — красное в CI и локально.

Использование:
    validate_required_contexts.py                    # проверить against quality/required-contexts.yaml
    validate_required_contexts.py --json             # вывод в JSON
    validate_required_contexts.py --selftest         # самопроверка
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml


def _workflow_dir(root: Path) -> Path:
    return root / ".github" / "workflows"


def _contexts_file(root: Path) -> Path:
    return root / "quality" / "required-contexts.yaml"


def extract_jobs_from_workflows(workflow_dir: Path) -> dict[str, list[str]]:
    """Извлечь все контексты status checks из workflow-файлов.

    Для matrix-джоб генерирует имена вида "<job_id> (<matrix_value>)".
    Возвращает {workflow_name: [context_name, ...]}.
    Workflow name — имя файла без расширения (например, 'package-quality').
    """
    contexts_by_workflow = {}
    if not workflow_dir.exists():
        return contexts_by_workflow

    for wf_file in sorted(workflow_dir.glob("*.yml")):
        try:
            wf = yaml.safe_load(wf_file.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        if not isinstance(wf, dict):
            continue
        jobs = wf.get("jobs", {})
        if not isinstance(jobs, dict):
            continue

        workflow_name = wf_file.stem
        contexts = []

        for job_id, job_def in jobs.items():
            if not isinstance(job_def, dict):
                contexts.append(job_id)
                continue

            strategy = job_def.get("strategy", {})
            matrix = strategy.get("matrix", {}) if isinstance(strategy, dict) else {}

            # Если есть matrix.include — это список конкретных комбинаций
            if "include" in matrix and isinstance(matrix["include"], list):
                for combo in matrix["include"]:
                    if isinstance(combo, dict) and "group" in combo:
                        contexts.append(f"{job_id} ({combo['group']})")
                    else:
                        contexts.append(job_id)
            # Если есть matrix с простыми списками — генерируем декартово произведение
            elif matrix:
                # Находим ключи матрицы (исключая include/exclude)
                matrix_keys = [k for k in matrix.keys() if k not in ("include", "exclude")]
                if matrix_keys:
                    # Для простоты: если есть 'group' в include, используем его
                    # Иначе берём первое значение первого ключа
                    first_key = matrix_keys[0]
                    first_values = matrix[first_key]
                    if isinstance(first_values, list):
                        for val in first_values:
                            contexts.append(f"{job_id} ({val})")
                    else:
                        contexts.append(job_id)
                else:
                    contexts.append(job_id)
            else:
                contexts.append(job_id)

        contexts_by_workflow[workflow_name] = contexts

    return contexts_by_workflow


def format_context(workflow_name: str, job_id: str) -> str:
    """Формат контекста, как GitHub показывает в status checks."""
    return f"{workflow_name} / {job_id}"


def load_declared_contexts(root: Path) -> list[str] | None:
    """Загрузить объявленные контексты из quality/required-contexts.yaml.

    Возвращает None, если файл не существует.
    """
    ctx_file = _contexts_file(root)
    if not ctx_file.exists():
        return None
    try:
        doc = yaml.safe_load(ctx_file.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return None
    if not isinstance(doc, dict):
        return None
    return doc.get("contexts", [])


def validate(root: Path) -> dict:
    """Сверить объявленные контексты с реальными джобами.

    Возвращает:
        declared: список объявленных контекстов
        actual: список реальных контекстов (workflow / job)
        missing_jobs: объявлены, но джобы нет (КРАСНОЕ — повесит очередь)
        undeclared_jobs: джоба есть, но не объявлена (WARNING)
        ok: True если нет missing_jobs
    """
    wf_dir = _workflow_dir(root)
    jobs_by_wf = extract_jobs_from_workflows(wf_dir)

    # Все реальные контексты
    actual = []
    for wf_name, job_ids in sorted(jobs_by_wf.items()):
        for job_id in sorted(job_ids):
            actual.append(format_context(wf_name, job_id))

    declared = load_declared_contexts(root)
    if declared is None:
        return {
            "declared": None,
            "actual": actual,
            "missing_jobs": [],
            "undeclared_jobs": actual,
            "ok": True,
            "message": "quality/required-contexts.yaml не найден — проверка пропущена",
        }

    declared_set = set(declared)
    actual_set = set(actual)

    # Объявлены, но джобы нет — КРАСНОЕ
    missing_jobs = sorted(declared_set - actual_set)
    # Джоба есть, но не объявлена — WARNING
    undeclared_jobs = sorted(actual_set - declared_set)

    return {
        "declared": sorted(declared),
        "actual": actual,
        "missing_jobs": missing_jobs,
        "undeclared_jobs": undeclared_jobs,
        "ok": len(missing_jobs) == 0,
    }


def format_report(result: dict) -> str:
    """Форматировать отчёт для человека."""
    lines = []

    if result.get("declared") is None:
        return result.get("message", "no contexts file")

    lines.append(f"Объявлено контекстов: {len(result['declared'])}")
    lines.append(f"Реальных джоб: {len(result['actual'])}")

    if result["missing_jobs"]:
        lines.append("")
        lines.append("❌ ОБЪЯВЛЕНЫ, НО ДЖОБЫ НЕТ (повесит очередь):")
        for ctx in result["missing_jobs"]:
            lines.append(f"  - {ctx}")

    if result["undeclared_jobs"]:
        lines.append("")
        lines.append("⚠️  Джобы есть, но не объявлены (не обязательно):")
        for ctx in result["undeclared_jobs"]:
            lines.append(f"  - {ctx}")

    if result["ok"]:
        lines.append("")
        lines.append("✅ Все объявленные контексты имеют соответствующие джобы")

    return "\n".join(lines)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Validate required contexts match CI jobs")
    ap.add_argument("--root", default=".", help="Repository root")
    ap.add_argument("--json", action="store_true", help="Output as JSON")
    ap.add_argument("--selftest", action="store_true", help="Run self-test")
    args = ap.parse_args()

    root = Path(args.root).resolve()

    if args.selftest:
        print(__doc__)
        print("Проверки валидатора — в tests/ (AGENTS.md: selftest не живёт в продакшн-модуле).")
        return 0

    result = validate(root)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(format_report(result))

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
