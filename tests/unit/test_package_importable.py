"""`ai_ops_kit` — настоящий пакет: импортируется, когда на пути ТОЛЬКО корень (v3.33.0).

До перевода импортов код пакета обращался к соседям по плоским именам (`import tool_broker`) и к
`_bootstrap` в `tools/`. Работало это лишь там, где `tools/` уже лежал на `sys.path` — то есть при
входе через плоский алиас. `import ai_ops_kit.gates.preflight` с одним корнем на пути падал с
`ModuleNotFoundError: No module named '_bootstrap'`, хотя пакет собирается в дистрибутив
(`pyproject.toml`) и после `pip install` пользователь получил бы ровно это.

Проверка ставит `sys.path` в РОВНО [корень] в отдельном процессе: ни `tools/`, ни `validation/`,
ни cwd, ни PYTHONPATH. Иначе она проверяла бы окружение теста, а не пакет.

Три обязательных теста на capability (AGENTS.md):
  * positive     — каждый модуль пакета импортируется с одним корнем на пути;
  * fail-closed  — модуль с плоским импортом ловится этой же пробой (иначе проба бесполезна);
  * side-effect  — плоских внутренних импортов в пакете не осталось: связи выражены пакетными
                   именами, и граф слоёв строится по тому же, что исполняет интерпретатор.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2]
SURFACE = PKG / "ai_ops_kit"

PROBE = textwrap.dedent("""
    import sys, importlib, json
    root = sys.argv[1]
    # Из путей выбрасывается ВСЁ, что лежит внутри репозитория (tools/, validation/, следы
    # editable-установки), и пустая строка (cwd). Остаётся стандартная библиотека, site-packages
    # и один корень — то, что видит пользователь после `pip install`.
    sys.path[:] = [p for p in sys.path if p and not p.startswith(root)] + [root]
    failed = {}
    for name in json.loads(sys.argv[2]):
        try:
            importlib.import_module(name)
        except Exception as exc:
            failed[name] = f"{type(exc).__name__}: {exc}"
    print(json.dumps(failed))
""")


def _modules():
    out = []
    for d in sorted(SURFACE.iterdir()):
        if not d.is_dir() or d.name == "__pycache__":
            continue
        for f in sorted(d.glob("*.py")):
            if f.name != "__init__.py":
                out.append(f"ai_ops_kit.{d.name}.{f.stem}")
    return out


def _import_with_root_only(modules, root=PKG):
    import json
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    r = subprocess.run([sys.executable, "-c", PROBE, str(root), json.dumps(modules)],
                       capture_output=True, text=True, timeout=600, env=env, cwd=str(root.parent))
    assert r.returncode == 0, f"проба не отработала:\n{r.stdout[-1000:]}\n{r.stderr[-1000:]}"
    return json.loads(r.stdout.strip().splitlines()[-1])


@pytest.mark.slow
def test_every_module_imports_with_root_only():
    """positive: КАЖДЫЙ модуль импортируется ПЕРВЫМ в своём процессе.

    v3.33.1: прежде все 95 модулей импортировались в ОДНОМ процессе — и первый же, кто тянул
    `_bootstrap`, чинил `sys.path` за всех остальных. Проверка была зелёной, а
    `import ai_ops_kit.lifecycle.run_report` в свежем процессе падал: девять модулей звали
    валидаторов по плоскому имени, не положив пути. После `pip install` пользователь получал
    ровно это.

    Порядок импортов — не контракт. Модуль обязан быть самодостаточным, а проверка обязана это
    мерить, а не полагаться на соседей: иначе она проверяет порядок обхода, а не пакет.
    """
    modules = _modules()
    assert modules, "модулей не найдено — тест потерял предмет"
    failed = {}
    for name in modules:                      # по одному: процесс на модуль, без чужих следов
        failed.update(_import_with_root_only([name]))
    assert not failed, (
        "модули пакета не импортируются, когда на пути только корень и они идут первыми "
        f"(после pip install будет то же самое): {dict(list(failed.items())[:5])}")


@pytest.mark.slow
def test_flat_import_would_be_caught(tmp_path):
    """fail-closed: подсунуть модуль с плоским импортом — проба обязана покраснеть."""
    root = tmp_path / "root"
    (root / "ai_ops_kit" / "probe").mkdir(parents=True)
    (root / "ai_ops_kit" / "__init__.py").write_text("", encoding="utf-8")
    (root / "ai_ops_kit" / "probe" / "__init__.py").write_text("", encoding="utf-8")
    (root / "tools").mkdir()
    (root / "tools" / "sibling.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "ai_ops_kit" / "probe" / "uses_flat.py").write_text(
        "import sibling\n", encoding="utf-8")          # плоское имя: видно только с tools/ на пути

    failed = _import_with_root_only(["ai_ops_kit.probe.uses_flat"], root=root)
    assert "ai_ops_kit.probe.uses_flat" in failed, (
        "плоский импорт не пойман — проба смотрит не туда, и класс дефектов пройдёт мимо")


def test_no_flat_internal_imports_left():
    """side-effect: связи между модулями пакета выражены пакетными именами.

    Плоские имена соседей — это те же связи, но невидимые ни человеку, ни `validate_layering`
    без карты «имя -> пакет». Исключение ровно одно: валидаторы из `validation/`, которые пакетом
    не являются, и `_bootstrap`, который путь к ним и кладёт.
    """
    own = {f.stem for d in SURFACE.iterdir() if d.is_dir() and d.name != "__pycache__"
           for f in d.glob("*.py") if f.name != "__init__.py"}
    leftovers = []
    for d in sorted(SURFACE.iterdir()):
        if not d.is_dir() or d.name == "__pycache__":
            continue
        for f in sorted(d.glob("*.py")):
            if f.name == "__init__.py":
                continue
            tree = ast.parse(f.read_text(encoding="utf-8"))
            for n in ast.walk(tree):
                names = ([a.name for a in n.names] if isinstance(n, ast.Import)
                         else [n.module] if isinstance(n, ast.ImportFrom) and n.module and not n.level
                         else [])
                for name in names:
                    if name in own:
                        leftovers.append(f"{f.relative_to(PKG)}: {name}")
    assert not leftovers, f"остались плоские внутренние импорты: {leftovers[:8]}"
