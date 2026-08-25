"""Lane A2: package-quality.yml содержит джобу security-scan.

Кит держит дочки на детерминированном сканере (ai_ops_kit/security/security_scan.py),
но свои диффы им не проверял. Джоба в CI закрывает этот пробел: сканер запускается
против диффа PR (--base origin/main) и краснеет на находках.

Тест проверяет:
1. Джоба security-scan существует в YAML.
2. Условие `if` ограничивает запуск только PR (не push в main).
3. Шаг вызывает security_scan.py с --base.
"""
from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW_PATH = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "package-quality.yml"


def test_security_scan_job_exists() -> None:
    """Джоба security-scan объявлена в package-quality.yml."""
    doc = yaml.safe_load(WORKFLOW_PATH.read_text())
    jobs = doc.get("jobs", {})
    assert "security-scan" in jobs, "джоба security-scan не найдена в package-quality.yml"


def test_security_scan_runs_only_on_pr() -> None:
    """Security-scan запускается только на PR, не на push в main."""
    doc = yaml.safe_load(WORKFLOW_PATH.read_text())
    job = doc["jobs"]["security-scan"]
    condition = job.get("if", "")
    # Условие должно проверять event_name == 'pull_request'
    assert "pull_request" in condition, f"security-scan должен запускаться только на PR, условие: {condition}"


def test_security_scan_calls_script_with_base() -> None:
    """Шаг вызывает security_scan.py с --base."""
    doc = yaml.safe_load(WORKFLOW_PATH.read_text())
    job = doc["jobs"]["security-scan"]
    steps = job.get("steps", [])

    # Ищем шаг, который вызывает security_scan.py
    found = False
    for step in steps:
        run_cmd = step.get("run", "")
        if "security_scan.py" in run_cmd and "--base" in run_cmd:
            found = True
            break

    assert found, "шаг с security_scan.py --base не найден в джобе security-scan"
