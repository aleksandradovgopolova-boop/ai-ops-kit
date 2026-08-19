"""Заморозка новых умений исполняется проверкой, а не памятью.

Работа `capability-freeze-enforced`. Решение владельца `ep-2026-08-17-capability-freeze-until-second-brownfield`:
новое умение не принимается, пока исход `owner_reaches_verified_pr_without_patching_the_kit` не стал
верным. Оговорка: работа, снижающая цену процесса, замыкающая обратную связь из поля или закрывающая
найденный полем дефект, новым умением НЕ считается.

ПОВОД БЫЛ ЖИВОЙ, а не теоретический: 18.08.2026 кит САМ предложил взять
`watch-contract-for-night-review` — работу из замороженной цели, — потому что решение существовало
записью в реестре и ничем не сверялось. Совет, противоречащий решению владельца, хуже отсутствия
совета: он выглядит как санкция.

ЧТО ПРОВЕРЯЕТСЯ ЗДЕСЬ (четыре условия из плана работы):
  1. отношение к заморозке объявлено — на ЦЕЛИ, потому что оговорка сказана про назначение, а
     проверка по формулировке заявки была бы лазейкой через слова (это названо в самом решении);
  2. проверка плана краснеет, когда замороженная работа ВЗЯТА, и называет решение номером;
  3. `next` не предлагает замороженное и ГОВОРИТ об этом человеку;
  4. снятие заморозки — не дата и не флаг, а тот самый исход, ставший верным.
"""
import copy

import pytest

from ai_ops_kit.planning import contours as _contours
from ai_ops_kit.planning import delivery_plan as dp
from ai_ops_kit.ui import presenter

pytestmark = pytest.mark.unit


def _plan(*, reached=False, relation="extension", status="todo", exception=None):
    w = {"id": "wi-new-skill", "title": "Новое умение", "type": "engineering",
         "goal": "g-ext", "status": status, "owner_role": "engineer",
         "depends_on": [], "write_scope": ["src/"], "value": "high"}
    if exception is not None:
        w["freeze_exception"] = exception
    if status == "in_progress":
        w["branch"] = "ai-ops/wi-new-skill"
    return {
        "schema_version": 1, "kind": dp.KIND,
        "goals": [
            {"id": dp.FREEZE_GOAL, "status": "active", "freeze_relation": "run_condition",
             "outcome": {dp.FREEZE_OUTCOME: reached}},
            {"id": "g-ext", "status": "active", "freeze_relation": relation, "outcome": {}},
        ],
        "work": [w,
                 {"id": "wi-condition", "title": "Условие прогона", "type": "engineering",
                  "goal": dp.FREEZE_GOAL, "status": "todo", "owner_role": "engineer",
                  "depends_on": [], "write_scope": ["qualification/"], "value": "high"}],
    }


class TestFreezeStateIsDerivedNotDeclared:
    def test_frozen_while_the_outcome_is_false(self):
        st = dp.freeze_state(_plan(reached=False))
        assert st["frozen"] is True and st["readable"] is True
        assert st["decision"] == dp.FREEZE_DECISION

    def test_lifted_when_the_outcome_becomes_true(self):
        """Снятие — исход, ставший верным, а не дата и не ручной флаг."""
        st = dp.freeze_state(_plan(reached=True))
        assert st["frozen"] is False
        assert not dp.frozen_work(_plan(reached=True)), "заморозка не снялась вместе с исходом"

    def test_missing_outcome_is_fail_closed(self):
        """Удалить строку исхода не должно означать «заморозки нет»: иначе правило снимается
        правкой того же файла, который оно охраняет."""
        plan = _plan()
        plan["goals"][0]["outcome"] = {}
        st = dp.freeze_state(plan)
        assert st["frozen"] is True and st["readable"] is False
        assert "не прочитано" in st["reason"], st["reason"]

    def test_no_manual_flag_exists(self):
        """В коде не должно быть выключателя заморозки: снятие обязано идти через исход."""
        src = (dp.__file__ and open(dp.__file__, encoding="utf-8").read()) or ""
        for flag in ("freeze_disabled", "freeze_off", "FREEZE_ENABLED", "skip_freeze"):
            assert flag not in src, f"появился ручной выключатель заморозки: {flag}"


