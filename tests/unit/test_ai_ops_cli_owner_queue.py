"""Unit tests for tools/ai_ops_cli.py — владельческие read-only команды (explain + inbox).

Обе команды — owner-facing и только читают состояние: `explain` собирает карточку одной задачи
(#539), `inbox` — единую очередь «что ждёт моего решения» (#540). Они делят общий помощник
`_explain_run` (запуск main() из каталога репозитория) и один и тот же паттерн «битый реестр ->
не знаю, код 1», поэтому живут в одном файле. Машинерия превью/флагов — в `test_ai_ops_cli.py`,
main()/прямые действия — в `test_ai_ops_cli_main.py`. Разрез #819 (потолок анти-монолит-гейта).
"""
from __future__ import annotations

import os

import pytest
import yaml as _yaml

from ai_ops_kit.cli import ai_ops_cli
from ai_ops_kit.cli import ai_ops_cli_intents as _intents
from ai_ops_kit.cli import ai_ops_cli_report as _report
from ai_ops_kit.ui import presenter as _presenter


def _explain_run(argv, cwd):
    old = os.getcwd()
    try:
        os.chdir(cwd)
        return ai_ops_cli.main(argv)
    finally:
        os.chdir(old)


# ── #539: ai-ops explain — владельческая карточка «что с моей задачей прямо сейчас» ──────────────
# Проверяем ТРИ обязательства команды: (1) карточка собирается из состояния; (2) для аудитории
# product внутренняя лексика/статусы скрыты, а блокер назван последствием, а не гейтом; (3) путь
# «активной работы нет» отвечает, а не падает и не молчит успехом.
def _focus_state(status="in_progress", conflicts=None, cost=None):
    return {"registry_ok": True, "active_count": 1,
            "focus": {"wid": "w-1", "task": "добавить экспорт в CSV",
                      "workflow": "ENGINEERING", "status": status,
                      "branch": "ai-ops/w-1", "human_approval": status == "needs_human_decision"},
            "conflicts": conflicts or [],
            "cost": cost or {"measured": True, "cost_usd": 0.42, "cost_complete": True,
                             "calls": 3, "tokens": 1000},
            "gates": 5, "living_status": {"managed": True, "fresh_today": True}}


