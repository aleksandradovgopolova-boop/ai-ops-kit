"""lane-ships-small-prs: pr-smoke.yml содержит ADVISORY-джобу размера PR.

Повод замерен (docs/parallel-execution-retro.md §1.7): лента сложила всю фазу в один PR на +2589
строк, и долг лёг на координатора. Durable-fix — проверка размера PR. Джоба в pr-smoke запускает её
против диффа PR (--base origin/main) и ПЕЧАТАЕТ отчёт, не блокируя: обкатка non-blocking (dp-002),
как начинала parallel-safety.

Проверяет:
1. Джоба pr-size существует в pr-smoke.yml.
2. Условие `if` ограничивает запуск только PR (в merge_group диффа PR нет — капкан статусов).
3. Шаг вызывает validate_pr_size.py с --base, но БЕЗ --strict (advisory на время обкатки).
4. Прямой вызов скрипта не нарушает pytest-only инвариант (whitelist в validate_agents_checklist).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT))

WORKFLOW_PATH = PKG_ROOT / ".github" / "workflows" / "pr-smoke.yml"

from ai_ops_kit.validation import validate_agents_checklist as checklist  # noqa: E402

pytestmark = pytest.mark.unit


def _steps():
    doc = yaml.safe_load(WORKFLOW_PATH.read_text())
    return doc, doc.get("jobs", {}).get("pr-size", {}).get("steps", [])


def test_pr_size_job_exists() -> None:
    """Джоба pr-size объявлена в pr-smoke.yml."""
    doc, _ = _steps()
    assert "pr-size" in doc.get("jobs", {}), "джоба pr-size не найдена в pr-smoke.yml"


def test_pr_size_runs_only_on_pr() -> None:
    """Только на PR: в merge_group нет PR-диффа, а обязательный пропуск повесил бы очередь."""
    doc, _ = _steps()
    condition = doc["jobs"]["pr-size"].get("if", "")
    assert "pull_request" in condition, f"pr-size должна идти только на PR, условие: {condition}"


def test_pr_size_is_advisory_calls_script_with_base_without_strict() -> None:
    """Шаг зовёт validate_pr_size.py с --base, но БЕЗ --strict — advisory на время обкатки."""
    _, steps = _steps()
    runs = [s.get("run", "") for s in steps if "validate_pr_size.py" in s.get("run", "")]
    assert runs, "шаг с validate_pr_size.py --base не найден в pr-size"
    assert all("--base" in r for r in runs), "вызов без --base — проверять нечего"
    assert all("--strict" not in r for r in runs), (
        "pr-size обязана быть ADVISORY (без --strict) на время обкатки — как начинала parallel-safety")


def test_direct_script_call_respects_pytest_only_invariant() -> None:
    """Прямой вызов скрипта в workflow разрешён whitelist'ом — контур сам себя не краснит."""
    assert checklist.offending_commands() == [], (
        "прямой вызов validate_pr_size.py должен быть в ALLOWED "
        "(validate_agents_checklist), иначе pytest-only инвариант краснит CI кита")
