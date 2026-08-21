"""Список «не подключено» не превращается в кладбище.

ПОВОД — ЗАМЕР (19.08.2026, разбор после аудита). Двенадцать модулей, добавленных 19.08, уезжали в
дочку и были там недостижимы: ноль импортов из поставки, ноль упоминаний в реестрах, гейтах,
workflow, командах и документации. Они пробили потолок поставки (479 содержательных файлов при 475,
3.7449 МБ при 3.7), и поднимать потолок под них значило бы платить объёмом дочки за то, что в ней
не работает.

Исключение из поставки — половина решения. Вторая половина здесь: **список обязан стареть в одну
сторону**. Как только модуль подключат (интентом, гейтом, записью в реестре или упоминанием в
документации), он перестаёт быть «не подключённым», и его имя обязано УЙТИ отсюда — иначе список
превратится в кладбище и перестанет что-либо значить, ровно как `known_violations` в
`packages/layering.yaml`, про который это сказано прямо.

Тест поэтому проверяет ДВА направления:
  * объявленное неподключённым действительно никем не вызывается (иначе дочка недополучает файл,
    который ей нужен — это хуже лишнего файла);
  * файл существует (имя в списке не должно пережить удаление модуля).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT / "installer"))

import ai_ops as installer  # noqa: E402 — путь ставится выше

# Где ищем следы подключения. Каталоги поставки + документация кита: если модуль назван хоть здесь,
# у него есть путь, по которому его позовут в дочке.
WIRING_DIRS = ("ai_ops_kit", "tools", "registry", "quality", "config", "commands", "workflows",
               "docs", "templates", "agents", "rules")
WIRING_FILES = ("README.md", "AGENTS.md")


def _module_name(rel: str) -> str:
    return rel.rsplit("/", 1)[-1][: -len(".py")]


def _mentions(name: str) -> list[str]:
    """Файлы, которые называют модуль, кроме него самого и других неподключённых."""
    own = {PKG_ROOT / r for r in installer.UNWIRED_MODULES}
    pat = re.compile(rf"\b{re.escape(name)}\b")
    hits = []
    for d in WIRING_DIRS:
        base = PKG_ROOT / d
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if not p.is_file() or "__pycache__" in p.parts or p.suffix in (".pyc",):
                continue
            if p in own:
                continue                       # ссылка внутри самой группы подключением не является
            try:
                if pat.search(p.read_text(encoding="utf-8", errors="ignore")):
                    hits.append(str(p.relative_to(PKG_ROOT)))
            except OSError:
                continue
    for f in WIRING_FILES:
        p = PKG_ROOT / f
        if p.is_file() and pat.search(p.read_text(encoding="utf-8", errors="ignore")):
            hits.append(f)
    return hits


@pytest.mark.unit
def test_every_unwired_module_still_exists():
    """Имя не переживает файл: удалённый модуль обязан уйти из списка."""
    missing = [r for r in sorted(installer.UNWIRED_MODULES) if not (PKG_ROOT / r).is_file()]
    assert not missing, (
        "в UNWIRED_MODULES перечислены файлы, которых нет — список стал кладбищем:\n  "
        + "\n  ".join(missing))


@pytest.mark.unit
@pytest.mark.parametrize("rel", sorted(installer.UNWIRED_MODULES))
def test_unwired_modules_are_really_unwired(rel):
    """Объявленное неподключённым обязано быть неподключённым — иначе дочка недополучает нужное."""
    hits = _mentions(_module_name(rel))
    assert not hits, (
        f"модуль '{rel}' объявлен неподключённым, но его называют: {hits[:6]}.\n"
        f"Если его подключили — уберите имя из installer.UNWIRED_MODULES, иначе дочка не получит "
        f"файл, который у неё зовут (класс F-033: механизм починен у кита и не доехал до дочки).")


@pytest.mark.unit
def test_unwired_modules_do_not_ship():
    """Заявленное исключение ИСПОЛНЯЕТСЯ фильтром поставки, а не только объявлено."""
    shipped = [r for r in sorted(installer.UNWIRED_MODULES) if installer.is_runtime_asset(r)]
    assert not shipped, f"объявлены неподключёнными, но едут в дочку: {shipped}"
