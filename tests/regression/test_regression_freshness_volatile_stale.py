"""Regression: протухший volatile-документ должен помечаться stale по реальному файлу.

ИСТОЧНИК. Механизм свежести знаний (validate_freshness, v2.9+): документы с frontmatter
`stability: volatile` протухают через 14 дней после `reviewed_at`; `evolving` — 90; `stable`
не истекает. Класс дефекта — «устаревший источник читается как актуальный»: если срок volatile
или ветка сравнения дат ломается, протухший оперативный документ молча остаётся «свежим».

СИМПТОМ. Владелец опирается на volatile-контекст, который на самом деле протух две недели назад,
и не получает сигнала STALE.

ЧТО КРАСНЕЕТ ПРИ РЕГРЕССЕ. Сквозной прогон `build()` по каталогу с РЕАЛЬНЫМ .md-файлом: volatile,
проверенный 30 дней назад, обязан прийти со статусом `stale`, а проверенный сегодня — `ok`.
Если `DEFAULT_EXPIRY["volatile"]` раздуть или сломать `today > expires` — тест краснеет.

Угол НОВЫЙ относительно unit-слоя: `tests/unit/test_validate_freshness.py` зовёт `assess`
напрямую словарями; здесь идёт полный путь через диск — парсинг frontmatter реального файла и
сборка отчёта `build`, то есть ровно то, что исполняется в CI/на дочке.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from validate_freshness import build, run


def _write_doc(directory, name, stability, reviewed_at):
    (directory / name).write_text(
        f"---\nstability: {stability}\nreviewed_at: {reviewed_at}\n---\n\n# doc\n",
        encoding="utf-8",
    )


@pytest.mark.regression
def test_volatile_reviewed_30d_ago_is_stale_through_real_file(tmp_path):
    """volatile, проверенный 30д назад, читается с диска и классифицируется stale."""
    today = date(2026, 9, 4)
    _write_doc(tmp_path, "ops-note.md", "volatile", (today - timedelta(days=30)).isoformat())

    results = build(tmp_path, today)

    assert len(results) == 1, results
    row = results[0]
    assert row["path"] == "ops-note.md"
    assert row["status"] == "stale", row


@pytest.mark.regression
def test_volatile_reviewed_today_is_fresh_through_real_file(tmp_path):
    """Тот же класс, проверенный сегодня, — ok (граница волатильности держится с обеих сторон)."""
    today = date(2026, 9, 4)
    _write_doc(tmp_path, "ops-note.md", "volatile", today.isoformat())

    results = build(tmp_path, today)

    assert results[0]["status"] == "ok", results


@pytest.mark.regression
def test_strict_run_returns_nonzero_when_a_volatile_doc_is_stale(tmp_path):
    """`run(..., strict=True)` возвращает 1 на протухшем volatile — сигнал доходит до выхода процесса."""
    today = date(2026, 9, 4)
    _write_doc(tmp_path, "ops-note.md", "volatile", (today - timedelta(days=30)).isoformat())

    assert run(tmp_path, today, strict=True) == 1
    # без --strict протухший документ — сигнал, а не блок: код возврата 0.
    assert run(tmp_path, today, strict=False) == 0
