# -*- coding: utf-8 -*-
"""Охват точки входа: каждый документ достижим из `docs/index.md`.

Мы сознательно НЕ заводим отдельную вики: находимость решается внутри репозитория одной дверью —
`docs/index.md` с четырьмя уровнями — и держится ПРОВЕРКОЙ, а не честным словом. Вики — это второй
источник истины, который тихо разъезжается с деревом; здесь тот же разъезд ловится красным.

Охраняется ОХВАТ, а не текст: если новый документ добавлен в `docs/`, но из индекса до него не
дойти по ссылкам, он — сирота, и проверка краснеет. «Достижим» = обходом ссылок от `docs/index.md`
вглубь дерева `docs/` (индекс → под-индекс README → лист тоже считается: индексу нужна
достижимость, а не пофайловое перечисление каждого листа).

Тот же класс защиты, что и `test_derived_numbers_coverage.py`: проверка без охвата — половина
проверки, а половина создаёт видимость полной.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[2]
DOCS = (KIT / "docs").resolve()
INDEX = DOCS / "index.md"

# `[текст](ссылка)` — берём ссылку до пробела (markdown-заголовок в кавычках) и до якоря `#`.
_LINK = re.compile(r"\]\(([^)\s]+)")

pytestmark = [pytest.mark.unit]


def _linked_docs(md: Path) -> set[Path]:
    """Относительные ссылки на `.md` внутри дерева `docs/`, разрешённые от файла-источника."""
    out: set[Path] = set()
    for href in _LINK.findall(md.read_text(encoding="utf-8", errors="replace")):
        href = href.split("#", 1)[0]
        if not href or "://" in href:  # якорь-в-себя или внешний URL — не переход по дереву
            continue
        target = (md.parent / href).resolve()
        if target.suffix == ".md" and (target == DOCS or DOCS in target.parents):
            out.add(target)
    return out


def _reachable_from_index() -> set[Path]:
    seen: set[Path] = set()
    queue = [INDEX.resolve()]
    while queue:
        cur = queue.pop()
        if cur in seen or not cur.is_file():
            continue
        seen.add(cur)
        queue.extend(_linked_docs(cur))
    return seen


def _all_docs() -> set[Path]:
    return {p.resolve() for p in DOCS.rglob("*.md")}


def test_index_is_the_single_entry_point():
    """Каждый документ в `docs/` достижим из индекса — сирот нет."""
    orphans = sorted(
        p.relative_to(KIT).as_posix() for p in (_all_docs() - _reachable_from_index())
    )
    assert not orphans, (
        "документ в docs/ не достижим из docs/index.md — до него не дойти ни по одной ссылке: "
        f"{orphans}. Впишите его в docs/index.md или в под-индекс README, на который индекс ссылается")


def test_index_itself_exists_and_is_reached():
    """Защита от вырождения: индекс на месте и является корнем обхода."""
    assert INDEX.is_file(), "docs/index.md исчез — точки входа нет"
    assert INDEX.resolve() in _reachable_from_index()
