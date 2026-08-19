"""Совет не ставит работу закрытой цели впереди живых (замер 19.08.2026).

ЗАМЕР, С КОТОРОГО НАЧАЛОСЬ. Первой целью плана стоит `real-product-qualification` со
`status: achieved`. `next` три раза подряд советовал её работу со словами «работает на цель первого
приоритета» — обходя P1-находки живого прогона, заведённые в тот же день и лежавшие под живыми
целями. Причина: приоритет считался ИНДЕКСОМ цели в файле, а `status` читался только для показа
(`where_are_we`, `next_work.py:306`).

ПОЧЕМУ ЭТО ДЕФЕКТ СОВЕТА, А НЕ ПЛАНА. План был неаккуратен (работа осталась на закрытой цели), но
механизм обязан переживать неаккуратность: достигнутая цель — не «самое важное направление», а
направление, которое больше никуда не ведёт. Совет, который этого не различает, тем убедительнее,
чем он неправее — он называет причину «цель первого приоритета».

ЧЕГО ПРАВКА НЕ ДЕЛАЕТ: работа под закрытой целью НЕ ИСЧЕЗАЕТ из кандидатов. Исчезновение было бы
тем же молчанием, которое запрещено заморозке умений. Она опускается и получает вслух названную
причину.
"""
from __future__ import annotations

import pathlib

import yaml

from ai_ops_kit.planning import delivery_plan as P
from ai_ops_kit.planning import next_work as N

REPO = pathlib.Path(__file__).resolve().parents[2]


