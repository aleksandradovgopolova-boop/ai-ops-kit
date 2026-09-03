"""Общие фикстуры-хелперы для разрезанных тестов execution_pipeline (не собирается pytest)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT / "tools"))

from ai_ops_kit.engine import execution_pipeline


def _init_git(child_root):
    """Helper: init a git repo with one commit."""
    subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=child_root, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=child_root, capture_output=True)
    (child_root / "dummy.txt").write_text("init")
    subprocess.run(["git", "add", "."], cwd=child_root, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=child_root, capture_output=True)


def _init_python_repo(child_root):
    """Git-репо с python-профилем БЕЗ тулчейна (нет ruff/mypy/pytest, нет tests/).

    Все проверки -> not_applicable детерминированно, независимо от среды теста.
    Повторяет фикстуру монолита (test_execution_pipeline_selftest, строки 51-62).
    """
    subprocess.run(["git", "init", "-q"], cwd=child_root, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=child_root, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=child_root, capture_output=True)
    (child_root / "src").mkdir(exist_ok=True)
    (child_root / "pyproject.toml").write_text(
        "[tool.poetry]\nname='x'\n[tool.poetry.dependencies]\n", encoding="utf-8")
    (child_root / "f").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=child_root, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "i"], cwd=child_root, capture_output=True)


def _head_branch(child_root):
    """Имя текущей ветки — default-ветка после git init варьируется (master/main)."""
    return execution_pipeline._git(child_root, "rev-parse", "--abbrev-ref", "HEAD")[1].strip()


_QUICK_SIG = {"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]}
