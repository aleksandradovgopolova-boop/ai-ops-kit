"""ШОВ: совет о следующей работе считается ПО ИСТОРИИ, а не только по активному плану.

ПОЧЕМУ ОТДЕЛЬНЫМ ФАЙЛОМ. `tests/unit/test_plan_control_plane.py` проверяет сам механизм: правила
плана и истории, вывод статусов. Он остался бы ЗЕЛЁНЫМ, если бы `next_work` историю не подавал, —
и ровно это произошло при разносе плана 14.08.2026: `ai-ops next` отказался советовать работу, потому
что `depends_on` смотрел на работу, уехавшую в историю, а неизвестная зависимость считается
блокирующей (и это верно). Механизм был исправен, шов — нет.

Замер того же дня объясняет, зачем это отдельный класс тестов: PR #118 прошёл пять кругов ревью, 36
находок, ни одну не поймали 11 джоб CI. Модульный тест проверяет, что механизм работает; шовный —
что его КТО-ТО ЗОВЁТ и что результат доезжает до человека.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from ai_ops_kit.planning import next_work as nw

PLAN = """\
schema_version: 1
kind: delivery-plan
goals:
  - id: g1
    status: active
work:
  - id: zavisimaya
    title: Работа, которая ждёт закрытую
    type: quality
    goal: g1
    status: todo
    owner_role: engineer
    depends_on: [ranshe-zakryta]
    write_scope: [src/]
    value: high
"""

HISTORY = """\
schema_version: 1
kind: delivery-plan-history
work:
  - id: ranshe-zakryta
    title: Работа, закрытая раньше
    goal: g1
    status: done
    closed_at: '2026-08-13'
    result: механизм выпущен и подтверждён полем
    commit: abc123abc123
"""

ROADMAP = """\
# ROADMAP

## Сейчас

- `g1` — направление, под которым идёт работа.

## Следующий результат

- `g1` — то же направление глазами пользователя.

## Дальше

- Крупное потом.

## Later

- Осознанно не берём.
"""


@pytest.fixture()
def repo(tmp_path):
    (tmp_path / "planning").mkdir()
    (tmp_path / "planning" / "plan.yaml").write_text(PLAN, encoding="utf-8")
    (tmp_path / "history").mkdir()
    (tmp_path / "history" / "plan-history.yaml").write_text(HISTORY, encoding="utf-8")
    (tmp_path / "ROADMAP.md").write_text(ROADMAP, encoding="utf-8")
    return tmp_path


def test_next_advises_work_whose_dependency_is_closed_in_history(repo):
    """ШОВ: `next_work.compute` видит историю — совет получен, а не отказ.

    Это НЕ дубль модульного теста: там проверялось, что `resolve` закрывает такую зависимость. Здесь
    проверяется, что до `resolve` вообще доехала история, то есть что шов собран.
    """
    rep = nw.compute(repo)

    assert rep["plan_errors"] == [], (
        f"совет невозможен: план объявлен недостоверным — {rep['plan_errors']}")
    assert (rep["next_best"] or {}).get("id") == "zavisimaya", rep.get("next_best")
    assert [w["id"] for w in rep["ready"]] == ["zavisimaya"]


def test_the_advice_reaches_the_human_text(repo):
    """Совет, доехавший только до JSON, — совет, которого человек не увидит.

    Тот же урок, что в B2-14: признание в `report.json` при молчащем выводе прогона равносильно
    отсутствию признания.
    """
    text = nw.render(nw.compute(repo))

    assert "Работа, которая ждёт закрытую" in text, text
    assert "ошибк" not in text.lower(), f"вывод говорит об ошибках плана: {text}"


def test_a_dependency_that_exists_nowhere_still_blocks(repo):
    """Граница шва: неизвестная зависимость по-прежнему блокирует.

    Подача истории не должна превратиться в «чего не нашли, то и закрыто»: это ослабило бы вывод
    статусов ровно там, где он единственная защита от совета взять работу, чьё основание не готово.
    """
    (repo / "history" / "plan-history.yaml").write_text(
        HISTORY.replace("ranshe-zakryta", "sovsem-drugaya"), encoding="utf-8")

    rep = nw.compute(repo)

    assert any("не резолвится" in e for e in rep["plan_errors"]), rep["plan_errors"]
    assert rep["next_best"] is None


def test_a_corrupt_history_does_not_silently_advise(repo):
    """Битая история не превращается в «зависимостей нет» на пути до человека.

    Здесь проверяется именно ШОВ отказа: `next_work` не обязан падать, но и советовать работу,
    основание которой не прочитано, он не имеет права.
    """
    (repo / "history" / "plan-history.yaml").write_text("kind: ne-istoriya\n", encoding="utf-8")

    rep = nw.compute(repo)

    assert rep["next_best"] is None, rep.get("next_best")
    assert rep["plan_errors"], "история не прочитана, а план объявлен достоверным"


def test_history_is_not_required_for_a_repo_without_it(tmp_path):
    """Молодой репозиторий без истории получает совет как обычно — правило не создаёт нового долга."""
    (tmp_path / "planning").mkdir()
    (tmp_path / "planning" / "plan.yaml").write_text(
        textwrap.dedent(PLAN).replace("    depends_on: [ranshe-zakryta]\n", "    depends_on: []\n"),
        encoding="utf-8")
    (tmp_path / "ROADMAP.md").write_text(ROADMAP, encoding="utf-8")

    rep = nw.compute(tmp_path)

    assert rep["plan_errors"] == [], rep["plan_errors"]
    assert (rep["next_best"] or {}).get("id") == "zavisimaya"