@pytest.mark.unit
class TestExplainIntent:
    """`ai-ops explain` — карточка задачи для владельца."""

    def test_explain_is_registered_and_direct(self):
        """Интент объявлен, исполняется (не превью), и его обработчик достижим."""
        assert "explain" in ai_ops_cli.INTENTS
        assert "explain" in ai_ops_cli.DIRECT_INTENTS
        assert "explain" in ai_ops_cli._INTENT_HANDLERS

    def test_card_assembles_from_focus_state(self):
        """Карточка собирает задачу, стадию, стоимость и следующий шаг из снимка состояния."""
        msg = _intents._explain_message(_focus_state())
        out = _presenter.render(msg, audience="product")
        assert "добавить экспорт в CSV" in out         # какая задача
        assert "в работе" in out                       # стадия
        assert "$0.42" in out                          # оценка стоимости
        assert "Дальше:" in out                        # следующий шаг

    def test_cost_unmeasured_is_honest_not_zero(self):
        """Неизмеренная стоимость называется прямо, а не показывается нулём."""
        out = _presenter.render(
            _intents._explain_message(_focus_state(cost={"measured": False})),
            audience="product")
        assert "не измерена" in out
        assert "$0.00" not in out
        # грамматика читаема (не «работа модель ещё не тратила»): фраза про обращения к модели
        assert "обращений к модели по этой задаче ещё не было" in out

    def test_blocker_is_a_consequence_not_a_gate_id(self):
        """Блокер назван последствием простыми словами — без имени гейта/трейсбека."""
        msg = _intents._explain_message(_focus_state(status="blocked"))
        out = _presenter.render(msg, audience="product")
        assert "Что мешает" in out
        assert "не проверено" in out or "не готова" in out
        assert msg["status"] == "blocked"
        low = out.lower()
        assert "gate" not in low and "code_review" not in low and "traceback" not in low

    def test_needs_human_decision_asks_for_decision(self):
        """Работа, ждущая человека, просит решение (статус needs_input, не blocked)."""
        msg = _intents._explain_message(_focus_state(status="needs_human_decision"))
        assert msg["status"] == "needs_input"
        out = _presenter.render(msg, audience="product")
        assert "реш" in out.lower()                     # «жду твоего решения» / «подтверди»

    def test_scope_conflict_becomes_a_blocker(self):
        """Пересечение области записи — тоже причина остановиться, названная последствием."""
        line = _intents._explain_blocker("in_progress", False, ["ai-ops/other"])
        assert line is not None
        assert "перепишут одно место" in line
        assert "ai-ops/other" in line

    def test_product_audience_suppresses_jargon(self):
        """Для product внутренний статус/workflow скрыты; на technical — доступны."""
        msg = _intents._explain_message(_focus_state())
        prod = _presenter.render(msg, audience="product")
        tech = _presenter.render(msg, audience="technical")
        assert "in_progress" not in prod and "ENGINEERING" not in prod
        assert "in_progress" in tech                    # тот же факт доступен технической аудитории

    def test_no_active_work_is_graceful(self, tmp_path, capsys):
        """Чистый репозиторий без идущих работ отвечает карточкой, а не падает и не молчит успехом."""
        rc = _explain_run(["explain", str(tmp_path)], tmp_path)
        out = capsys.readouterr().out
        assert rc == 0
        assert "ничего не идёт" in out.lower()
        assert "дальше" in out.lower()

    def test_corrupt_registry_says_it_does_not_know(self, tmp_path):
        """Битый реестр идущих работ -> «не знаю, что идёт» и код 1, а не ложное «ничего»."""
        awp = tmp_path / ".ai" / "runtime" / "active-work.yaml"
        awp.parent.mkdir(parents=True)
        awp.write_text("kind: active-work\nactive: [ this: is: broken\n", encoding="utf-8")
        rc = _explain_run(["explain", str(tmp_path)], tmp_path)
        assert rc == 1

    # ── #566: явный статус «технически done, продуктово нет» в explain ─────────────────────────────
    def test_failed_outcome_with_green_delivery_shows_technically_done_not_product(self):
        """Итог failed + доставка подтверждена -> карточка explain говорит различитель явно."""
        state = _focus_state(status="done")
        state["product_outcome"] = {
            "product_status": {"status": "delivered_not_met",
                               "label": "технически done, продуктово нет",
                               "technically_done_not_product": True,
                               "delivery_verified": True, "outcome_verdict": "failed"},
            "outcome_verdict": "failed", "reason": "activation 42%→41%", "flip_ready": True}
        msg = _intents._explain_message(state)
        assert msg["status"] == "degraded"
        out = _presenter.render(msg, audience="product")
        assert "Технически done, продуктово нет" in out
        assert "правильное" in out.lower()

    def test_unmeasured_outcome_leaves_the_card_unchanged(self):
        """Итог ещё не измерен (unknown) -> карточку НЕ трогаем: unknown ≠ провал."""
        state = _focus_state()
        state["product_outcome"] = {
            "product_status": {"technically_done_not_product": False, "label": "итог не измерен"},
            "outcome_verdict": "unknown", "reason": None, "flip_ready": False}
        msg = _intents._explain_message(state)
        assert msg["status"] == "ok"
        assert "Технически done" not in _presenter.render(msg, audience="product")

    def test_explain_discovers_outcome_docs_and_flips_verdict(self, tmp_path):
        """explain находит OutcomeContract(+Readout) в дочке и считает вердикт по РЕАЛЬНОМУ замеру."""
        import yaml
        contract = {"schema_version": 1, "kind": "OutcomeContract", "decision": "рост активации",
                    "evaluation_period": "30 дней",
                    "primary_metric": {"name": "activation_rate", "source": "posthog"},
                    "baseline": {"value": 42, "measured_at": "2026-08-01", "source": "posthog"},
                    "target": {"value": 45, "by": "2026-10-01"},
                    "guardrails": [{"name": "error_rate", "must_not_exceed": 2}],
                    "events": ["task.completed"],
                    "decision_rules": {"continue": "взяли", "change": "ниже", "stop": "просели"}}
        readout = {"schema_version": 1, "kind": "OutcomeReadout",
                   "contract": "outcome-contract.yaml", "target_met": "no",
                   "hypothesis": "refuted",
                   "measured": {"metric": "activation_rate", "value": 41,
                                "measured_at": "2026-09-16"},
                   "guardrails_observed": [], "unexpected_effects": [],
                   "next_decision": "менять подход", "back_to_discovery": "—"}
        (tmp_path / "outcome-contract.yaml").write_text(
            yaml.safe_dump(contract, allow_unicode=True), encoding="utf-8")
        (tmp_path / "outcome-readout.yaml").write_text(
            yaml.safe_dump(readout, allow_unicode=True), encoding="utf-8")
        po = _intents._explain_outcome(tmp_path)
        assert po is not None
        assert po["outcome_verdict"] == "failed"     # флип unknown→failed по реальному замеру
        assert po["flip_ready"] is True


