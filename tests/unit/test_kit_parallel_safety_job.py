"""parallel-safety-runs-in-ci: pr-smoke.yml содержит джобу параллельной безопасности.

Кит держит дочки на проверке по ДИФФУ (validate_parallel_safety.py), но своим PR её не гонял.
Джоба в pr-smoke закрывает пробел: скрипт запускается против диффа PR (--base origin/main --strict)
и краснеет, если PR смешал код с координационным файлом.

Проверяет:
1. Джоба parallel-safety существует в pr-smoke.yml.
2. Условие `if` ограничивает запуск только PR (джобе нужен PR-дифф против origin/main).
3. Шаг вызывает validate_parallel_safety.py с --base и --strict (уже блокирующий, но джоба пока
   НЕ обязательный контекст — перевод в required решает владелец после обкатки, dp-002).
4. Прямой вызов скрипта не нарушает pytest-only инвариант (whitelist в validate_agents_checklist).
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT))

WORKFLOW_PATH = PKG_ROOT / ".github" / "workflows" / "pr-smoke.yml"

from ai_ops_kit.validation import validate_agents_checklist as checklist  # noqa: E402


def test_parallel_safety_job_exists() -> None:
    """Джоба parallel-safety объявлена в pr-smoke.yml."""
    doc = yaml.safe_load(WORKFLOW_PATH.read_text())
    assert "parallel-safety" in doc.get("jobs", {}), "джоба parallel-safety не найдена в pr-smoke.yml"


def test_parallel_safety_runs_only_on_pr() -> None:
    """Только на PR: джобе нужен PR-дифф против origin/main, которого на других событиях нет."""
    doc = yaml.safe_load(WORKFLOW_PATH.read_text())
    condition = doc["jobs"]["parallel-safety"].get("if", "")
    assert "pull_request" in condition, f"parallel-safety должна идти только на PR, условие: {condition}"


def test_parallel_safety_calls_script_with_base_and_strict() -> None:
    """Шаг вызывает validate_parallel_safety.py с --base и --strict (краснеет на смешанном PR)."""
    doc = yaml.safe_load(WORKFLOW_PATH.read_text())
    steps = doc["jobs"]["parallel-safety"].get("steps", [])
    found = any("validate_parallel_safety.py" in s.get("run", "")
                and "--base" in s.get("run", "")
                and "--strict" in s.get("run", "")
                for s in steps)
    assert found, "шаг с validate_parallel_safety.py --base … --strict не найден в parallel-safety"


def test_direct_script_call_respects_pytest_only_invariant() -> None:
    """Прямой вызов скрипта в workflow разрешён whitelist'ом — контур сам себя не краснит."""
    assert checklist.offending_commands() == [], (
        "прямой вызов validate_parallel_safety.py должен быть в ALLOWED "
        "(validate_agents_checklist), иначе pytest-only инвариант краснит CI кита")
