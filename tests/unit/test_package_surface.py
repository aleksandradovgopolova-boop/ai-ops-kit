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
import re
import importlib
from pathlib import Path

import pytest

import _bootstrap  # noqa: F401 — кладёт tools/ и корень в sys.path

PKG = Path(__file__).resolve().parents[2]
SURFACE = PKG / "ai_ops_kit"
# v3.34: ЗОНА-ИСКЛЮЧЕНИЕ. `validation` — точки входа, а не модули движка: их основной способ
# вызова — запуск процессом (CI, `ai-ops doctor`, pytest), и в этом режиме корня репозитория на
# `sys.path` нет по определению. Поэтому валидатор обязан начинаться с плоского `import _bootstrap`
# — единственного способа положить пути ДО того, как появится пакетное имя. Инварианты «плоский
# алиас в tools/», «единственный дом» и «импорт с одним корнем» писались для кода, который
# импортируют; распространить их сюда значило бы завести 76 алиасов в `tools/` — то есть раздуть
# СЛЕДУЮЩЕЕ родовое имя ради формальной чистоты предыдущего.
#
# Исключение объявлено ОДНИМ именем и проверяется на нерасползание (см. тест ниже): любой другой
# пакет, пытающийся жить по этим правилам, поймается.
EXEMPT_ZONE = "validation"

PRODUCT_PACKAGES = sorted(d.name for d in SURFACE.iterdir()
                          if d.is_dir() and d.name not in {"__pycache__", "devtools", EXEMPT_ZONE})


def _aliases():
    """{плоское имя: [пакеты, где он объявлен]}"""
    out = {}
    for d in sorted(SURFACE.iterdir()):
        if not d.is_dir() or d.name in ("__pycache__", EXEMPT_ZONE):
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
    """Алиас обязан БЫТЬ модулем, а не его копией — иначе состояние разъезжается.

    `_bootstrap` исключён осознанно (v3.33): его тёзки в `tools/`, `validation/` и в пакете —
    независимые модули по необходимости, потому что каждый обязан быть импортируем ДО того, как
    настроены пути. Требование единственного объекта к ним неприменимо и безопасно: состояния они
    не держат, а правка sys.path идемпотентна.
    """
    for f in sorted((SURFACE / pkg).glob("*.py")):
        if f.name in ("__init__.py", "_bootstrap.py"):
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
def test_exactly_one_side_is_an_alias():
    """У каждого модуля ровно одна сторона — алиас, вторая — настоящий код.

    Инвариант держится и ДО переезда (код в tools/, алиас в пакете), и ПОСЛЕ (код в пакете, алиас
    в tools/ для обратной совместимости 661 импорта). Две копии кода или два алиаса одинаково
    плохи: в первом случае правки расходятся, во втором модуля нет вообще.

    Форма алиаса обязана быть подменой sys.modules: `from X import *` создал бы второй объект
    модуля со своим состоянием — этот класс уже стоил отладки в orchestrator_usage и pr_open.

    v3.33: `_bootstrap` — объявленное исключение. Его задача — положить пути ДО того, как станет
    возможен любой импорт, поэтому он обязан существовать в каждом каталоге, откуда запускают код:
    `tools/`, `ai_ops_kit/validation/` и внутри пакета. Три тёзки не расходятся по смыслу — каждый ищет корень
    по маркеру VERSION и идемпотентно правит sys.path, состояния ни один не держит. Алиас здесь
    невозможен: чтобы импортировать алиас, нужен путь, который кладёт как раз он.
    """
    BOOTSTRAP_BY_DESIGN = {"_bootstrap.py"}

    def is_alias(path: Path) -> bool:
        return "sys.modules[__name__]" in path.read_text(encoding="utf-8")

    problems = []
    for d in sorted(SURFACE.iterdir()):
        # v3.34: зона-исключение алиасов не имеет и иметь не должна — валидаторы запускают
        # процессом по пути, а импортируют пакетным именем. 76 алиасов в `tools/` раздули бы
        # следующее родовое имя ради формальной чистоты предыдущего.
        if not d.is_dir() or d.name in ("__pycache__", EXEMPT_ZONE):
            continue
        for f in sorted(d.glob("*.py")):
            if f.name == "__init__.py" or f.name in BOOTSTRAP_BY_DESIGN:
                continue
            flat = PKG / "tools" / f.name
            if not flat.is_file():
                problems.append(f"{d.name}/{f.name}: плоского файла нет вовсе")
                continue
            sides = [is_alias(f), is_alias(flat)]
            if sides.count(True) != 1:
                where = "оба алиасы" if all(sides) else "оба с кодом"
                problems.append(f"{d.name}/{f.name}: {where}")
            for path in (f, flat):
                if "import *" in path.read_text(encoding="utf-8"):
                    problems.append(f"{path}: алиас через `import *` копирует состояние")
    assert not problems, problems[:8]


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


