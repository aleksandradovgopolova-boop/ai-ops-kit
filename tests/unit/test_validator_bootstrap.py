"""Валидаторы стартуют без PYTHONPATH — то есть в child-репозитории и в чистом клоне (v3.31.0).

Десять модулей `ai_ops_kit/validation/*.py` делают `import _bootstrap` ради side effect: он кладёт корень
пакета в `sys.path`, откуда импортируется `ai_ops_kit`. При запуске скрипта `sys.path[0]` — это
каталог скрипта, то есть `ai_ops_kit/validation/`; `tools/_bootstrap.py` оттуда не виден. Работало только
там, где `tools/` уже лежал в путях: в CI — из-за PYTHONPATH в обоих workflow, у разработчика —
из-за editable-установки. В свежей установке `validate_ai_ops_child.py` падал с
ModuleNotFoundError, и `installer --selftest` это честно показывал.

Поэтому тест ОБЯЗАН чистить окружение: проверка, которую можно закрасить переменной среды,
проверяет среду, а не код. Ровно этот класс («работает локально / работает в CI») стоил репозиторию
трёх разборов за неделю.

Три обязательных теста на capability (AGENTS.md):
  * positive     — каждый такой валидатор стартует БЕЗ PYTHONPATH из чужого cwd;
  * fail-closed  — в копии репозитория без `ai_ops_kit/validation/_bootstrap.py` тот же запуск падает именно
                   с ModuleNotFoundError: проверка имеет зубы, а не подтверждает сама себя;
  * side-effect  — bootstrap РЕАЛЬНО кладёт корень в путь: `import ai_ops_kit` в том же процессе
                   проходит (иначе модуль импортируется, но задачу не решает).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import ambient

PKG = Path(__file__).resolve().parents[2]
VALIDATION = PKG / "ai_ops_kit" / "validation"
MISSING = "No module named '_bootstrap'"


def _needs_bootstrap(root: Path) -> list[Path]:
    """Валидаторы, импортирующие _bootstrap. Список не зашит: новый такой модуль подхватится сам."""
    return sorted(f for f in (root / "ai_ops_kit" / "validation").glob("*.py")
                  if f.name != "_bootstrap.py"
                  and "import _bootstrap" in f.read_text(encoding="utf-8"))


def _run(script: Path, cwd: Path):
    """Запуск без PYTHONPATH И БЕЗ ПОЯСА editable-установки (см. `tests/ambient`).

    19.08.2026: раньше здесь чистился только `PYTHONPATH`, и проба «удалить `_bootstrap.py` из
    копии» НЕ ДОХОДИЛА ДО ДЕФЕКТА: `import _bootstrap` разрешался через meta-path finder рабочего
    клона, запуск завершался кодом 0, и тест сообщал «удалили, а не сломалось». Проверка, которую
    можно закрасить чужим деревом, проверяет чужое дерево.
    """
    return ambient.run([script], cwd=cwd, base=Path(cwd).parent, timeout=180)


@pytest.mark.slow
def test_validators_start_without_pythonpath(tmp_path):
    """positive: ни один валидатор не падает на импорте _bootstrap без PYTHONPATH."""
    scripts = _needs_bootstrap(PKG)
    assert scripts, "ни один валидатор не импортирует _bootstrap — тест потерял предмет"

    broken = []
    for script in scripts:
        r = _run(script, tmp_path)          # чужой cwd: артефактов рядом нет, работа короткая
        if MISSING in r.stderr:
            broken.append(script.name)
    assert not broken, (
        f"валидаторы не стартуют без PYTHONPATH (в child-репозитории тоже): {broken}")


@pytest.mark.slow
def test_missing_bootstrap_is_caught(tmp_path):
    """fail-closed: без validation/_bootstrap.py тот же запуск падает — проверка не тавтология."""
    clone = tmp_path / "clone"
    for rel in ("VERSION", "ai_ops_kit"):
        src = PKG / rel
        dst = clone / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(src, dst)
    (clone / "ai_ops_kit" / "validation" / "_bootstrap.py").unlink()

    victim = clone / "ai_ops_kit" / "validation" / "validate_ai_ops_child.py"
    r = _run(victim, tmp_path)
    assert MISSING in r.stderr, (
        "удалили ai_ops_kit/validation/_bootstrap.py, а запуск не сломался — тест не проверяет то, "
        f"ради чего написан.\nstdout: {r.stdout[-500:]}\nstderr: {r.stderr[-500:]}")


@pytest.mark.slow
def test_bootstrap_puts_root_on_path(tmp_path):
    """side-effect: импорт _bootstrap делает импортируемой пакетную поверхность ai_ops_kit."""
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(VALIDATION)!r})\n"   # как при запуске validation/<script>.py
        "import _bootstrap  # noqa: F401\n"
        "import ai_ops_kit.gates.gate_policy as gp\n"
        "print('OK', bool(gp))\n",
        encoding="utf-8")

    r = ambient.run([probe], cwd=tmp_path, base=tmp_path, timeout=120)
    assert r.returncode == 0 and "OK True" in r.stdout, (
        f"_bootstrap импортировался, но корень в sys.path не положил.\nstderr: {r.stderr[-800:]}")