class TestTheRuleDoesNotLeakIntoChildPlans:
    """Заморозка — внутреннее решение о развитии КИТА. Требовать её классификацию от плана чужого
    продукта значило бы экспортировать свою политику в чужой CI.

    Поймано первым же полным прогоном: обязательный признак уронил 12 проверок, включая планы,
    которые кит САМ создаёт дочке (`bootstrap`), и шаблон плана. Признак применимости — наличие цели
    заморозки в плане: она есть только там, где решение принято.
    """

    def _child_plan(self):
        return {"schema_version": 1, "kind": dp.KIND,
                "goals": [{"id": "g-product", "status": "active", "outcome": {"users_can_export": False}}],
                "work": [{"id": "wi-export", "title": "Экспорт заказов", "type": "engineering",
                          "goal": "g-product", "status": "todo", "owner_role": "engineer",
                          "depends_on": [], "write_scope": ["src/"], "value": "high"}]}

    def test_plan_without_the_freeze_goal_is_not_frozen(self):
        st = dp.freeze_state(self._child_plan())
        assert st["applies"] is False and st["frozen"] is False
        assert "плану продукта" in st["reason"], st["reason"]
        assert dp.frozen_work(self._child_plan()) == {}

    def test_child_plan_is_not_required_to_classify_goals(self):
        errs = dp.validate(self._child_plan(), _contours.load_model())["errors"]
        assert not [e for e in errs if "freeze_relation" in e], errs

    def test_kit_plan_is_required_to_classify_goals(self):
        """Обратная половина: там, где решение принято, объявление обязательно."""
        plan = _plan()
        del plan["goals"][1]["freeze_relation"]
        errs = dp.validate(plan, _contours.load_model())["errors"]
        assert any("freeze_relation" in e for e in errs), errs


class TestExceptionIsCheckedAgainstTheGoal:
    def test_extension_goal_work_is_frozen(self):
        frozen = dp.frozen_work(_plan(relation="extension"))
        assert "wi-new-skill" in frozen
        assert dp.FREEZE_DECISION in frozen["wi-new-skill"], frozen["wi-new-skill"]

    def test_run_condition_goal_work_is_not_frozen(self):
        """КОНТРОЛЬ: оговорка обязана работать, иначе правило заблокировало бы ровно те работы,
        которые сокращают расстояние до прогона (это названо в решении)."""
        assert dp.frozen_work(_plan(relation="run_condition")) == {}

    def test_explicit_exception_with_reason_unfreezes_one_work(self):
        frozen = dp.frozen_work(_plan(exception="закрывает находку поля B2-19"))
        assert frozen == {}, frozen

    def test_empty_exception_does_not_unfreeze(self):
        """Пустое исключение — тихий обход, а не исключение."""
        frozen = dp.frozen_work(_plan(exception="   "))
        assert "wi-new-skill" in frozen


class TestValidationRedsWhereItMatters:
    def _validate(self, plan):
        return dp.validate(plan, _contours.load_model())

    def test_goal_without_relation_is_an_error(self):
        plan = _plan()
        del plan["goals"][1]["freeze_relation"]
        errs = self._validate(plan)["errors"]
        assert any("freeze_relation" in e and dp.FREEZE_DECISION in e for e in errs), errs

    def test_unknown_relation_is_an_error(self):
        plan = _plan(relation="возможно")
        errs = self._validate(plan)["errors"]
        assert any("freeze_relation" in e for e in errs), errs

    def test_taking_frozen_work_is_an_error_naming_the_decision(self):
        errs = self._validate(_plan(status="in_progress"))["errors"]
        assert any(dp.FREEZE_DECISION in e and "заморожена" in e for e in errs), errs

    def test_declaring_frozen_work_in_the_plan_is_allowed(self):
        """Объявлять замороженную работу МОЖНО: иначе план перестал бы описывать продукт, и
        замороженное просто исчезло бы из вида. Запрещено её ВЕСТИ."""
        errs = self._validate(_plan(status="todo"))["errors"]
        assert not [e for e in errs if "заморожена" in e], errs

    def test_empty_exception_is_an_error(self):
        errs = self._validate(_plan(exception=""))["errors"]
        assert any("без причины" in e for e in errs), errs

    def test_real_plan_of_this_repo_is_valid(self):
        """Контур на настоящем плане: классификация 14 целей проставлена и не ломает проверку."""
        plan = dp.load(".")
        v = dp.validate(plan, _contours.load_model(), closed=dp.load_history("."), root=".")
        assert v["errors"] == [], v["errors"]
        assert all(g.get("freeze_relation") in dp.FREEZE_RELATIONS for g in dp.goals(plan))


