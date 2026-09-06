"""Быстрая локальная проверка зеркалит быстрые БЛОКИРУЮЩИЕ ворота CI — красное ловится до пуша.

Работа `local-check-mirrors-ci`, цель `checks-that-run`, находка docs/parallel-execution-retro.md.

ЗАМЕР. `scripts/check-full.sh` уже держали тесты (`test_evidence_scope.py`): он берёт ИМЕННО тот
интерпретатор, которым работает запускающий, и отказывает названно, если pytest в нём нет.
`scripts/check-fast.sh` — точка обратной связи ВО ВРЕМЯ работы — этому контракту не подчинялась:
она звала голый `python3` и падала `No module named pytest` на машине владельца, и не гоняла линтер,
хотя джоба `lint` в CI блокирующая. То есть быстрый цикл давал зелёное, которого в CI не было.

Три обязательных теста на capability (AGENTS.md):
  * positive     — на чистом дереве check-fast доходит до pytest ИМЕННО объявленным интерпретатором;
  * fail-closed  — интерпретатор без pytest -> названный отказ (код 2), а не трассировка модуля;
                   и провал линтера ОСТАНАВЛИВАЕТ до pytest, а не всплывает раундом CI после;
  * side-effect  — линтер РЕАЛЬНО вызывается (ворота `lint` зеркалятся, а не только упомянуты).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2]
SCRIPT = PKG / "scripts" / "check-fast.sh"

pytestmark = [pytest.mark.unit, pytest.mark.slow]  # #465: мета-тест (гоняет pytest/ruff подпроцессом) — в slow, не держит fast-стену


def _logging_python(tmp_path):
    """Обёртка вокруг настоящего интерпретатора, записывающая каждый свой запуск."""
    log = tmp_path / "py-calls.log"
    w = tmp_path / "python-logging"
    w.write_text("#!/usr/bin/env bash\n"
                 f'echo "$@" >> {log}\n'
                 f'exec {sys.executable} "$@"\n', encoding="utf-8")
    w.chmod(0o755)
    return w, log


def _fake_ruff(tmp_path, exit_code):
    """Каталог с поддельным `ruff`, который логирует вызов и выходит заданным кодом; кладётся в PATH
    первым, чтобы `command -v ruff` нашёл именно его."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    log = tmp_path / "ruff-calls.log"
    (bindir / "ruff").write_text("#!/usr/bin/env bash\n"
                                 f'echo "$@" >> {log}\n'
                                 f"exit {exit_code}\n", encoding="utf-8")
    (bindir / "ruff").chmod(0o755)
    return bindir, log


# ── positive ────────────────────────────────────────────────────────────────────────────────────

def test_pytest_runs_on_the_announced_interpreter(tmp_path):
    """check-fast доходит до pytest тем же интерпретатором, что назван, — не голым `python3`."""
    w, log = _logging_python(tmp_path)
    r = subprocess.run(["bash", str(SCRIPT), "--collect-only", "-q"], cwd=str(PKG),
                       capture_output=True, text=True, timeout=300,
                       env={**os.environ, "PYTHON": str(w)})
    assert r.returncode == 0, (r.stdout + r.stderr)[-800:]
    calls = log.read_text(encoding="utf-8") if log.is_file() else ""
    assert "-m pytest" in calls, (
        "быстрый прогон идёт не объявленным интерпретатором:\n" + calls)


def test_it_runs_the_fast_not_slow_set(tmp_path):
    """Зеркалит группу CI `fast`: тот же отбор `-m "not slow"`, а не иной набор."""
    w, log = _logging_python(tmp_path)
    subprocess.run(["bash", str(SCRIPT), "--collect-only", "-q"], cwd=str(PKG),
                   capture_output=True, text=True, timeout=300,
                   env={**os.environ, "PYTHON": str(w)})
    calls = log.read_text(encoding="utf-8") if log.is_file() else ""
    assert "not slow" in calls, calls


# ── fail-closed ───────────────────────────────────────────────────────────────────────────────

def test_refuses_an_interpreter_without_pytest(tmp_path):
    """Интерпретатор без pytest -> названный отказ (код 2), а не `No module named pytest`."""
    fake = tmp_path / "python-without-pytest"
    fake.write_text("#!/usr/bin/env bash\n"
                    'if [ "$1" = "-c" ] && [[ "$2" == *"import pytest"* ]]; then exit 1; fi\n'
                    f'exec {sys.executable} "$@"\n', encoding="utf-8")
    fake.chmod(0o755)
    r = subprocess.run(["bash", str(SCRIPT), "--collect-only", "-q"], cwd=str(PKG),
                       capture_output=True, text=True, timeout=120,
                       env={**os.environ, "PYTHON": str(fake)})
    assert r.returncode == 2, (r.returncode, (r.stdout + r.stderr)[-600:])
    assert "pytest в нём нет" in (r.stdout + r.stderr), (r.stdout + r.stderr)[-600:]


def test_a_lint_failure_stops_before_pytest(tmp_path):
    """Провал линтера ОСТАНАВЛИВАЕТ быстрый прогон до тестов — красное не уезжает в CI-раунд."""
    w, pylog = _logging_python(tmp_path)
    bindir, _ = _fake_ruff(tmp_path, exit_code=1)
    r = subprocess.run(["bash", str(SCRIPT), "--collect-only", "-q"], cwd=str(PKG),
                       capture_output=True, text=True, timeout=120,
                       env={**os.environ, "PYTHON": str(w),
                            "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"})
    assert r.returncode != 0, "линтер упал, а быстрый прогон не остановился"
    calls = pylog.read_text(encoding="utf-8") if pylog.is_file() else ""
    assert "-m pytest" not in calls, (
        "линтер упал, но pytest всё равно запустился — ворота линтера не блокируют:\n" + calls)


# ── side-effect ───────────────────────────────────────────────────────────────────────────────

def test_the_linter_is_actually_invoked(tmp_path):
    """Джоба `lint` CI зеркалится РЕАЛЬНЫМ вызовом ruff, а не одним упоминанием в комментарии."""
    w, _ = _logging_python(tmp_path)
    bindir, ruff_log = _fake_ruff(tmp_path, exit_code=0)
    r = subprocess.run(["bash", str(SCRIPT), "--collect-only", "-q"], cwd=str(PKG),
                       capture_output=True, text=True, timeout=300,
                       env={**os.environ, "PYTHON": str(w),
                            "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"})
    assert r.returncode == 0, (r.stdout + r.stderr)[-800:]
    assert ruff_log.is_file() and "check" in ruff_log.read_text(encoding="utf-8"), (
        "check-fast не вызвал ruff — ворота линтера не зеркалятся")
