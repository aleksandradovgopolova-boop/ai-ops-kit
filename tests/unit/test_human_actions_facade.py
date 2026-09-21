"""Фасад владельца (P1 №8/№9 ревью): 7 действий человеческим языком поверх 34 intents.

Инвариант: фасад — СЛОЙ поверх INTENTS, не замена. 7 глаголов роутят на РАБОТАЮЩИЕ внутренние пути
(существующий intent / RESEARCH-воркфлоу / полный обзор продукта), 34 intents работают как раньше,
len(INTENTS) не меняется, а описания честны (безопасность в review; человек подтверждает выпуск;
feedback — про сам кит). Тесты видны красным на прежнем состоянии (фасада не было).
"""
from __future__ import annotations

import json

import pytest

from ai_ops_kit.cli import ai_ops_cli
from ai_ops_kit.cli.ai_ops_cli import HUMAN_ACTIONS, INTENTS, facade_plan, main

pytestmark = pytest.mark.unit

FINAL_ORDER = ["research", "start", "check", "work", "review", "release", "feedback"]


class TestSevenActionsDeclared:
    def test_exactly_seven_in_fixed_order(self):
        assert list(HUMAN_ACTIONS) == FINAL_ORDER

    def test_each_entry_has_required_shape(self):
        for verb, spec in HUMAN_ACTIONS.items():
            assert set(("intents", "mode", "needs_task", "label")) <= set(spec), verb
            assert spec["mode"] in ("primary", "all"), verb
            assert isinstance(spec["needs_task"], bool)
            assert spec["intents"], f"{verb}: не назван ни один внутренний intent"

    def test_every_target_intent_exists(self):
        """Каждый внутренний target фасада — реальный intent (фасад не обещает несуществующего)."""
        for verb, spec in HUMAN_ACTIONS.items():
            for tgt in spec["intents"]:
                assert tgt in INTENTS, f"{verb} -> {tgt}: такого intent нет в реестре"

    def test_intents_count_untouched_by_the_facade(self):
        """Фасад — слой ПОВЕРХ: число intents = 37 (замок числа команд не сломан фасадом)."""
        assert len(INTENTS) == 37


class TestRoutingIsToWorkingPaths:
    def test_start_routes_to_specify(self):
        assert facade_plan(["start", "хочу X"]) == [["specify", "хочу X"]]

    def test_release_routes_to_delivery(self):
        assert facade_plan(["release", "."]) == [["delivery", "."]]

    def test_check_is_readonly_owner_overview_status_inbox_next(self):
        plan = facade_plan(["check", "."])
        assert [p[0] for p in plan] == ["status", "inbox", "next"]

    def test_work_freetext_routes_to_run(self):
        assert facade_plan(["work", "добавь экспорт"]) == [["run", "добавь экспорт"]]

    def test_work_show_stays_projection_intent(self):
        """`work show <id>` — read-only проекция intent `work`, НЕ фасадное «делай»."""
        assert facade_plan(["work", "show", "wi-1"]) is None
        assert facade_plan(["work", ".", "show", "wi-1"]) is None  # каталог в начале (обёртка)

    def test_review_plain_is_the_intent(self):
        """`review` без `all` — обычный intent review (конкретное изменение)."""
        assert facade_plan(["review"]) is None
        assert facade_plan(["review", "."]) is None

    def test_feedback_is_the_intent(self):
        assert facade_plan(["feedback", "кит соврал про green"]) is None

    def test_research_routes_to_run_with_research_task_type(self):
        """research НЕ intent: запуск RESEARCH-воркфлоу через run + task_type=research (ai_route)."""
        plan = facade_plan(["research", "стоит ли брать Postgres?"])
        assert len(plan) == 1 and plan[0][0] == "run"
        i = plan[0].index("--signals")
        assert json.loads(plan[0][i + 1])["task_type"] == "research"

    def test_research_respects_explicit_signals_task_type(self):
        """Если владелец уже задал task_type — фасад его не перетирает."""
        plan = facade_plan(["research", "q", "--signals", '{"task_type": "ENGINEERING"}'])
        i = plan[0].index("--signals")
        assert json.loads(plan[0][i + 1])["task_type"] == "ENGINEERING"


class TestReviewAllRunsTheProductReview:
    def test_review_all_calls_run_nightly(self, tmp_path, monkeypatch, capsys):
        """`review all` — полный обзор продукта СЕЙЧАС: cli зовёт intelligence.run_nightly ВНИЗ."""
        (tmp_path / ".git").mkdir()
        calls = {}

        def _fake(root, *, since=None, deliver=True, date=None):
            calls["root"] = str(root)
            calls["deliver"] = deliver
            return {"brief": "БРИФ-ОБЗОРА-ПРОДУКТА", "receipt": None, "baseline": None}

        from ai_ops_kit.intelligence import nightly_review
        monkeypatch.setattr(nightly_review, "run_nightly", _fake)
        rc = main(["review", "all", str(tmp_path)])
        out = capsys.readouterr().out
        assert rc == 0
        assert calls.get("root") == str(tmp_path)
        assert calls.get("deliver") is False, "обзор по требованию не должен молча доставлять владельцу"
        assert "БРИФ-ОБЗОРА-ПРОДУКТА" in out

    def test_review_all_needs_a_repository(self, tmp_path, capsys):
        """Без git-репозитория обзор честно отказывает (строится по истории коммитов)."""
        rc = main(["review", "all", str(tmp_path)])
        err = capsys.readouterr().err
        assert rc == 1 and "не git-репозиторий" in err


class TestDescriptionsAreHonest:
    def test_review_names_security(self):
        """review отвечает «можно ли выпускать и почему, ВКЛЮЧАЯ безопасность» (отд. глагола нет)."""
        assert "безопас" in HUMAN_ACTIONS["review"]["label"].lower()

    def test_release_says_human_confirms_the_release(self):
        """release честно: кит готовит к выпуску, но merge/деплой подтверждает ЧЕЛОВЕК."""
        low = HUMAN_ACTIONS["release"]["label"].lower()
        assert "подтверждаешь ты" in low
        assert "не выпускает" in low or "не деплоит" in low

    def test_feedback_says_it_is_about_the_kit_not_the_product(self):
        """feedback — мета-канал о самом ките, а не про продукт владельца."""
        low = HUMAN_ACTIONS["feedback"]["label"].lower()
        assert "кит" in low and ("не про твой продукт" in low or "про сам кит" in low)

    def test_research_promises_evidence_and_decision_package(self):
        low = HUMAN_ACTIONS["research"]["label"].lower()
        assert "исследован" in low and "доказательств" in low and "решени" in low


class TestExistingIntentsStillWork:
    def test_non_facade_verb_is_not_intercepted(self):
        """Глагол вне фасада проходит обычным разбором (facade_plan его не трогает)."""
        assert facade_plan(["status", "."]) is None
        assert facade_plan(["governance"]) is None

    def test_next_and_plan_are_internal_not_in_the_showcase(self):
        """next/plan (и learn=readout) НЕ в человеческой витрине, но остаются рабочими интентами."""
        assert "next" not in HUMAN_ACTIONS and "plan" not in HUMAN_ACTIONS
        assert "learn" not in HUMAN_ACTIONS
        assert {"next", "plan", "readout"} <= set(INTENTS)
