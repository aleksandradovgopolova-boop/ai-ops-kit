"""ДЕФЕКТ: `waiting_on_owner`-работы проваливались мимо всех веток категоризации в `next_work.compute()`.

`resolve()` (`ai_ops_kit/planning/delivery_plan.py`) отдаёт статус `waiting_on_owner` как
ОБЪЯВЛЕННЫЙ факт — «механизм готов, ждём названного шага владельца» (см. `plan_model.py`,
`OWNER_WAIT_STATUS`). Цикл категоризации в `compute()` проверял только `in_progress`,
`blocked`/`waiting` и `ready` — статус `waiting_on_owner` не совпадал ни с одним условием и молча
выпадал из `in_progress`/`blocked`/`ready`/`not_ready` разом: ни один из четырёх списков ответа
не содержал такую работу.

Пока в плане была хоть одна `in_progress`-работа, пропажа маскировалась (`withheld` в
`test_next_skips_achieved_goals.py`/`test_capability_freeze_enforced.py` не был пуст по другой
причине). Но если ВСЕ оставшиеся активные работы — `waiting_on_owner`, `next_best` становится
`None`, и раньше НИЧЕГО не объясняло почему: кит отвечал «предложить нечего» без единого слова о
том, что дело — за владельцем. Ровно то молчание, против которого стоит инвариант «пустой совет
обязан быть объяснён» (см. `test_nothing_frozen_is_ever_offered`).

Правка: `waiting_on_owner`-работы попадают в новый список `held` (семантически — «удержано,
ждёт владельца», а не «заблокировано графом» и не «идёт сейчас»), с полем `waiting_on` — тем же
текстом, что назвал человек в плане. `render()` проговаривает их вслух в разделах 3 и 4.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.planning import next_work as N

PLAN = """schema_version: 1
kind: delivery-plan
goals:
  - id: g1
    status: active
work:
  - id: wi-waits-on-merge-queue
    title: Требовать merge queue в настройках GitHub
    type: engineering
    goal: g1
    status: waiting_on_owner
    waiting_on: включить «Require merge queue» в настройках ветки main
    owner_role: engineer
    depends_on: []
    write_scope: [.github/]
    value: high
  - id: wi-waits-on-budget-call
    title: Согласовать бюджет второго проекта
    type: engineering
    goal: g1
    status: waiting_on_owner
    waiting_on: назвать бюджет токенов на второй продукт
    owner_role: engineer
    depends_on: []
    write_scope: [registry/]
    value: medium
"""

ROADMAP = (
    "# Направление продукта\n\n## Сейчас\n- `g1` — довести настройку до конца\n\n"
    "## Следующий результат\n- владелец подтверждает готовность\n\n"
    "## Дальше\n- следующая цель\n\n## Не берём\n- мобильное приложение\n"
)


@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / "planning").mkdir(parents=True)
    (root / "planning" / "plan.yaml").write_text(PLAN, encoding="utf-8")
    (root / "ROADMAP.md").write_text(ROADMAP, encoding="utf-8")
    return root


def test_all_work_waiting_on_owner_yields_no_next_best_but_names_why(repo):
    """Шов из живого триггера: ВСЕ активные работы — `waiting_on_owner` -> `next_best` None,
    но ответ не молчит — он называет удержанные работы и их `waiting_on`."""
    rep = N.compute(repo)

    assert rep["next_best"] is None, rep["next_best"]

    # ни одна работа не потерялась: обе видны, и именно в `held`, а не растворились между
    # `in_progress`/`blocked`/`ready`/`not_ready`
    for bucket in ("in_progress", "blocked", "ready", "not_ready"):
        ids = {r["id"] for r in rep[bucket]}
        assert not ids & {"wi-waits-on-merge-queue", "wi-waits-on-budget-call"}, \
            f"waiting_on_owner работа осела в '{bucket}', а не в 'held': {ids}"

    held = rep.get("held") or []
    held_ids = {r["id"] for r in held}
    assert held_ids == {"wi-waits-on-merge-queue", "wi-waits-on-budget-call"}, held

    by_id = {r["id"]: r for r in held}
    assert by_id["wi-waits-on-merge-queue"]["waiting_on"] == \
        "включить «Require merge queue» в настройках ветки main"
    assert by_id["wi-waits-on-budget-call"]["waiting_on"] == \
        "назвать бюджет токенов на второй продукт"

    # инвариант, проверяемый и в test_next_skips_achieved_goals.py /
    # test_capability_freeze_enforced.py: пустой совет засчитывается только если названо, что
    # именно удержано.
    withheld = (rep.get("blocked") or []) + (rep.get("held") or []) + (rep.get("in_progress") or [])
    assert withheld, "предложить нечего и НЕ СКАЗАНО почему — вычитание съело ответ молча"
    for w in withheld:
        assert w.get("reasons") or w.get("blocked_by") or w.get("status") == "in_progress", \
            f"работа {w.get('id')} удержана без названной причины"

    # причина в `reasons` — та, что назвал человек в `waiting_on`, а не общая фраза
    reasons_text = " ".join(x for r in held for x in r["reasons"])
    assert "Require merge queue" in reasons_text
    assert "бюджет токенов" in reasons_text


def test_render_speaks_the_held_work_aloud(repo):
    """`render()`: пустой раздел 4 называет удержанные работы по имени и их `waiting_on`."""
    rep = N.compute(repo)
    text = N.render(rep)

    assert "взять нечего" in text
    assert "wi-waits-on-merge-queue" in text
    assert "wi-waits-on-budget-call" in text
    assert "включить «Require merge queue»" in text
    assert "назвать бюджет токенов" in text
