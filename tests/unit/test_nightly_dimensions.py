"""Ночной обзор по осям: находки РАЗЛОЖЕНЫ по названным осям, фокус РОТИРУЕТСЯ, оси питают тренд.

ПОВОД. Обзор перечислял находки одним плоским списком — по нему не видно, какие измерения продукта
вообще смотрели. «Расхождений нет» было неотличимо от «сюда не заглядывали». Работа
`nightly-review-organizes-and-rotates-dimensions` раскладывает находки по названным осям (имена — из
каталога ревьюеров `agents/quality/`, не выдуманы), РОТИРУЕТ фокус (каждый прогон подсвечивает
следующую ось, за цикл проходят все) и кормит осевыми счётчиками уже готовый недельный тренд (#1053).

Проверяются четыре свойства, каждое стоило бы дорого без него:
  (а) находки сгруппированы по НАЗВАННЫМ осям;
  (б) ротация двигает фокус между прогонами, курсор персистится, за цикл — все оси;
  (в) ось без наблюдаемого сигнала В ЭТОМ РЕПО -> «не наблюдается», а НЕ «ок»;
  (г) осевые счётчики питают ТОТ ЖЕ недельный тренд (не второй журнал).
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
from ai_ops_kit.intelligence import nightly_review as nr  # noqa: E402
from ai_ops_kit.intelligence import nightly_trends as nt  # noqa: E402


def _findings(**by_check):
    """Синтетические находки: check=ok-строка ('bad'/'good'/'unknown') или список таких строк.

    Обзор даёт одну запись на проверку; здесь можно задать несколько расхождений на проверку, чтобы
    проверить и группировку, и арифметику счётчиков по оси.
    """
    mark = {"bad": False, "good": True, "unknown": None}
    out = []
    for check, spec in by_check.items():
        specs = spec if isinstance(spec, (list, tuple)) else [spec]
        for s in specs:
            out.append({"check": check, "subject": check, "ok": mark[s], "detail": f"{check}:{s}"})
    return out


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


# ── (а) НАХОДКИ СГРУППИРОВАНЫ ПО НАЗВАННЫМ ОСЯМ ────────────────────────────────────────────────

@pytest.mark.unit
def test_findings_are_grouped_under_the_named_axis_their_check_belongs_to():
    """Проверки документации ложатся под ось «документация», артефактов — под «архитектуру» и т.д."""
    groups = {g["key"]: g for g in nd.group_findings_by_axis(
        _findings(документация="bad", ссылки="bad", артефакты="bad",
                  **{"план работы": "bad", "события": "bad"}))}
    assert groups["documentation"]["status"] == "расхождения"
    assert {f["check"] for f in groups["documentation"]["findings"]} == {"документация", "ссылки"}
    assert groups["architecture"]["status"] == "расхождения"
    assert {f["check"] for f in groups["architecture"]["findings"]} == {"артефакты"}
    assert groups["product-ux"]["status"] == "расхождения"
    assert groups["analytics"]["status"] == "расхождения"


@pytest.mark.unit
def test_axis_names_come_from_the_reviewer_catalog_not_invented():
    """Каждый объявленный осью ревьюер РЕАЛЬНО существует в agents/quality/ — имена не выдуманы."""
    missing = [r for r in nd.declared_reviewers()
               if not (PKG_ROOT / "agents" / "quality" / f"{r}.md").is_file()]
    assert missing == [], f"ось ссылается на несуществующего ревьюера: {missing}"


@pytest.mark.unit
def test_the_brief_groups_findings_by_axis_and_marks_the_focus(repo):
    """Бриф раскладывает находки по осям своим разделом и помечает ось в фокусе."""
    delta = nr.collect_delta(repo, focus="security")
    brief = nr.format_brief(delta, repo)
    assert "## Что я проверила — по осям" in brief
    for dim in nd.DIMENSIONS:
        assert f"### {dim['title']}" in brief, f"ось «{dim['title']}» не названа в брифе"
    section = brief.split("## Что я проверила — по осям", 1)[1]
    assert "### безопасность — **в фокусе сегодня**" in section


# ── (б) РОТАЦИЯ ДВИГАЕТ ФОКУС, КУРСОР ПЕРСИСТИТСЯ, ЗА ЦИКЛ — ВСЕ ОСИ ────────────────────────────

@pytest.mark.unit
def test_rotation_visits_every_axis_once_per_cycle_in_order(tmp_path):
    """За цикл (len осей прогонов) фокус проходит все оси ровно по разу, в порядке DIMENSIONS."""
    keys = nd.axis_keys()
    seq = [nd.rotate_focus(tmp_path, advance=True) for _ in range(len(keys))]
    assert seq == keys, seq
    assert set(seq) == set(keys), "за цикл в фокус попали не все оси"


@pytest.mark.unit
def test_rotation_wraps_around_and_persists_the_cursor(tmp_path):
    """После полного цикла фокус возвращается к первой оси; курсор персистится между вызовами."""
    keys = nd.axis_keys()
    for _ in range(len(keys)):
        nd.rotate_focus(tmp_path, advance=True)
    assert (tmp_path / nd.FOCUS_CURSOR_REL).is_file(), "курсор ротации не сохранён"
    assert nd.read_focus_cursor(tmp_path) == keys[-1]
    assert nd.rotate_focus(tmp_path, advance=True) == keys[0], "ротация не замкнулась на первую ось"


@pytest.mark.unit
def test_peeking_the_focus_does_not_move_the_cursor(tmp_path):
    """Показ брифа (advance=False) НЕ двигает ротацию: иначе просмотр/подтверждение сдвигали бы фокус."""
    first = nd.rotate_focus(tmp_path, advance=False)
    again = nd.rotate_focus(tmp_path, advance=False)
    assert first == again, "заглядывание сдвинуло курсор"
    assert not (tmp_path / nd.FOCUS_CURSOR_REL).is_file(), "заглядывание записало состояние"


@pytest.mark.unit
def test_a_real_run_moves_the_focus_between_runs(repo):
    """Между реальными прогонами фокус двигается (курсор персистится в дочку)."""
    nr.run_nightly(repo, deliver=False)
    first = nd.read_focus_cursor(repo)
    nr.run_nightly(repo, deliver=False)
    second = nd.read_focus_cursor(repo)
    assert first and second and first != second, (first, second)


# ── (в) ОСЬ БЕЗ СИГНАЛА -> «НЕ НАБЛЮДАЕТСЯ», А НЕ «ОК» ─────────────────────────────────────────

@pytest.mark.unit
def test_an_axis_with_no_deterministic_signal_says_not_observed_not_ok():
    """Ось без детерминированной проверки (тесты, безопасность) — «не наблюдается», не «ок»."""
    groups = {g["key"]: g for g in nd.group_findings_by_axis([])}
    for key in ("tests", "security"):
        assert groups[key]["status"] == "не наблюдается", key
    lines = "\n".join(nd.format_dimensions(nd.group_findings_by_axis([])))
    assert "не наблюдается здесь" in lines
    assert "это «не смотрели»" in lines, "не названо, что тишина ≠ «всё хорошо»"


@pytest.mark.unit
def test_an_unchecked_axis_is_not_observed_not_clean():
    """Проверка оси не отработала (артефакта нет -> ok is None) — «не наблюдается», а не «чисто»."""
    groups = {g["key"]: g for g in nd.group_findings_by_axis(_findings(артефакты="unknown"))}
    assert groups["architecture"]["status"] == "не наблюдается", groups["architecture"]
    assert groups["architecture"]["findings"] == []


@pytest.mark.unit
def test_a_checked_axis_with_no_discrepancy_is_clean_distinct_from_not_observed():
    """Проверка оси ШЛА и расхождений нет — это «чисто», отдельное от «не наблюдается»."""
    groups = {g["key"]: g for g in nd.group_findings_by_axis(_findings(артефакты="good"))}
    assert groups["architecture"]["status"] == "чисто", groups["architecture"]


# ── (г) ОСЕВЫЕ СЧЁТЧИКИ ПИТАЮТ ТОТ ЖЕ НЕДЕЛЬНЫЙ ТРЕНД (не второй журнал) ───────────────────────

@pytest.mark.unit
def test_axis_counts_aggregate_checks_of_the_axis():
    """Счётчик оси = сумма расхождений её проверок; «не проверено» в счёт не идёт."""
    counts = nd.axis_finding_counts(
        _findings(документация=["bad", "bad"], ссылки="bad", артефакты="unknown"))
    assert counts["documentation"] == 3, counts
    assert "architecture" not in counts, "unknown не должен попадать в осевой счётчик"


@pytest.mark.unit
def test_axis_counts_feed_the_weekly_trend_through_the_same_journal(repo):
    """Осевые счётчики недельной давности сравниваются с сегодняшними — та же машинерия тренда."""
    week_ago = (datetime.now() - timedelta(days=7)).isoformat()
    old = _findings(документация="bad")
    nt.record_history(repo, old, at=week_ago, axis_counts=nd.axis_finding_counts(old))
    now_findings = _findings(документация=["bad", "bad", "bad"])
    trend = nt.compute_axis_trends(nt.read_history(repo), nd.axis_finding_counts(now_findings))
    row = next(r for r in trend["rows"] if r["check"] == "documentation")
    assert row["was"] == 1 and row["now"] == 3 and row["direction"] == "хуже", trend


@pytest.mark.unit
def test_axis_counts_live_in_the_review_history_file_not_a_second_journal(repo):
    """Осевые счётчики лежат в ТОМ ЖЕ файле истории обзора, а не в отдельном журнале."""
    findings = _findings(события="bad")
    nt.record_history(repo, findings, axis_counts=nd.axis_finding_counts(findings))
    assert (repo / nt.HISTORY_REL).is_file(), "единый журнал истории обзора не создан"
    entry = nt.read_history(repo)[-1]
    assert entry.get("axis_counts") == {"analytics": 1}, entry


@pytest.mark.unit
def test_a_run_records_axis_counts_and_brief_names_the_axis_trend(repo):
    """Реальный прогон пишет осевые счётчики в историю; бриф называет тренд по осям первоклассно."""
    delta = nr.collect_delta(repo)
    assert "axis_counts" in delta and "axis_trends" in delta
    brief = nr.format_brief(delta, repo)
    assert any("Тренд по осям" in ln for ln in brief.splitlines())
    nr.run_nightly(repo, deliver=False)
    assert "axis_counts" in nt.read_history(repo)[-1], "прогон не записал осевые счётчики в историю"
