"""Пакетная поверхность ai_ops_kit: дом модуля — пакет.

v4.0: плоский слой `tools/` СНЯТ. Раньше настоящий код жил в `ai_ops_kit/<пакет>/`, а в `tools/`
лежали тонкие алиасы через подмену `sys.modules` для обратной совместимости; в 4.0 слой удалён
физически, точки входа зовутся пакетно (`python3 -m ai_ops_kit.<pkg>.<mod>`). Проверки, стоявшие на
самом факте существования плоского слоя (единственный дом, ровно одна сторона алиас, реестр
`deprecated-surface.yaml`), сняты вместе со слоем.

Осталось два инварианта, не зависящих от плоского слоя:
  * dev-only модули (installer.DEV_ONLY_TOOLS) не попадают в продуктовые пакеты — пользователь не
    получает то, чего получать не должен;
  * зона-исключение `validation` держит только точки входа, объявлена одним именем и не расползается.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2]
SURFACE = PKG / "ai_ops_kit"
# v3.34: ЗОНА-ИСКЛЮЧЕНИЕ. `validation` — точки входа, а не модули движка: их основной способ
# вызова — запуск процессом (CI, `ai-ops doctor`, pytest), и в этом режиме корня репозитория на
# `sys.path` нет по определению. Поэтому валидатор обязан начинаться с плоского `import _bootstrap`
# — единственного способа положить пути ДО того, как появится пакетное имя. Инвариант «единственный
# дом» писался для кода, который импортируют; распространить его сюда значило бы завести десятки
# алиасов.
#
# Исключение объявлено ОДНИМ именем и проверяется на нерасползание (см. тест ниже): любой другой
# пакет, пытающийся жить по этим правилам, поймается.
EXEMPT_ZONE = "validation"

PRODUCT_PACKAGES = sorted(d.name for d in SURFACE.iterdir()
                          if d.is_dir() and d.name not in {"__pycache__", "devtools", EXEMPT_ZONE})


def _aliases():
    """{имя модуля: [пакеты, где он объявлен]} — по всем продуктовым пакетам ai_ops_kit."""
    out = {}
    for d in sorted(SURFACE.iterdir()):
        if not d.is_dir() or d.name in ("__pycache__", EXEMPT_ZONE):
            continue
        for f in sorted(d.glob("*.py")):
            if f.name != "__init__.py":
                out.setdefault(f.stem, []).append(d.name)
    return out


def _dev_only():
    src = (PKG / "installer" / "ai_ops.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", None) == "DEV_ONLY_TOOLS" for t in node.targets):
            return set(ast.literal_eval(ast.unparse(node.value).replace("frozenset(", "").rstrip(")")))
    raise AssertionError("DEV_ONLY_TOOLS не найден в инсталляторе")


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
    assert not missing, f"dev-only модули без дома в devtools: {missing}"


# ------------------------------------------------------------- зона-исключение ---

# Не-валидаторы, которым место в зоне ОБЪЯВЛЕНО поимённо. Список вправе только сокращаться:
# зона существует ради двурежимных точек входа, и всё, что попало сюда «просто так», обязано
# быть названо здесь с причиной — иначе исключение из инварианта станет складом.
ZONE_NON_VALIDATORS = {
    "__init__": "маркер пакета",
    "_bootstrap": "загрузчик путей: с него начинается КАЖДЫЙ валидатор в script-режиме",
    "ai_capability_selftest": "самопроверка возможностей, запускается процессом как валидатор",
    "ai_managed_checksums": "drift-детект managed-зоны; вызывается installer'ом и в child",
    "delivery_footprint_warning": "чистая логика предупреждения о тающем запасе поставки; ядро вверх "
                                  "не тянет (разбор передаётся аргументом), зовётся проверкой "
                                  "поставки test_installer — живёт рядом с потолком по write_scope "
                                  "работы delivery-footprint-warns-before-breach",
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