@pytest.mark.unit
def test_flat_aliases_are_self_sufficient():
    """Плоский алиас обязан САМ уметь найти пакет.

    Поймано CI: алиас делал `import ai_ops_kit...`, не положив корень в sys.path. Локально это
    скрывала editable-установка (её .pth кладёт корень в любой процесс), а в CI и в
    child-репозитории, где PYTHONPATH не задан, запуск файла напрямую падал с
    ModuleNotFoundError. Тот же класс, что и «чеклист держался на editable-установке».
    """
    bad = []
    for d in sorted(SURFACE.iterdir()):
        if not d.is_dir() or d.name == "__pycache__":
            continue
        for f in sorted(d.glob("*.py")):
            if f.name == "__init__.py":
                continue
            flat = PKG / "tools" / f.name
            if not flat.is_file():
                continue
            src = flat.read_text(encoding="utf-8")
            if "sys.modules[__name__]" not in src:
                continue                      # настоящий код, не алиас
            if "import _bootstrap" not in src:
                bad.append(flat.name)
    assert not bad, (
        "алиасы импортируют пакет, не положив корень в sys.path — упадут вне editable-установки: "
        f"{bad[:8]}")


# ------------------------------------------------------------- зона-исключение ---

# Не-валидаторы, которым место в зоне ОБЪЯВЛЕНО поимённо. Список вправе только сокращаться:
# зона существует ради двурежимных точек входа, и всё, что попало сюда «просто так», обязано
# быть названо здесь с причиной — иначе исключение из инварианта станет складом.
ZONE_NON_VALIDATORS = {
    "__init__": "маркер пакета",
    "_bootstrap": "загрузчик путей: с него начинается КАЖДЫЙ валидатор в script-режиме",
    "ai_capability_selftest": "самопроверка возможностей, запускается процессом как валидатор",
    "ai_managed_checksums": "drift-детект managed-зоны; вызывается installer'ом и в child",
}


@pytest.mark.unit
def test_exempt_zone_is_a_single_declared_package():
    """Исключение одно и названо. Два исключения — это уже не исключение, а второе правило."""
    assert EXEMPT_ZONE == "validation"
    assert (SURFACE / EXEMPT_ZONE).is_dir(), "зона объявлена, а пакета нет"


@pytest.mark.unit
def test_exempt_zone_holds_only_entrypoints():
    """fail-closed: зона не превращается в склад для кода, которому там не место.

    Ровно так `ai_route` — движок маршрутизации, а не валидатор — годами лежал среди валидаторов
    и импортировался ПЛОСКО из `workitem` и `run_plan`. Пока каталог не был пакетом, это никому
    не мешало и никем не проверялось; при переносе (v3.34) вылезло сразу. Проверка ниже — чтобы
    следующий такой модуль ловился в тот же день, а не через год.
    """
    strays = []
    for f in sorted((SURFACE / EXEMPT_ZONE).glob("*.py")):
        if f.stem.startswith("validate_") or f.stem in ZONE_NON_VALIDATORS:
            continue
        strays.append(f.stem)
    assert not strays, (
        f"в зоне-исключении лежит не точка входа: {strays}. Либо модуль переезжает в свой пакет "
        f"(как ai_route -> engine в v3.34), либо вписывается в ZONE_NON_VALIDATORS с причиной")


@pytest.mark.unit
def test_zone_exemption_list_only_shrinks():
    """Объявленный не-валидатор, которого больше нет, обязан уйти из списка."""
    real = {f.stem for f in (SURFACE / EXEMPT_ZONE).glob("*.py")}
    stale = sorted(set(ZONE_NON_VALIDATORS) - real)
    assert not stale, f"объявлены несуществующие модули зоны: {stale}"


@pytest.mark.unit
def test_zone_modules_really_need_the_exemption():
    """side-effect: зона оправдана ФАКТОМ, а не удобством.

    Если валидаторы перестанут делать плоский `import _bootstrap`, исключение станет ненужным и
    обязано быть снято. Проверка обнаружит это сама, а не будет ждать, пока кто-то вспомнит.
    """
    # Идиома двурежимна (v3.34): пакетный импорт в try, ПЛОСКИЙ в except. Именно плоский
    # фолбэк и есть причина исключения — он невозможен для обычного модуля пакета.
    flat_bootstrap = [f.name for f in sorted((SURFACE / EXEMPT_ZONE).glob("*.py"))
                      if re.search(r"^\s*import _bootstrap\b", f.read_text(encoding="utf-8"), re.M)]
    assert flat_bootstrap, (
        "ни один валидатор больше не делает плоский import _bootstrap — причина зоны-исключения "
        "исчезла, снимите EXEMPT_ZONE и верните validation под общий инвариант")
