"""Пакетная поверхность ai_ops_kit — шим перед физическим переносом дерева (v3.30).

Дерево пока плоское. Пакет даёт модулям осмысленные имена и границы, НЕ перемещая файлы: каждый
подмодуль — алиас через sys.modules. Обычный шим (`from X import *`) создал бы второй объект
модуля со своим состоянием, и пересоздание глобали (как `drain_call_stats` в orchestrator_usage)
разъехалось бы между копиями — этот класс дефектов уже стоил отдельной отладки.

Три обязательных теста на capability (AGENTS.md):
  * positive     — оба пути импорта дают ОДИН объект; каждый плоский модуль имеет ровно один алиас;
  * fail-closed  — модуль вне пакетов и модуль в двух пакетах ловятся; dev-only не попадает в
                   продуктовый пакет;
  * side-effect  — состояние общее: правка через один путь видна через другой.
"""
from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

import _bootstrap  # noqa: F401 — кладёт tools/ и корень в sys.path

PKG = Path(__file__).resolve().parents[2]
SURFACE = PKG / "ai_ops_kit"
PRODUCT_PACKAGES = sorted(d.name for d in SURFACE.iterdir()
                          if d.is_dir() and d.name not in {"__pycache__", "devtools"})


def _aliases():
    """{плоское имя: [пакеты, где он объявлен]}"""
    out = {}
    for d in sorted(SURFACE.iterdir()):
        if not d.is_dir() or d.name == "__pycache__":
            continue
        for f in sorted(d.glob("*.py")):
            if f.name != "__init__.py":
                out.setdefault(f.stem, []).append(d.name)
    return out


def _flat_modules():
    return {p.stem for p in (PKG / "tools").glob("*.py")} - {"__init__"}


def _dev_only():
    src = (PKG / "installer" / "ai_ops.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", None) == "DEV_ONLY_TOOLS" for t in node.targets):
            return set(ast.literal_eval(ast.unparse(node.value).replace("frozenset(", "").rstrip(")")))
    raise AssertionError("DEV_ONLY_TOOLS не найден в инсталляторе")


# ---------------------------------------------------------------- positive ---

@pytest.mark.unit
@pytest.mark.parametrize("pkg", PRODUCT_PACKAGES)
def test_package_modules_are_the_same_object(pkg):
    """Алиас обязан БЫТЬ модулем, а не его копией — иначе состояние разъезжается."""
    for f in sorted((SURFACE / pkg).glob("*.py")):
        if f.name == "__init__.py":
            continue
        via_pkg = importlib.import_module(f"ai_ops_kit.{pkg}.{f.stem}")
        flat = importlib.import_module(f.stem)
        assert via_pkg is flat, f"{pkg}.{f.stem}: алиас — отдельный объект, состояние разъедется"


@pytest.mark.unit
def test_every_flat_module_has_exactly_one_home():
    aliases = _aliases()
    flat = _flat_modules() - {"_bootstrap"} | {"_bootstrap"}
    homeless = sorted(flat - set(aliases))
    assert not homeless, f"модули вне пакетной поверхности: {homeless}"
    doubled = {m: p for m, p in aliases.items() if len(p) > 1}
    assert not doubled, f"модуль объявлен в двух пакетах: {doubled}"


# ------------------------------------------------------------- fail-closed ---

@pytest.mark.unit
def test_dev_only_modules_are_not_in_product_packages():
    """Продуктовый пакет не должен содержать то, что пользователь никогда не получит.

    Источник истины — installer.DEV_ONLY_TOOLS: единственное объявление об исключении из поставки.
    """
    aliases = _aliases()
    dev = _dev_only()
    leaked = sorted(m for m in dev if any(p != "devtools" for p in aliases.get(m, [])))
    assert not leaked, f"dev-only модули лежат в продуктовых пакетах: {leaked}"
    missing = sorted(m for m in dev if "devtools" not in aliases.get(m, []))
    assert not missing, f"dev-only модули без алиаса в devtools: {missing}"


@pytest.mark.unit
def test_alias_files_do_not_copy_state():
    """Запрещённая форма шима: `from X import *` вместо подмены sys.modules."""
    bad = []
    for d in sorted(SURFACE.iterdir()):
        if not d.is_dir() or d.name == "__pycache__":
            continue
        for f in sorted(d.glob("*.py")):
            if f.name == "__init__.py":
                continue
            src = f.read_text(encoding="utf-8")
            if "sys.modules[__name__]" not in src or "import *" in src:
                bad.append(f"{d.name}/{f.name}")
    assert not bad, f"алиасы копируют состояние вместо подмены модуля: {bad}"


# -------------------------------------------------------- side-effect proof ---

@pytest.mark.unit
def test_state_is_really_shared():
    """Правка через пакетный путь видна через плоский — доказательство единственности объекта."""
    from ai_ops_kit.providers import orchestrator_usage as via_pkg
    import orchestrator_usage as flat

    marker = {"model": "package-surface-probe", "input_tokens": 1}
    via_pkg._CALL_STATS.append(marker)
    try:
        assert marker in flat._CALL_STATS, "состояние не общее — это две копии модуля"
    finally:
        flat._CALL_STATS.remove(marker)
