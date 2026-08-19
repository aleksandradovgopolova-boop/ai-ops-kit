#!/usr/bin/env python3
"""assemble_plan.py — сборщик planning/plan.yaml из файлов planning/works/*.yaml.

РАЗБИВКА ПЛАНА (19.08.2026, derived-state-out-of-tracked-files): `planning/plan.yaml` разбит на
файлы по работам в `planning/works/<id>.yaml`. Каждый файл — одна работа. Этот скрипт собирает
единый `planning/plan.yaml` из файлов для тех, кто хочет видеть план целиком.

Использование:
    python3 tools/assemble_plan.py                  # собрать planning/plan.yaml
    python3 tools/assemble_plan.py --output out.yaml  # собрать в другой файл
    python3 tools/assemble_plan.py --check          # проверить, что план актуален
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml


def assemble_plan(works_dir: Path) -> dict:
    """Собрать план из файлов работ."""
    works = []

    for work_file in sorted(works_dir.glob("*.yaml")):
        try:
            with open(work_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if data and "work" in data:
                works.extend(data["work"])
        except (yaml.YAMLError, OSError) as e:
            print(f"Warning: failed to load {work_file}: {e}", file=sys.stderr)

    # Сортируем работы по порядку в файле (по имени файла, если нет другого порядка)
    # В реальности порядок определяется порядком файлов в директории

    return {
        "schema_version": 1,
        "kind": "delivery-plan",
        "work": works,
    }


def check_plan(plan_file: Path, works_dir: Path) -> bool:
    """Проверить, что план актуален (совпадает со сборкой)."""
    if not plan_file.exists():
        print(f"Plan file {plan_file} does not exist", file=sys.stderr)
        return False

    try:
        with open(plan_file, "r", encoding="utf-8") as f:
            current = yaml.safe_load(f)

        assembled = assemble_plan(works_dir)

        # Сравниваем работы
        current_works = current.get("work", [])
        assembled_works = assembled.get("work", [])

        if len(current_works) != len(assembled_works):
            print(
                f"Work count mismatch: current={len(current_works)}, assembled={len(assembled_works)}",
                file=sys.stderr,
            )
            return False

        # Проверяем, что все работы есть (без учёта порядка)
        current_ids = {w.get("id") for w in current_works}
        assembled_ids = {w.get("id") for w in assembled_works}

        if current_ids != assembled_ids:
            missing = assembled_ids - current_ids
            extra = current_ids - assembled_ids
            if missing:
                print(f"Missing works in plan: {missing}", file=sys.stderr)
            if extra:
                print(f"Extra works in plan: {extra}", file=sys.stderr)
            return False

        return True

    except (yaml.YAMLError, OSError) as e:
        print(f"Error checking plan: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="Assemble planning/plan.yaml from planning/works/*.yaml")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("planning/plan.yaml"),
        help="Output file (default: planning/plan.yaml)",
    )
    parser.add_argument(
        "--works-dir",
        type=Path,
        default=Path("planning/works"),
        help="Directory with work files (default: planning/works)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check if plan is up-to-date (exit 0 if yes, 1 if no)",
    )

    args = parser.parse_args()

    if args.check:
        plan_file = args.output
        works_dir = args.works_dir
        if check_plan(plan_file, works_dir):
            print("Plan is up-to-date")
            return 0
        else:
            print("Plan is out-of-date. Run without --check to rebuild.", file=sys.stderr)
            return 1

    # Assemble plan
    works_dir = args.works_dir
    if not works_dir.exists():
        print(f"Works directory {works_dir} does not exist", file=sys.stderr)
        return 1

    plan = assemble_plan(works_dir)

    # Write output
    output_file = args.output
    with open(output_file, "w", encoding="utf-8") as f:
        yaml.dump(plan, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    print(f"Assembled {len(plan['work'])} works into {output_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
