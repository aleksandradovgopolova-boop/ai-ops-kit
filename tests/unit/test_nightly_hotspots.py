"""Горячие точки ночного обзора: агрегат ПО ИСТОРИИ — что краснеет ЧАЩЕ всего (хронические болячки).

ПОВОД. Обзор смотрел на СНИМОК (что разошлось со вчера) и на НЕДЕЛЬНЫЙ ТРЕНД (лучше/хуже за неделю
относительно одного обзора-якоря). Ни то ни другое не отвечает «что болит ХРОНИЧЕСКИ»: какая
проверка/ось краснеет из ночи в ночь. Работа `nightly-review-aggregates-hotspots-from-history`
добавляет этот срез — агрегат по всей доступной истории, а не по одной точке.

Проверяются свойства, каждое стоило бы дорого без него:
  (а) история из нескольких прогонов -> горячие точки названы ПО ЧАСТОТЕ покраснения, в верном
      порядке (хроническое выше разового), с числом «краснела в K из N»;
  (б) записей меньше порога -> «мало истории», агрегат НЕ выдуман (и это НЕ «горячих точек нет»);
  (в) пустая история -> честно «истории ещё нет»;
  (г) горячие точки ПО ОСЯМ — тот же агрегат из той же истории, имя оси человеческое;
  (д) окно ограничивает агрегат последними N записями; агрегат read-only, нового файла не заводит.
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT))

from ai_ops_kit.intelligence import nightly_dimensions as nd  # noqa: E402
from ai_ops_kit.intelligence import nightly_hotspots as nh  # noqa: E402
from ai_ops_kit.intelligence import nightly_review as nr  # noqa: E402
from ai_ops_kit.intelligence import nightly_trends as nt  # noqa: E402


def _findings(**counts):
    """Синтетические находки: {check: n} -> n записей `ok is False` для этой проверки (как в тренде)."""
    out = []
    for check, n in counts.items():
        for _ in range(int(n)):
            out.append({"check": check, "subject": check, "ok": False, "detail": "расхождение"})
    return out


def _history(*runs):
    """История как список записей `{counts: {...}}` из последовательности словарей счётчиков-по-проверке."""
    return [{"at": f"2026-09-{i + 1:02d}T03:00:00", "counts": dict(run)} for i, run in enumerate(runs)]


@pytest.fixture()
def repo(tmp_path):
    """Git-репозиторий с одним коммитом — минимум, на котором обзор осмыслен (как в test_nightly_review)."""
    root = tmp_path / "product"
    root.mkdir()
    (root / "README.md").write_text("# p\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    for k, v in (("user.email", "t@t.t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(root), "config", k, v], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "init"], check=True)
    return root


# ── (а) НЕСКОЛЬКО ПРОГОНОВ -> ГОРЯЧИЕ ТОЧКИ ПО ЧАСТОТЕ, В ВЕРНОМ ПОРЯДКЕ ────────────────────────

@pytest.mark.unit
def test_hotspots_rank_checks_by_how_often_they_went_red():
    """Проверка, что краснела в БОЛЬШЕМ числе прогонов, стоит выше — хроническое выше разового."""
    hist = _history({"ссылки": 1}, {"ссылки": 1, "документация": 1},
                    {"ссылки": 1, "документация": 1}, {"ссылки": 1}, {})
    hot = nh.compute_hotspots(hist)
    assert hot["has_enough"] is True, hot
    checks = [r["check"] for r in hot["rows"]]
    assert checks == ["ссылки", "документация"], hot["rows"]
    top = hot["rows"][0]
    assert top["runs_red"] == 4 and top["window_runs"] == 5, top


@pytest.mark.unit
def test_ties_on_frequency_break_by_total_findings():
    """При равной частоте выше тот, у кого БОЛЬШЕ находок суммарно (сильнее болит)."""
    hist = _history({"a": 1, "b": 5}, {"a": 1, "b": 1}, {"a": 1, "b": 1})
    hot = nh.compute_hotspots(hist)
    # обе краснели в 3 из 3; b даёт 7 находок, a — 3, значит b выше
    assert [r["check"] for r in hot["rows"]] == ["b", "a"], hot["rows"]
    assert hot["rows"][0]["total_findings"] == 7, hot["rows"][0]


@pytest.mark.unit
def test_the_hotspot_line_names_frequency_out_of_the_window():
    """Строка брифа называет частоту словами «краснела в K из N обзоров»."""
    hot = nh.compute_hotspots(_history({"ссылки": 1}, {"ссылки": 1}, {"ссылки": 1}, {}))
    lines = "\n".join(nh.format_hotspots(hot))
    assert "краснела в 3 из 4 обзоров" in lines, lines


# ── (б) МАЛО ЗАПИСЕЙ -> «МАЛО ИСТОРИИ», НЕ ВЫДУМАНО, И ЭТО НЕ «ГОРЯЧИХ ТОЧЕК НЕТ» ───────────────

@pytest.mark.unit
def test_too_few_entries_says_little_history_and_invents_nothing():
    """Записей меньше порога -> has_enough=False, строк нет, агрегат не выдуман."""
    hot = nh.compute_hotspots(_history({"ссылки": 1}, {"ссылки": 1}))
    assert hot["has_enough"] is False and hot["rows"] == [], hot
    assert hot["considered"] == 2 and hot["min_entries"] == nh.MIN_ENTRIES_FOR_HOTSPOTS
    assert "мало истории" in hot["reason"], hot["reason"]


@pytest.mark.unit
def test_little_data_is_not_the_same_as_no_hotspots():
    """«Мало данных» (has_enough=False) и «за окно ничто не краснело» (has_enough=True, rows=[]) —
    РАЗНЫЕ ответы и не сворачиваются один в другой."""
    scarce = nh.compute_hotspots(_history({"ссылки": 1}))
    empty_but_enough = nh.compute_hotspots(_history({}, {}, {}))
    assert scarce["has_enough"] is False
    assert empty_but_enough["has_enough"] is True and empty_but_enough["rows"] == []
    scarce_text = "\n".join(nh.format_hotspots(scarce))
    measured_text = "\n".join(nh.format_hotspots(empty_but_enough))
    assert "мало данных" in scarce_text.lower()
    assert "ничто не краснело" in measured_text and "мало данных" not in measured_text.lower()


# ── (в) ПУСТАЯ ИСТОРИЯ -> ЧЕСТНО ────────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_empty_history_says_so_and_invents_no_hotspot():
    """Пустая история -> честное «истории ещё нет», без выдуманных горячих точек."""
    hot = nh.compute_hotspots([])
    assert hot["has_enough"] is False and hot["rows"] == [] and hot["considered"] == 0
    assert "истории ещё нет" in hot["reason"], hot["reason"]


# ── (г) ГОРЯЧИЕ ТОЧКИ ПО ОСЯМ — ТА ЖЕ ИСТОРИЯ, ИМЯ ОСИ ЧЕЛОВЕЧЕСКОЕ ─────────────────────────────

@pytest.mark.unit
def test_axis_hotspots_aggregate_the_same_history_by_axis(repo):
    """Осевые счётчики истории агрегируются в горячие точки по осям; имя оси — человеческое."""
    for _ in range(3):
        f = _findings(документация=1)
        nt.record_history(repo, f, axis_counts=nd.axis_finding_counts(f))
    f = _findings(события=1)
    nt.record_history(repo, f, axis_counts=nd.axis_finding_counts(f))
    hot = nh.compute_axis_hotspots(nt.read_history(repo))
    assert [r["check"] for r in hot["rows"]] == ["documentation", "analytics"], hot["rows"]
    assert hot["rows"][0]["runs_red"] == 3, hot["rows"][0]
    lines = "\n".join(nh.format_axis_hotspots(hot))
    assert "документация" in lines, lines  # ключ оси переведён в название


@pytest.mark.unit
def test_axis_hotspots_share_the_review_history_not_a_second_journal(repo):
    """Горячие точки по осям читают ТУ ЖЕ историю обзора (history.yaml), нового журнала не заводят."""
    f = _findings(события=1)
    for _ in range(3):
        nt.record_history(repo, f, axis_counts=nd.axis_finding_counts(f))
    files_before = {p.name for p in (repo / ".ai/project/nightly-review").glob("*")}
    nh.compute_axis_hotspots(nt.read_history(repo))
    files_after = {p.name for p in (repo / ".ai/project/nightly-review").glob("*")}
    assert files_before == files_after, "агрегат горячих точек завёл новый файл состояния"
    assert "history.yaml" in files_after


# ── (д) ОКНО ОГРАНИЧИВАЕТ АГРЕГАТ; ИНТЕГРАЦИЯ С БРИФОМ ──────────────────────────────────────────

@pytest.mark.unit
def test_the_window_limits_the_aggregate_to_recent_entries():
    """Старые записи вне окна не считаются: болячка, погасшая давно, в горячие точки не попадает."""
    hist = _history({"старое": 1}, {"старое": 1}, {"свежее": 1}, {"свежее": 1}, {"свежее": 1})
    hot = nh.compute_hotspots(hist, window=3)
    checks = [r["check"] for r in hot["rows"]]
    assert checks == ["свежее"], hot
    assert "старое" not in checks, "запись вне окна не должна попадать в агрегат"


@pytest.mark.unit
def test_the_brief_shows_the_hotspots_section(repo):
    """Бриф показывает раздел «Горячие точки» — первоклассно, наравне с трендом."""
    delta = nr.collect_delta(repo)
    brief = nr.format_brief(delta, repo)
    assert "## Горячие точки" in brief, brief


@pytest.mark.unit
def test_the_brief_hotspots_name_the_chronic_check_from_real_history(repo):
    """С накопленной историей раздел брифа называет хроническую болячку по частоте."""
    for _ in range(3):
        nt.record_history(repo, _findings(ссылки=1))
    brief = nr.format_brief(nr.collect_delta(repo), repo)
    section = brief.split("## Горячие точки", 1)[1].split("## ", 1)[0]
    assert "ссылки" in section and "из 3 обзоров" in section, section
