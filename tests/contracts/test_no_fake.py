"""Гранулярные тесты no_fake контракта (мигрировано из test_no_fake_selftest.py).

Модуль не объявляет пройденной проверки, которой не делал.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2] / "ai_ops_kit"

# Утверждение об успехе: «пройдено» или «имя: OK». Регистр не важен — ловим смысл, а не написание.
CLAIMS_SUCCESS = re.compile(r"\bPASSED\b|:\s*OK\b|\bУСПЕШНО\b|\bПРОЙДЕН", re.IGNORECASE)

# Вызовы, которые проверкой не являются: печать и сборка парсера аргументов.
NOT_A_CHECK = {"print", "ArgumentParser", "add_argument", "parse_args", "exit", "format"}


def _selftest_blocks(tree: ast.AST):
    """Ветки `if <что-то>.selftest:` в модуле."""
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and "selftest" in ast.dump(node.test):
            yield node


def _claims(block: ast.If) -> list[str]:
    """Строковые литералы ветки, утверждающие успех."""
    out = []
    for n in ast.walk(block):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and CLAIMS_SUCCESS.search(n.value):
            out.append(n.value.strip())
    return out


def _real_calls(block: ast.If) -> int:
    """Сколько вызовов в ветке похожи на настоящую проверку."""
    n_calls = 0
    for n in ast.walk(block):
        if isinstance(n, ast.Call):
            name = getattr(n.func, "id", None) or getattr(n.func, "attr", None)
            if name and name not in NOT_A_CHECK:
                n_calls += 1
    return n_calls


def _modules():
    return sorted(p for p in PKG.rglob("*.py") if "__pycache__" not in p.parts)


@pytest.mark.contract
def test_no_module_claims_a_selftest_it_did_not_run():
    offenders = []
    for path in _modules():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as e:
            offenders.append(f"{path.name}: не разбирается ({e})")
            continue
        for block in _selftest_blocks(tree):
            claims = _claims(block)
            if claims and _real_calls(block) == 0:
                offenders.append(
                    f"{path.relative_to(PKG.parent)}:{block.lineno} — утверждает успех "
                    f"({claims[0]!r}), не вызвав ни одной проверяемой функции"
                )
    assert not offenders, (
        "селфтест объявляет пройденную проверку, которой не было — код 0 и вид успеха "
        "при нуле проверок:\n  " + "\n  ".join(offenders)
    )


@pytest.mark.contract
def test_the_guard_would_catch_the_defect_it_was_written_for():
    """Охрана обязана краснеть на образце дефекта — иначе она сама «объявлена и не исполняется»."""
    fake = ast.parse(
        "def main():\n"
        "    if args.selftest:\n"
        "        print('SELFTEST: delivery_size.py')\n"
        "        print('  - measure_delivery_size: OK')\n"
        "        print('SELFTEST ' + 'PASSED')\n"
        "        return 0\n"
    )
    blocks = list(_selftest_blocks(fake))
    assert blocks, "образец дефекта перестал распознаваться как ветка selftest"
    assert _claims(blocks[0]), "утверждение об успехе не распознано — охрана ослепла"
    assert _real_calls(blocks[0]) == 0, "печать засчитана за проверку"

    honest = ast.parse(
        "def main():\n"
        "    if args.selftest:\n"
        "        print(__doc__)\n"
        "        print('Проверки модуля — в tests/unit/.')\n"
        "        return 0\n"
    )
    hb = list(_selftest_blocks(honest))[0]
    assert not _claims(hb), "честная форма ошибочно считается утверждением об успехе"
