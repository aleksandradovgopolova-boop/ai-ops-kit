# -*- coding: utf-8 -*-
"""Roadmap Now/Next/Later ВЫВОДИТСЯ из плана и краснеет при расхождении с авторским ROADMAP.md.

Работа `roadmap-now-next-later`, цель `roadmap-and-delivery` (PR-7).

Проверки — на ФИКСТУРЕ-плане, не на живом (урок 20.08.2026: тест, зависящий от состояния живого
плана, тихо перестаёт проверять, когда план меняется). Здесь вход — dict, выход — детерминирован.

Три обязательных теста на capability (AGENTS.md):
  * positive     — горизонты выводятся из исходов и состояния работ так, как задумано;
  * fail-closed  — расхождение авторского горизонта с выведенным даёт отклонение, названное поимённо;
  * side-effect  — «нет авторского ROADMAP.md» ≠ «расхождений нет»: третье состояние не глотается.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[2]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))

from ai_ops_kit.planning import roadmap_manager as rm   # noqa: E402

pytestmark = pytest.mark.unit


def _plan():
    """Фикстура из четырёх направлений — по одному на каждый выводимый горизонт."""
    return {
        "schema_version": 1,
        "kind": "delivery-plan",
        "goals": [
            # NOW: под цель идёт работа in_progress.
            {"id": "g-now", "title": "Идёт сейчас", "status": "active",
             "outcome": {"a": False, "b": False}},
            # NEXT: работа есть, но ждёт закрытия зависимости из g-now.
            {"id": "g-next", "title": "Ждёт", "status": "active",
             "outcome": {"a": False}},
            # LATER: исходов ноль, работ под цель нет.
            {"id": "g-later", "title": "Не начато", "status": "active",
             "outcome": {"a": False, "b": False}},
            # SHIPPED: все исходы достигнуты.
            {"id": "g-done", "title": "Готово", "status": "active",
             "outcome": {"a": True, "b": True}},
        ],
        "work": [
            {"id": "w-now", "goal": "g-now", "status": "in_progress"},
            {"id": "w-next", "goal": "g-next", "status": "todo", "depends_on": ["w-now"]},
        ],
    }


def test_horizons_derived_from_outcomes_and_work_state():
    """positive: каждый горизонт содержит ровно то направление, что задумано входом."""
    r = rm.build(_plan())
    assert [d.goal_id for d in r.horizon(rm.NOW)] == ["g-now"]
    assert [d.goal_id for d in r.horizon(rm.NEXT)] == ["g-next"]
    assert [d.goal_id for d in r.horizon(rm.LATER)] == ["g-later"]
    assert [d.goal_id for d in r.horizon(rm.SHIPPED)] == ["g-done"]

    now = r.horizon(rm.NOW)[0]
    assert (now.reached, now.total) == (0, 2)
    assert now.active_work == 1 and now.blocked_work == 0

    nxt = r.horizon(rm.NEXT)[0]
    assert nxt.blocked_work == 1          # работа заблокирована незакрытой зависимостью
    assert "зависим" in nxt.note

    done = r.horizon(rm.SHIPPED)[0]
    assert (done.reached, done.total) == (2, 2)


def test_ready_work_without_deps_is_now():
    """Готовая к взятию работа (deps закрыты) кладёт направление в Now, а не в Next."""
    plan = {
        "goals": [{"id": "g", "outcome": {"x": False}}],
        "work": [{"id": "w", "goal": "g", "status": "todo", "depends_on": ["closed-1"]}],
    }
    # Зависимость закрыта в истории — работа готова, горизонт Now.
    r = rm.build(plan, history=[{"id": "closed-1"}])
    assert [d.goal_id for d in r.horizon(rm.NOW)] == ["g"]
    # А без закрытия зависимости — Next (заблокирована).
    r2 = rm.build(plan)
    assert [d.goal_id for d in r2.horizon(rm.NEXT)] == ["g"]


def test_deviation_flags_authored_horizon_mismatch():
    """fail-closed: авторский горизонт расходится с выведенным — отклонение названо поимённо."""
    r = rm.build(_plan())
    # Авторский ROADMAP.md: активное направление задвинуто в Later, готовое — обещано под Now.
    authored = {
        "now": {"goals": ["g-done"]},          # завершённое обещано как незакрытое
        "next_outcome": {"goals": ["g-later"]},  # не начатое обещано ближе, чем движется работа
        "later_major": {"goals": ["g-now"]},   # активное задвинуто дальше своего горизонта
        "someday": {"goals": []},
    }
    devs = rm.deviations(r, authored)
    joined = "\n".join(devs)
    assert "g-now" in joined and "опережает" in joined
    assert "g-later" in joined and "раньше" in joined
    assert "g-done" in joined and "достигнут" in joined
    # Согласованный авторский файл (горизонты совпадают с выведенными) — ноль отклонений.
    aligned = {
        "now": {"goals": ["g-now"]},
        "next_outcome": {"goals": ["g-next"]},
        "later_major": {"goals": ["g-later"]},
        "someday": {"goals": []},
    }
    assert rm.deviations(r, aligned) == []


def test_deviations_speak_human_without_raw_horizon_slugs():
    """P2: человеку не показывают сырой горизонт 'now'/'next'/'later' и голый счётчик «0/2».

    Отклонение — это главный текст, который читает не-разработчик. Раньше в нём стоял технический
    горизонт («по плану горизонт 'next'») и голая дробь исходов. Проверяем, что подача человеческая:
    горизонт назван словами, счётчик развёрнут, а логика (какие цели помечены) не изменилась.
    """
    r = rm.build(_plan())
    authored = {
        "now": {"goals": ["g-done"]},
        "next_outcome": {"goals": ["g-later"]},
        "later_major": {"goals": ["g-now"]},
        "someday": {"goals": []},
    }
    joined = "\n".join(rm.deviations(r, authored))
    # Ни одного сырого слага горизонта в кавычках — только человеческие формулировки.
    for raw in ("горизонт 'now'", "горизонт 'next'", "горизонт 'later'",
                "'now'", "'next'", "'later'"):
        assert raw not in joined, f"сырой термин просочился к человеку: {raw!r}"
    # Термины поданы словами и счётчик развёрнут.
    assert "запланировано следующим" in joined or "пока не взято в работу" in joined
    assert "результатов" in joined


def test_humanize_outcomes_reads_as_a_sentence():
    """Счётчик исходов разворачивается в предложение; пустой набор назван честно, не «0/0»."""
    assert rm.humanize_outcomes(0, 2) == "достигнуто 0 из 2 результатов"
    assert rm.humanize_outcomes(1, 3) == "достигнуто 1 из 3 результатов"
    assert "0/0" not in rm.humanize_outcomes(0, 0)
    assert rm.humanize_outcomes(0, 0) == "результаты пока не заданы"


def test_no_authored_file_is_not_no_deviation():
    """side-effect: отсутствие авторского ROADMAP.md — «сверять нечего», а не «расхождений нет»."""
    r = rm.build(_plan())
    # deviations на None возвращает пусто — но check ниже сообщает это ТРЕТЬИМ состоянием, не зелёным.
    assert rm.deviations(r, None) == []


def test_check_reports_missing_authored_as_third_state(tmp_path):
    """check на репо без ROADMAP.md: authored_present=False — состояние названо, не подменено."""
    (tmp_path / "planning").mkdir()
    import yaml
    (tmp_path / "planning" / "plan.yaml").write_text(
        yaml.safe_dump({"kind": "delivery-plan", "goals": _plan()["goals"],
                        "work": _plan()["work"]}, allow_unicode=True),
        encoding="utf-8",
    )
    rep = rm.check(tmp_path)
    assert rep["authored_present"] is False
    assert rep["deviations"] == []
    assert rep["roadmap"]["now"][0]["goal"] == "g-now"


def test_render_is_parseable_by_authored_validator():
    """Сгенерированный ROADMAP.md читается авторским парсером `roadmap.parse` — один шов, не два."""
    from ai_ops_kit.planning import roadmap as authored
    md = rm.render_markdown(rm.build(_plan()))
    parsed = authored.parse(md)
    assert "g-now" in parsed["now"]["goals"]
    assert "g-next" in parsed["next_outcome"]["goals"]
    assert "g-later" in parsed["later_major"]["goals"]
