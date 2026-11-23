"""#1558: настройка покрытия репозитория учитывает код, исполненный в дочернем процессе.

Без неё валидаторы и CLI, которые тесты запускают отдельным процессом, выглядели непокрытыми
(замер 18.11.2026: 349 функций с 0%, 115 из них в валидаторах), и CRAP завышал их долг.
Проверяется настоящая секция `[tool.coverage]` из pyproject.toml на маленьком корпусе.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PKG = Path(__file__).resolve().parents[2]


def coverage_section() -> str:
    run = tomllib.loads((PKG / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["coverage"]["run"]
    return "[tool.coverage.run]\n" + "".join(f"{k} = {json.dumps(v)}\n" for k, v in run.items())


def test_repository_config_patches_subprocesses():
    assert "subprocess" in tomllib.loads((PKG / "pyproject.toml").read_text())["tool"]["coverage"]["run"]["patch"]


@pytest.mark.parametrize("with_repo_config", [True, False])
def test_code_run_only_in_a_child_process_is_covered(tmp_path, with_repo_config):
    """Отрицательный случай — то же без настройки: так было до #1558, и тест это показывает."""
    pytest.importorskip("pytest_cov")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("def only_in_child():\n    value = 1\n    return value + 1\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_child.py").write_text(
        "import subprocess, sys, tempfile\nfrom pathlib import Path\n"
        "ROOT = Path(__file__).resolve().parents[1]\n"
        "def test_child():\n"
        "    with tempfile.TemporaryDirectory() as elsewhere:\n"
        "        code = f'import sys; sys.path.insert(0, {str(ROOT)!r}); import pkg; pkg.only_in_child()'\n"
        "        done = subprocess.run([sys.executable, '-c', code], cwd=elsewhere, capture_output=True, text=True)\n"
        "        assert done.returncode == 0 and done.stderr == '', done.stderr\n")
    (tmp_path / "pyproject.toml").write_text(coverage_section() if with_repo_config else "")
    env = {k: v for k, v in __import__("os").environ.items() if not k.startswith(("COV_CORE_", "COVERAGE_"))}
    result = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider",
                             "--cov=pkg", "--cov-report=json:cov.json"],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    executed = json.loads((tmp_path / "cov.json").read_text())["files"]["pkg/__init__.py"]["executed_lines"]
    assert (executed == [1, 2, 3]) is with_repo_config, executed
