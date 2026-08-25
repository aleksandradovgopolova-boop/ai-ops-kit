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
_TOOLS_DIR = PKG / ".research" / "tools"


def _run_selftest(path):
    """Run a research tool's --selftest as a subprocess (as it is invoked in prod)."""
    env = dict(os.environ); env.pop("PYTHONPATH", None)   # v3.31: окружение пользователя, без пояса
    return subprocess.run([sys.executable, str(path), "--selftest"], cwd=PKG, env=env,
                          capture_output=True, text=True, timeout=300)


@pytest.mark.slow
@pytest.mark.parametrize("name", TOOLS)
def test_research_tool_selftest(name):
    path = PKG / ".research" / "tools" / name
    if not path.is_file():
        pytest.skip(f"{name} отсутствует — исследовательский контур не установлен")
    r = _run_selftest(path)
    assert r.returncode == 0, (r.stdout + r.stderr)[-700:]


@pytest.mark.slow
@pytest.mark.parametrize("name", TOOLS)
def test_research_tool_selftest_prints_something(name):
    """positive: селфтест печатает непустой вывод — не «прошёл на пустоте»."""
    path = PKG / ".research" / "tools" / name
    if not path.is_file():
        pytest.skip(f"{name} отсутствует — исследовательский контур не установлен")
    r = _run_selftest(path)
    assert (r.stdout + r.stderr).strip(), f"{name} --selftest ничего не напечатал"


@pytest.mark.unit
def test_missing_research_tool_selftest_fails_closed():
    """fail-closed: запуск несуществующего инструмента с --selftest даёт rc != 0."""
    ghost = _TOOLS_DIR / "__нет_такого_инструмента__.py"
    assert not ghost.exists()
    r = subprocess.run([sys.executable, str(ghost), "--selftest"], cwd=PKG,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode != 0, "запуск несуществующего инструмента дал rc=0"


@pytest.mark.slow
def test_research_selftests_do_not_touch_research_data():
    """side-effect: прогон селфтестов не меняет артефакты .research (mtime неизменны)."""
    data_dirs = [PKG / ".research" / d for d in ("evidence", "requests", "decisions")]
    before = {}
    for d in data_dirs:
        if d.is_dir():
            before[d] = {p.name: p.stat().st_mtime_ns for p in d.iterdir() if p.is_file()}

    for name in TOOLS:
        path = _TOOLS_DIR / name
        if path.is_file():
            _run_selftest(path)

    for d, snap in before.items():
        now = {p.name: p.stat().st_mtime_ns for p in d.iterdir() if p.is_file()}
        assert now == snap, f"селфтесты изменили артефакты разведки в {d.name}"


@pytest.mark.unit
@pytest.mark.parametrize("name", TOOLS)
def test_research_tool_exists(name):
    """Команда, ссылающаяся на исчезнувший инструмент, — мёртвая запись в контуре."""
    assert (PKG / ".research" / "tools" / name).is_file(), f"{name} не найден"