# ── #540: ai-ops inbox — единая владельческая очередь «что ждёт моего решения» ────────────────────
# Проверяем ЧЕТЫРЕ обязательства: (1) очередь агрегирует из источников (решения с карточкой
# что/варианты/рекомендация, остановки, подтверждения, обзор, предупреждения о выпуске); (2) пустая
# очередь честна — «ничего не ждёт», а не выдуманный список; (3) для аудитории product скрыты
# идентификаторы работ/решений (жаргон), а на technical — доступны; (4) битый реестр -> «не знаю,
# что ждёт» и код 1, а не ложное «ничего».
def _make_queue(decisions=None, blocked=None, reviews=None, insight=None, warnings=None,
                registry_ok=True):
    d = decisions or []
    b = blocked or []
    r = reviews or []
    w = warnings or []
    total = len(d) + len(b) + len(r) + (1 if insight else 0) + len(w)
    return {"registry_ok": registry_ok, "total": total, "decisions": d, "blocked": b,
            "reviews": r, "insight": insight, "warnings": w}


@pytest.mark.unit
class TestInboxIntent:
    """`ai-ops inbox` — очередь всего, что ждёт решения владельца."""

    def test_inbox_is_registered_and_direct(self):
        """Интент объявлен, исполняется (не превью), и его обработчик достижим."""
        assert "inbox" in ai_ops_cli.INTENTS
        assert "inbox" in ai_ops_cli.DIRECT_INTENTS
        assert "inbox" in ai_ops_cli._INTENT_HANDLERS

    def test_reads_only_pending_decisions_with_card(self, tmp_path):
        """Источник решений: берутся только pending, с полями что/варианты/рекомендация."""
        ddir = tmp_path / ".ai" / "project" / "decisions"
        ddir.mkdir(parents=True)
        (ddir / "2026-09-06-d1.yaml").write_text(_yaml.safe_dump(
            {"id": "d1", "status": "pending", "proposal": "поднять таймаут доставки",
             "options": ["30s", "60s"], "recommendation": "60s"}, allow_unicode=True),
            encoding="utf-8")
        (ddir / "2026-09-05-d0.yaml").write_text(_yaml.safe_dump(
            {"id": "d0", "status": "approved", "proposal": "уже решено"}, allow_unicode=True),
            encoding="utf-8")
        got = _intents._inbox_decisions(tmp_path)
        assert [x["id"] for x in got] == ["d1"]                 # approved не попал
        assert got[0]["options"] == ["30s", "60s"]
        assert got[0]["recommendation"] == "60s"

    def test_decisions_dir_is_not_created_on_read(self, tmp_path):
        """Чтение решений НЕ создаёт каталог: inbox только читает (в отличие от list_decisions)."""
        assert _intents._inbox_decisions(tmp_path) == []
        assert not (tmp_path / ".ai" / "project" / "decisions").exists()

    def test_render_aggregates_all_buckets(self):
        """Очередь показывает решения (карточкой), остановки, подтверждения, обзор и предупреждения."""
        q = _make_queue(
            decisions=[{"id": "d1", "what": "поднять таймаут", "options": ["30s", "60s"],
                        "recommendation": "60s"}],
            blocked=[{"wid": "w-1", "task": "экспорт в CSV", "why": "проверка не пройдена"}],
            reviews=[{"wid": "w-2", "task": "смена схемы", "why": "жду подтверждения"}],
            insight={"what": "ночной обзор изменений", "path": "x"},
            warnings=[{"what": "здоровье продукта красное — выпускать рискованно", "why": "тесты"}])
        out = _intents._inbox_render(q, "product")
        assert "поднять таймаут" in out                         # решение
        assert "варианты:" in out and "60s" in out              # карточка: варианты+рекомендация
        assert "рекомендую" in out
        assert "экспорт в CSV" in out                           # остановленная работа
        assert "смена схемы" in out                             # ждёт подтверждения
        assert "ночной обзор" in out                            # свежий обзор
        assert "выпускать рискованно" in out                    # предупреждение о выпуске

    def test_empty_queue_is_honest(self):
        """Пустая очередь говорит «ничего не ждёт», а не показывает выдуманный список."""
        out = _intents._inbox_render(_make_queue(), "product")
        assert "Ничего не ждёт твоего решения." in out

    def test_empty_on_clean_repo_returns_zero(self, tmp_path, capsys):
        """Чистый репозиторий: команда отвечает пустой очередью и кодом 0, а не падает."""
        rc = _explain_run(["inbox", str(tmp_path)], tmp_path)
        out = capsys.readouterr().out
        assert rc == 0
        assert "ничего не ждёт" in out.lower()

    def test_product_audience_suppresses_ids(self):
        """Для product идентификаторы работ/решений скрыты; на technical — доступны."""
        q = _make_queue(blocked=[{"wid": "w-42", "task": "экспорт в CSV",
                                   "why": "проверка не пройдена"}])
        prod = _intents._inbox_render(q, "product")
        tech = _intents._inbox_render(q, "technical")
        assert "w-42" not in prod                               # идентификатор скрыт от владельца
        assert "экспорт в CSV" in prod                          # но сама задача названа
        assert "w-42" in tech                                   # тот же факт доступен технической

    def test_status_reflects_queue(self):
        """Статус контракта: решения -> нужно решение; только остановки -> заблокировано; пусто -> ок."""
        assert _intents._inbox_status(_make_queue(
            decisions=[{"id": "d", "what": "x", "options": [], "recommendation": ""}])) == "needs_input"
        assert _intents._inbox_status(_make_queue(
            blocked=[{"wid": "w", "task": "t", "why": "y"}])) == "blocked"
        assert _intents._inbox_status(_make_queue()) == "ok"
        assert _intents._inbox_status(_make_queue(registry_ok=False)) == "degraded"

    def test_release_warning_from_red_health(self, tmp_path, monkeypatch):
        """Предупреждение о выпуске выводится из красного здоровья продукта (read-only источник)."""
        monkeypatch.setattr(_report, "_product_health_report",
                            lambda root: {"band": "red", "reasons": ["CI красный"]})
        warns = _intents._inbox_release_warnings(tmp_path)
        assert len(warns) == 1
        assert "рискованно" in warns[0]["what"]
        # Зелёное/нет данных -> предупреждения нет (не выдумываем).
        monkeypatch.setattr(_report, "_product_health_report", lambda root: {"band": "green"})
        assert _intents._inbox_release_warnings(tmp_path) == []
        monkeypatch.setattr(_report, "_product_health_report", lambda root: None)
        assert _intents._inbox_release_warnings(tmp_path) == []

    def test_corrupt_registry_says_it_does_not_know(self, tmp_path):
        """Битый реестр идущих работ -> «не знаю, что ждёт» и код 1, а не ложное «ничего»."""
        awp = tmp_path / ".ai" / "runtime" / "active-work.yaml"
        awp.parent.mkdir(parents=True)
        awp.write_text("kind: active-work\nactive: [ this: is: broken\n", encoding="utf-8")
        q = _intents._inbox_collect(tmp_path)
        assert q["registry_ok"] is False
        out = _intents._inbox_render(q, "product")
        assert "Не знаю, что ждёт" in out
        rc = _explain_run(["inbox", str(tmp_path)], tmp_path)
        assert rc == 1
