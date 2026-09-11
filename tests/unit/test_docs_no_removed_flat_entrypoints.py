"""Документация не зовёт снятый в 4.0 плоский слой — ни `tools/X.py`, ни корневой `validation/X.py`.

ПОВОД — ЗАМЕР 10.09.2026:
  Мажор 4.0 физически снял плоский слой `tools/` (точки входа стали пакетными,
  `python3 -m ai_ops_kit.<pkg>.<mod>`), а корневого `validation/` нет с 3.34. При этом:
    * `docs/WALKTHROUGH.md` целиком воспроизводил CLI на `python3 $KIT/tools/orchestrator.py …`
      и `$KIT/validation/ai_route.py …` — дочерний репозиторий, скопировав, получал «No such file»
      на каждой строке;
    * `docs/QUICKSTART.md` звал `<kit>/tools/generate_artifacts.py` и
      `.ai/managed/validation/validate_standalone_engine.py`, противореча собственному тексту
      («корневого `validation/` нет с 3.34»);
    * `FILE_INDEX.md` держал целую мёртвую секцию `tools/` (~40 путей).

ПОЧЕМУ СТОРОЖА НЕ ПОЙМАЛИ. `test_docs_name_what_exists` проверяет только `README.md` и `docs/**`
и только пути В ОБРАТНЫХ КАВЫЧКАХ. Командные строки в fenced-блоках (```bash … ```) не в кавычках,
а `FILE_INDEX.md` лежит в корне — вне его охвата. Так класс и прожил незамеченным.

ЧТО ЛОВИТ ЭТОТ ТЕСТ. Путь-сегмент `tools/<mod>.py` или `validation/<mod>.py` (в любом окружении —
`$KIT/…`, `.ai/managed/…`, голый, в кавычках или в команде), где `<mod>.py` РЕАЛЬНО существует под
`ai_ops_kit/` (значит, файл переехал, а путь остался старым). Пакетный `ai_ops_kit/validation/…`
не считается устаревшим; `.research/tools/…` (свой каталог) — тоже, там модуль не резолвится
под `ai_ops_kit/`.

ЗАПИСИ О ПРОШЛОМ (журнал версий, change-brief'ы, аудиты, миграционные гайды, research, qualification)
исключены: они по делу цитируют снятый слой, каким он был. Требовать от них сегодняшнего дерева —
переписывать прошлое.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PKG = Path(__file__).resolve().parents[2]

# Живой корпус: пользовательские доки + структурные карты + живые policy-доки.
CORPUS_ROOTS = ("docs", "rules", "runtime", "workflows", "templates")
CORPUS_FILES = ("README.md", "FILE_INDEX.md", "AGENTS.md", "NOTICE.md", "APPLY.md")

# Записи о прошлом — не обещания о настоящем.
PAST_PREFIXES = (
    "docs/changelog",
    "docs/change-briefs",
    "docs/audit-report.md",
    "docs/audit-2026",
    "history/",
    ".research/",
    "qualification/",
    "newsfragments/",
)

# Сегмент `tools/<mod>.py` или `validation/<mod>.py`, не приклеенный к `ai_ops_kit/`.
FLAT_SEGMENT = re.compile(r"(?<![\w./-])(tools|validation)/([a-z_][a-z0-9_]*)\.py")


def _module_lives_under_package(basename: str) -> bool:
    """`<basename>.py` существует где-то под `ai_ops_kit/` — значит, путь `tools/<basename>.py`
    или `validation/<basename>.py` указывает на место, откуда файл переехал."""
    return any(p.name == basename for p in (PKG / "ai_ops_kit").rglob(basename))


def _is_past(rel: str) -> bool:
    return any(rel.startswith(p) for p in PAST_PREFIXES)


def _live_docs():
    files = []
    for name in CORPUS_FILES:
        p = PKG / name
        if p.is_file():
            files.append(p)
    for root in CORPUS_ROOTS:
        for p in sorted((PKG / root).rglob("*.md")):
            if not _is_past(p.relative_to(PKG).as_posix()):
                files.append(p)
    return [f for f in files if f.is_file()]


LIVE = _live_docs()


def test_the_corpus_is_not_empty():
    """Зелёный обход пустого множества — это не «чисто», это «нечего проверять»."""
    assert len(LIVE) > 20, f"живой документации найдено {len(LIVE)} файлов — обход ослеп"


def test_the_corpus_covers_the_regression_sites():
    """Ровно те файлы, где жил дефект, обязаны быть в охвате — иначе сторож слеп там, где нужен."""
    covered = {f.relative_to(PKG).as_posix() for f in LIVE}
    for must in ("FILE_INDEX.md", "docs/WALKTHROUGH.md", "docs/QUICKSTART.md"):
        assert must in covered, f"{must} выпал из корпуса — сторож не покрывает место регрессии"


def test_no_document_calls_the_removed_flat_layer():
    """Плоский `tools/X.py` и корневой `validation/X.py` сняты в 4.0/3.34. Документ, который их
    называет там, где файл переехал под `ai_ops_kit/`, учит команде, ломающейся у дочки."""
    stale = []
    for f in LIVE:
        rel = f.relative_to(PKG).as_posix()
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            for m in FLAT_SEGMENT.finditer(line):
                basename = f"{m.group(2)}.py"
                if _module_lives_under_package(basename):
                    stale.append(f"{rel}:{i} -> {m.group(0)} (переехал под ai_ops_kit/)")
    assert not stale, (
        "документация зовёт снятый плоский слой (точки входа теперь "
        "`python3 -m ai_ops_kit.<pkg>.<mod>`, см. MIGRATION_GUIDE_4.0.md):\n  "
        + "\n  ".join(stale)
    )
