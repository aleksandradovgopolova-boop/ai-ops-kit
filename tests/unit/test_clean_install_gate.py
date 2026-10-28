"""Гейт чистой установки не пропускает сломанную команду (#1397).

Берём РЕАЛЬНУЮ функцию `check_produces_output` из `scripts/check-clean-install.sh` (а не её копию)
и проверяем: команда с ненулевым кодом или с Traceback в выводе ПАДАЕТ, а не получает OK. Раньше
`out="$(... || true)"` глотал код возврата, и команда с Traceback и rc=2 проходила как OK.
"""
from __future__ import annotations

import pathlib
import subprocess

import pytest

pytestmark = pytest.mark.unit

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "check-clean-install.sh"


def _func_source() -> str:
    """Текст самой функции из скрипта — тестируем реальный код, не его пересказ."""
    out = subprocess.run(
        ["sed", "-n", "/^check_produces_output()/,/^}/p", str(SCRIPT)],
        capture_output=True, text=True, check=True).stdout
    assert "check_produces_output()" in out, "функция не извлеклась из скрипта"
    return out


def _call(cmd: str) -> subprocess.CompletedProcess:
    script = (
        "set -uo pipefail\n"
        'fail() { echo "FAIL:$*" >&2; exit 1; }\n'
        f"{_func_source()}\n"
        f'check_produces_output "lbl" {cmd}\n'
    )
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True)


def test_good_command_passes():
    r = _call("echo hello")
    assert r.returncode == 0 and "OK  lbl" in r.stdout


def test_nonzero_exit_fails():
    r = _call("""python3 -c 'print("boom"); import sys; sys.exit(2)'""")
    assert r.returncode != 0 and "FAIL" in r.stderr


def test_traceback_in_output_fails_even_with_zero_exit():
    r = _call("""python3 -c 'print("Traceback (most recent call last)")'""")
    assert r.returncode != 0 and "FAIL" in r.stderr


def test_empty_output_fails():
    r = _call("true")
    assert r.returncode != 0 and "FAIL" in r.stderr
