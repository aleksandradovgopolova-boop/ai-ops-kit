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

    def test_nothing_frozen_is_ever_offered(self):
        """На настоящем плане: что заморозка вычла, то не предлагается — сколько бы этого ни было.

        ПЕРЕПИСАН 19.08.2026. Прежде тест требовал, чтобы на настоящем плане была КОНКРЕТНАЯ
        замороженная работа (`watch-contract-for-night-review`). Заморозку сняли решением
        владельца 19.08, работу закрыли — и тест стал падать не потому, что механизм сломан, а
        потому, что был привязан к состоянию плана на один день. Инвариант же не в том, что
        что-то заморожено, а в том, что ЗАМОРОЖЕННОЕ НЕ ПРЕДЛАГАЕТСЯ. Его и проверяем; сила
        механизма на непустом множестве доказана отдельно, на фикстуре.
        """
        from ai_ops_kit.planning import next_work
        rep = next_work.compute(".", me="session:test")
        offered = {(rep["next_best"] or {}).get("id")} | {p["id"] for p in rep["parallel_with"]}
        frozen_ids = {f["id"] for f in rep["frozen"]}
        assert not (offered & frozen_ids), f"замороженное всё ещё предлагается: {offered & frozen_ids}"

        # ПУСТОЙ ОТВЕТ ЗАКОНЕН, НО ОБЯЗАН БЫТЬ ОБЪЯСНЁН. Второй раз за два дня этот тест падает не
        # потому, что механизм сломан, а потому, что был привязан к состоянию плана: 19.08 он
        # требовал КОНКРЕТНУЮ замороженную работу, сегодня — чтобы предложить было ВСЕГДА что.
        # Замер 20.08.2026: в плане осталось две работы, одна идёт у владельца, вторая ждёт его же
        # решения по своему условию. Предлагать нечего — и это правильный ответ, а не поломка.
        #
        # Настоящий инвариант не «ответ непустой», а «вычитание не молчит»: если предложить нечего,
        # человеку названо, ЧТО именно мешает. Молчаливое «ничего» и «ничего, потому что вот это» —
        # разные ответы, и путать их здесь опаснее всего: план выглядел бы исчерпанным.
        withheld = (rep.get("blocked") or []) + (rep.get("held") or [])
        assert rep["next_best"] is not None or withheld, (
            "предложить нечего и НЕ СКАЗАНО почему — вычитание съело ответ молча")
        for w in withheld:
            assert w.get("reasons") or w.get("blocked_by"), (
                f"работа {w.get('id')} удержана без названной причины")


class TestLiftingIsTheOutcomeNotAnEdit:
    """Снять заморозку можно ДВУМЯ способами, и они не подменяют друг друга.

    (1) исход стал верным — так задумано изначально;
    (2) решение человека, названное явно (`freeze_lifted_by`) — добавлено 19.08.2026, потому что
        владелец снял заморозку до достижения условия, и записать это было НЕЧЕМ, кроме как
        поставив исход верным. Исход при этом стережёт канал `stable`, то есть решение о процессе
        молча переписывало факт о продукте.
    Проверяется на ФИКСТУРЕ, а не на настоящем плане: настоящий план меняется каждый день, и тест,
    привязанный к его сегодняшнему состоянию, ломается от честной работы.
    """

    def _frozen_plan(self):
        return {"schema_version": 1, "kind": dp.KIND,
                "goals": [{"id": dp.FREEZE_GOAL, "freeze_relation": "run_condition",
                           "outcome": {dp.FREEZE_OUTCOME: False}},
                          {"id": "g-ext", "freeze_relation": "extension"}],
                "work": [{"id": "wi-new-skill", "goal": "g-ext", "status": "todo"}]}

    def test_flipping_the_outcome_unfreezes_everything(self):
        plan = copy.deepcopy(self._frozen_plan())
        assert dp.frozen_work(plan), "фикстура не заморожена — проверять нечего"
        next(g for g in plan["goals"] if g["id"] == dp.FREEZE_GOAL)["outcome"][dp.FREEZE_OUTCOME] = True
        assert dp.frozen_work(plan) == {}, \
            "исход стал верным, а работы остались заморожены — снятие не связано с исходом"

    def test_an_explicit_decision_lifts_the_freeze_without_touching_the_outcome(self):
        plan = copy.deepcopy(self._frozen_plan())
        goal = next(g for g in plan["goals"] if g["id"] == dp.FREEZE_GOAL)
        goal[dp.FREEZE_LIFT_FIELD] = "ep-2026-08-19-freeze-lifted"
        st = dp.freeze_state(plan)
        assert st["frozen"] is False, "решение названо, а заморозка держится"
        assert st["lifted_by"] == "ep-2026-08-19-freeze-lifted"
        assert st["outcome_reached"] is False, "исход подменён снятием — ровно то, что развязывали"
        assert "НЕ достигнут" in st["reason"], \
            "снятие решением не отличимо от достигнутого исхода в человеческом ответе"
        assert goal["outcome"][dp.FREEZE_OUTCOME] is False, "снятие переписало факт"

    def test_the_real_plan_does_not_claim_an_outcome_it_has_not_reached(self):
        """Настоящий план: если заморозка снята решением — исход обязан остаться фактом.

        Это и есть та ошибка, ради которой поле заведено: 19.08 исход стоял `true` при
        `verified PR = 0` и пустом `field_evidence`, а он стережёт канал `stable`.
        """
        plan = dp.load(".")
        st = dp.freeze_state(plan)
        if st.get("lifted_by"):
            assert st["outcome_reached"] is False or _outcome_has_evidence(), (
                "исход объявлен достигнутым вместе со снятием решением — если он ДЕЙСТВИТЕЛЬНО "
                "достигнут, заполните registry/release-claims.yaml -> field_evidence")