class TestNextDoesNotOfferFrozenWork:
    """ШОВ: правило существует ровно там, где кит советует. 18.08 он советовал замороженное."""

    def test_frozen_work_is_not_offered_and_is_named(self, tmp_path):
        rep = {"schema_version": 1, "plan_present": True, "plan_errors": [], "plan_warnings": [],
               "roadmap": {"errors": [], "warnings": []},
               "where_are_we": [], "in_progress": [], "blocked": [], "ready": [],
               "next_best": {"id": "wi-condition", "title": "Условие прогона", "owner_role": "engineer",
                             "score": 5, "why": ["работает на цель первого приоритета"], "unblocks": []},
               "parallel_with": [], "parallel_skipped": [], "not_ready": [],
               "held_by_others": [], "held_by_me": [], "holders_reach": {},
               "frozen": [{"id": "wi-new-skill", "title": "Новое умение", "reason": "цель — расширение"}],
               "freeze": {"frozen": True, "decision": dp.FREEZE_DECISION}}
        msg = presenter.from_next_work(rep)
        why = msg.get("why_it_matters") or ""
        assert "не предлагаю" in why, f"заморозка не названа человеку: {msg}"
        assert "расширение умений" in why, why
        payload = msg["technical_details"]["payload"]
        assert payload["заморожено"] == "wi-new-skill"
        assert payload["решение о заморозке"] == dp.FREEZE_DECISION

    def test_the_answer_is_unchanged_when_nothing_is_frozen(self):
        """КОНТРОЛЬ: без заморозки ответ не обрастает лишними словами."""
        rep = {"schema_version": 1, "plan_present": True, "plan_errors": [], "plan_warnings": [],
               "roadmap": {"errors": [], "warnings": []}, "where_are_we": [], "in_progress": [],
               "blocked": [], "ready": [], "parallel_with": [], "parallel_skipped": [],
               "not_ready": [], "held_by_others": [], "held_by_me": [], "holders_reach": {},
               "next_best": {"id": "wi-1", "title": "Работа", "owner_role": "engineer", "score": 3,
                             "why": ["ценность высокая"], "unblocks": []},
               "frozen": [], "freeze": {"frozen": False}}
        msg = presenter.from_next_work(rep)
        assert "не предлагаю" not in (msg.get("why_it_matters") or "")

    def test_real_repo_no_longer_offers_the_frozen_work(self):
        """На настоящем плане: та самая работа, которую кит предложил 18.08, больше не предлагается,
        а остальные предложения остались."""
        from ai_ops_kit.planning import next_work
        rep = next_work.compute(".", me="session:test")
        offered = {(rep["next_best"] or {}).get("id")} | {p["id"] for p in rep["parallel_with"]}
        frozen_ids = {f["id"] for f in rep["frozen"]}
        assert "watch-contract-for-night-review" in frozen_ids, rep["frozen"]
        assert not (offered & frozen_ids), f"замороженное всё ещё предлагается: {offered & frozen_ids}"
        assert rep["next_best"] is not None, "вычитание съело весь ответ"


class TestLiftingIsTheOutcomeNotAnEdit:
    def test_flipping_the_outcome_unfreezes_everything(self):
        plan = copy.deepcopy(dp.load("."))
        goal = next(g for g in plan["goals"] if g["id"] == dp.FREEZE_GOAL)
        assert dp.frozen_work(plan), "на настоящем плане заморозка не держится — проверять нечего"
        goal["outcome"][dp.FREEZE_OUTCOME] = True
        assert dp.frozen_work(plan) == {}, \
            "исход стал верным, а работы остались заморожены — снятие не связано с исходом"
