"""Regression evidence гоняет команду тестов без оболочки (#1157).

Команда тестов из профиля — бинарь и аргументы; оболочка там была лишь поверхностью внедрения.
Команду, которую без оболочки так же не исполнить, кит не гонит «примерно так же»: прогона не было,
и это `unverifiable`, а не доказательство. Настоящий прогон списком (`python -m pytest -q`)
сторожат живые тесты `test_regression_evidence.py`.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from ai_ops_kit.gates import regression_evidence as re_

pytestmark = pytest.mark.unit

_FILES = ["calc.py", "test_calc.py"]


def _profile(cmd):
    return {"stacks": [{"commands": {"test": cmd}}]}


@pytest.mark.parametrize("cmd", ["pytest -q && echo ok", "npm test | tee out.txt",
                                 "pytest $ARGS", "cd sub && pytest"])
def test_shell_only_test_command_is_unverifiable(tmp_path, cmd):
    proof = re_.prove(tmp_path, "base", "head", _profile(cmd), _FILES)
    assert proof["status"] == "unverifiable"
    assert "оболочки" in proof["reason"]
    assert proof["checks"] == [], "прогона не было — проверок в отчёте быть не должно"


def test_shell_only_command_creates_no_worktree(tmp_path):
    """Отказ стоит ДО дерева на базовой ревизии: git здесь не вызывается вовсе."""
    proof = re_.prove(tmp_path, "base", "head", _profile("a | b"), _FILES)
    assert proof["status"] == "unverifiable"
    assert not list(tmp_path.iterdir()), "отказ оставил следы в корне"


def test_module_has_no_shell_true_call():
    tree = ast.parse(Path(re_.__file__).read_text(encoding="utf-8"))
    shell_true = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.keyword)
                  and n.arg == "shell" and getattr(n.value, "value", None) is True]
    assert shell_true == []
