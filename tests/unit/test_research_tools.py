"""Инструменты .research — последнее, что оставалось в чеклисте отдельными командами.

Они лежат вне tools/validation (исследовательский контур), но их селфтесты — такие же проверки,
и место им в pytest: там у падения есть имя.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2]
TOOLS = ["verify_quotes.py", "freshness_sweep.py", "ev_scaffold.py"]


@pytest.mark.slow
@pytest.mark.parametrize("name", TOOLS)
def test_research_tool_selftest(name):
    path = PKG / ".research" / "tools" / name
    if not path.is_file():
        pytest.skip(f"{name} отсутствует — исследовательский контур не установлен")
    env = dict(os.environ); env["PYTHONPATH"] = f"{PKG}/tools:{PKG}/validation"
    r = subprocess.run([sys.executable, str(path), "--selftest"], cwd=PKG, env=env,
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, (r.stdout + r.stderr)[-700:]


@pytest.mark.unit
@pytest.mark.parametrize("name", TOOLS)
def test_research_tool_exists(name):
    """Команда, ссылающаяся на исчезнувший инструмент, — мёртвая запись в контуре."""
    assert (PKG / ".research" / "tools" / name).is_file(), f"{name} не найден"