def _repo(tmp_path, work, goals, roadmap_goals):
    (tmp_path / "planning").mkdir(parents=True, exist_ok=True)
    (tmp_path / "planning" / "plan.yaml").write_text(yaml.safe_dump(
        {"schema_version": 1, "kind": "delivery-plan", "goals": goals, "work": work},
        allow_unicode=True, sort_keys=False), encoding="utf-8")
    lines = ["# ROADMAP", "", "## Сейчас", ""]
    lines += [f"- `{g}` — пользователь получает результат" for g in roadmap_goals]
    lines += ["", "## Следующий результат", "", "- `next-thing` — пользователь может большее", "",
              "## Дальше", "", "- крупная возможность", "", "## Later", "", "- идея — не сейчас"]
    (tmp_path / "ROADMAP.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tmp_path


def _item(wid, goal, **kw):
    base = {"id": wid, "title": f"работа {wid}", "type": "engineering", "goal": goal,
            "status": "todo", "owner_role": "engineer", "depends_on": [],
            "write_scope": [f"src/{wid}/"], "value": "high"}
    base.update(kw)
    return base


CLOSED_FIRST = [{"id": "done-goal", "status": "achieved", "outcome": {"reached": True}},
                {"id": "live-goal", "status": "active", "outcome": {"works": False}}]


# ── порядок целей ─────────────────────────────────────────────────────────────────────────────

def test_achieved_goal_ranks_below_a_live_one_declared_later():
    plan = {"goals": CLOSED_FIRST, "work": []}
    prio = P.goal_priority(plan)
    assert prio["live-goal"] < prio["done-goal"], prio


def test_paused_goal_also_ranks_below_live():
    plan = {"goals": [{"id": "paused-goal", "status": "paused"},
                      {"id": "live-goal", "status": "active"}], "work": []}
    prio = P.goal_priority(plan)
    assert prio["live-goal"] < prio["paused-goal"], prio


def test_declared_order_still_decides_among_live_goals():
    """Контроль: порядок в файле остаётся приоритетом — правка сузила его, а не отменила."""
    plan = {"goals": [{"id": "a", "status": "active"}, {"id": "b", "status": "active"},
                      {"id": "c"}], "work": []}
    prio = P.goal_priority(plan)
    assert prio["a"] < prio["b"] < prio["c"], prio


def test_unknown_status_is_treated_as_live_and_caught_by_validate():
    """Опечатка не переставляет план молча: приоритет не меняется, а ошибку называет `validate`."""
    plan = {"schema_version": 1, "kind": "delivery-plan",
            "goals": [{"id": "typo", "status": "acheived"}, {"id": "live", "status": "active"}],
            "work": []}
    assert P.goal_priority(plan)["typo"] < P.goal_priority(plan)["live"]
    errs = P.validate(plan)["errors"]
    assert any("acheived" in e and "typo" in e for e in errs), errs


def test_known_statuses_are_not_an_error():
    """Контроль: живые/паузные/достигнутые цели проверку проходят."""
    plan = {"schema_version": 1, "kind": "delivery-plan",
            "goals": [{"id": g, "status": st} for g, st in
                      (("a", "active"), ("b", "paused"), ("c", "achieved"), ("d", None))],
            "work": []}
    assert not [e for e in P.validate(plan)["errors"] if "status" in e]


# ── совет ─────────────────────────────────────────────────────────────────────────────────────

def test_advice_prefers_the_live_goal(tmp_path):
    """ШОВ: две одинаково ценные работы, первая — под достигнутой целью. Советуется вторая."""
    r = _repo(tmp_path,
              [_item("w-done", "done-goal"), _item("w-live", "live-goal")],
              CLOSED_FIRST, ("done-goal", "live-goal"))
    rep = N.compute(r)
    assert rep["next_best"]["id"] == "w-live", rep["next_best"]
    # и «цель первого приоритета» больше не говорится про работу закрытой цели — именно эта фраза
    # делала неверный совет убедительным
    closed = next(x for x in rep["ready"] if x["id"] == "w-done")
    assert not any("первого приоритета" in w for w in closed["why"]), closed["why"]


def test_work_under_a_closed_goal_does_not_disappear(tmp_path):
    """Граница: работа остаётся кандидатом, и причина её низкого приоритета названа вслух."""
    r = _repo(tmp_path,
              [_item("w-done", "done-goal"), _item("w-live", "live-goal")],
              CLOSED_FIRST, ("done-goal", "live-goal"))
    rep = N.compute(r)
    row = next(x for x in rep["ready"] if x["id"] == "w-done")
    assert any("не ведёт вперёд" in w for w in row["why"]), row["why"]


def test_only_closed_goals_left_still_gets_advice(tmp_path):
    """Контроль fail-open: если ЖИВЫХ целей нет, совет не пропадает — он всё ещё называет работу."""
    r = _repo(tmp_path, [_item("w-done", "done-goal")],
              [CLOSED_FIRST[0]], ("done-goal",))
    rep = N.compute(r)
    assert rep["next_best"] and rep["next_best"]["id"] == "w-done"


# ── шов на НАСТОЯЩЕМ плане репозитория ────────────────────────────────────────────────────────

def test_real_plan_is_not_advised_from_a_closed_goal():
    """Дефект был найден на ЭТОМ плане, поэтому здесь он и сторожится.

    До правки `next` на настоящем плане советовал работу цели `real-product-qualification`
    (`status: achieved`) со словами «работает на цель первого приоритета»."""
    rep = N.compute(REPO)
    best = rep.get("next_best")
    assert best, rep.get("gap")
    plan = yaml.safe_load((REPO / "planning" / "plan.yaml").read_text(encoding="utf-8"))
    goal = next(w["goal"] for w in plan["work"] if w["id"] == best["id"])
    assert P.goal_is_live(plan, goal), (
        f"советуется работа '{best['id']}' под нежвой целью '{goal}'")


def test_real_plan_has_no_work_left_on_a_closed_goal():
    """Гигиена самого плана: работа под достигнутой целью — это забытая работа, а не приоритет."""
    plan = yaml.safe_load((REPO / "planning" / "plan.yaml").read_text(encoding="utf-8"))
    stray = [w["id"] for w in plan["work"] if not P.goal_is_live(plan, w.get("goal"))]
    assert not stray, f"работы остались под закрытыми целями: {stray}"