def _outcome_has_evidence():
    """Достигнутый исход обязан иметь полевое доказательство — иначе это объявление."""
    import yaml as _y
    from pathlib import Path as _P
    p = _P("registry/release-claims.yaml")
    if not p.is_file():
        return False
    return bool((_y.safe_load(p.read_text(encoding="utf-8")) or {}).get("field_evidence"))


class TestLiftingByOutcomeNeedsProvenEvidence:
    """P0 (аудит 04.09.2026): исход, снимающий заморозку, — ручная булева декларация. Заморозку
    держит `bool(outcome[FREEZE_OUTCOME])`, и снять её можно было, вписав `true` без единого
    доказательства (класс F-002/F-005). `validate` теперь требует у снимающего заморозку исхода
    полевое доказательство (`registry/release-claims.yaml -> field_evidence`), как история требует у
    `done` место перепроверки. НЕ у всех исходов — только у того, что ГАСИТ заморозку.

    Проверяется на ФИКСТУРЕ с временным корнем: настоящий план меняется каждый день, и настоящий
    `field_evidence` непуст (там это проверяет `test_real_plan_of_this_repo_is_valid`).
    """

    def _write_evidence(self, root):
        (root / "registry").mkdir(parents=True, exist_ok=True)
        (root / "registry" / "release-claims.yaml").write_text(
            "field_evidence:\n  - repo: some-child\n    outcome: ok\n", encoding="utf-8")

    def _errs(self, plan, root):
        return dp.validate(plan, _contours.load_model(), root=str(root))["errors"]

    def _self_declared(self, e):
        return dp.FREEZE_OUTCOME in e and "field_evidence" in e and "самодекларация" in e

    def test_true_without_evidence_is_an_error(self, tmp_path):
        """`true` без доказательства — снятие заморозки самодекларацией. Это дефект P0."""
        errs = self._errs(_plan(reached=True), tmp_path)
        assert any(self._self_declared(e) for e in errs), errs

    def test_true_with_resolving_evidence_is_valid(self, tmp_path):
        """Тот же `true`, но с резолвящимся полевым доказательством — валидно."""
        self._write_evidence(tmp_path)
        errs = self._errs(_plan(reached=True), tmp_path)
        assert not any(self._self_declared(e) for e in errs), errs

    def test_false_needs_no_evidence(self, tmp_path):
        """Заморозка держится (исход `false`) — доказательства не требуется, проверка не бьёт."""
        errs = self._errs(_plan(reached=False), tmp_path)
        assert not any(self._self_declared(e) for e in errs), errs

    def test_child_plan_without_freeze_goal_is_never_touched(self, tmp_path):
        """Правило внутреннее для кита: план без цели заморозки проверка не трогает даже без
        доказательства (иначе кит экспортировал бы свою политику в чужой CI)."""
        child = {"schema_version": 1, "kind": dp.KIND,
                 "goals": [{"id": "g-product", "status": "active", "outcome": {"x": True}}],
                 "work": [{"id": "wi", "title": "Работа", "type": "engineering", "goal": "g-product",
                           "status": "todo", "owner_role": "engineer", "depends_on": [],
                           "write_scope": ["src/"], "value": "high"}]}
        errs = self._errs(child, tmp_path)
        assert not any("field_evidence" in e for e in errs), errs

    def test_without_root_the_check_is_silent(self):
        """Без корня доказательство негде резолвить — проверка молчит, как и прочие ссылочные."""
        errs = dp.validate(_plan(reached=True), _contours.load_model())["errors"]
        assert not any(self._self_declared(e) for e in errs), errs
