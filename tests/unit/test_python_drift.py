"""Расхождение версии Python local↔CI ловится ДО пуша и НЕ блокирует цикл (issue #1378).

Локальный цикл идёт на интерпретаторе человека (машина владельца — 3.14), блокирующий CI считает
пол `requires-python` (3.12). Зелёное локально на 3.14 не гарантирует зелёное на 3.12 — лишний круг
local-green → CI-red. Проверка предупреждает об этом ДО пуша, называя пол, и остаётся advisory:
правило владельца первого класса — разница версий НЕ должна блокировать разработку.

Тесты подают версию и пол ЯВНО (шов `local`/`floor`): проверка меряет разбор расхождения, а не тот
Python, которым запущен сам тест.

Три обязательных теста на capability (AGENTS.md):
  * positive     — minor локального != пол CI -> предупреждение с НАЗВАННЫМ полом;
  * fail-closed  — minor совпал с полом -> ни слова (иначе проверка шумит всегда и её заглушат);
  * side-effect  — пол читается из pyproject (один источник), а код возврата ВСЕГДА 0 (не блокирует).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG))
from ai_ops_kit.devtools import python_drift as pd  # noqa: E402

pytestmark = pytest.mark.unit


# ── positive ──────────────────────────────────────────────────────────────────────────────────

def test_mismatch_warns_and_names_the_floor():
    """local 3.14, пол 3.12 -> статус drift, и предупреждение называет ИМЕННО пол (3.12) и local."""
    rep = pd.assess(local=(3, 14), floor=(3, 12))
    assert rep["status"] == "drift"
    assert rep["newer"] is True
    line = pd.warning_line(rep)
    assert "3.14" in line and "3.12" in line
    # Не просто «версии разные», а что делать: прогнать на полу CI.
    assert "python3.12" in line
    assert "CI" in line


def test_older_local_than_floor_also_drifts():
    """Расхождение — в обе стороны: local 3.12, пол 3.13 тоже drift (newer=False)."""
    rep = pd.assess(local=(3, 12), floor=(3, 13))
    assert rep["status"] == "drift"
    assert rep["newer"] is False
    assert "старше" in pd.warning_line(rep)


# ── fail-closed ───────────────────────────────────────────────────────────────────────────────

def test_aligned_minor_is_silent():
    """minor совпал с полом -> aligned и ПУСТАЯ строка: проверка, кричащая всегда, будет заглушена."""
    rep = pd.assess(local=(3, 12), floor=(3, 12))
    assert rep["status"] == "aligned"
    assert pd.warning_line(rep) == ""


def test_patch_difference_is_not_drift():
    """Разница только в patch (3.12.x) к классу «3.14-only зелёный» не относится и не предупреждается.
    local_version отбрасывает patch -> (3, 12) против пола (3, 12) = aligned."""
    rep = pd.assess(local=pd.local_version((3, 12, 7)), floor=(3, 12))
    assert rep["status"] == "aligned"


# ── side-effect ───────────────────────────────────────────────────────────────────────────────

def test_floor_comes_from_pyproject_single_source():
    """Пол не зашит здесь второй раз: assess без аргумента floor читает requires-python из pyproject
    (через declared_floor) — меняется декларация, меняется и предупреждение."""
    from ai_ops_kit.validation.validate_python_compat import declared_floor
    rep = pd.assess(local=(3, 14))
    assert rep["ci_floor"] == list(declared_floor())


def test_cli_never_blocks_the_cycle():
    """Код возврата ВСЕГДА 0, даже при расхождении: advisory не вправе ронять локальный цикл.

    Запускаем настоящим интерпретатором как модуль — так же, как это делают check-full/check-fast.
    На этой машине (local 3.14, пол 3.12) предупреждение реально печатается в stderr, но exit 0."""
    r = subprocess.run([sys.executable, "-m", "ai_ops_kit.devtools.python_drift"],
                       cwd=PKG, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, (r.stdout + r.stderr)
    # --json даёт машиночитаемый отчёт тем же нулевым кодом.
    rj = subprocess.run([sys.executable, "-m", "ai_ops_kit.devtools.python_drift", "--json"],
                        cwd=PKG, capture_output=True, text=True, timeout=30)
    assert rj.returncode == 0
    assert '"kind": "PythonDrift"' in rj.stdout
