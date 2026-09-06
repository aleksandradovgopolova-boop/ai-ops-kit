"""Пост-релизная петля ПРОВЕДЕНА В КОНТУР одним вызовом: PRR -> verify -> outcome -> verdict (#545).

ПОВОД (outcome-loop, «built ≠ wired»). Звенья пост-релизной петли уже построены, но стояли рядом и
никто не соединял их в один путь: `verify_analytics_runtime` звался только из `__main__`/тестов,
валидатор PRR — как отдельный процесс, `project_outcome`/`trace_feature_rationale` — нигде вне
своего модуля. `post_release_loop.run_post_release` — ТОНКАЯ проводка: композиция существующих
функций в один результат с одним вердиктом. Здесь доказывается, что проводка реально проходит путь
и что её ЧЕСТНЫЙ ДЕФОЛТ соблюдён.

ЧТО ПРОВЕРЯЕТСЯ (и почему именно это):
  1. единый путь проходит PRR -> verify -> verdict на примере examples/readout-demo/PRR-001.yaml;
  2. без выгрузки аналитики verdict честно unknown/watch, а НЕ «healthy» (инвариант unavailable≠0);
  3. три доказательства гейта без producer'а помечены not_measured и это ВИДНО в выводе (1 из 4);
  4. никакой goal.outcome не флипается — проводка возвращает вердикт, но плана не трогает.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT))

from ai_ops_kit.cli import post_release_loop as prl  # noqa: E402
from ai_ops_kit.ui import presenter  # noqa: E402

EXAMPLE_PRR = PKG_ROOT / "examples" / "readout-demo" / "PRR-001.yaml"

# Каталог событий: два события kind=analytics ОБЯЗАНЫ доезжать.
CATALOG = """schema_version: 1
kind: event-catalog
events:
  - {name: task.completed, kind: analytics}
  - {name: object.version_created, kind: analytics}
"""

# Валидный OutcomeContract (форма — по validate_product_objects._check_contract).
CONTRACT = {
    "schema_version": 1, "kind": "OutcomeContract", "decision": "ускорить онбординг",
    "evaluation_period": "30 дней",
    "primary_metric": {"name": "activation_rate", "source": "posthog"},
    "baseline": {"value": 20, "measured_at": "2026-09-01", "source": "posthog"},
    "target": {"value": 35, "by": "2026-10-01"},
    "guardrails": [{"name": "error_rate", "must_not_exceed": 2}],
    "events": ["task.completed"],
    "decision_rules": {"continue": "target достигнут", "change": "ниже baseline",
                       "stop": "guardrail пробит"},
}


def _child(tmp_path, *, catalog=None, seen=None, plan_outcome=None):
    """Синтетическая дочка. catalog/seen — каталог событий и выгрузка поступления; plan_outcome —
    goal.outcome в planning/plan.yaml (для доказательства, что проводка его не флипает)."""
    root = tmp_path / "product"
    (root / "analytics").mkdir(parents=True)
    if catalog is not None:
        (root / "analytics" / "events.yaml").write_text(catalog, encoding="utf-8")
    if seen is not None:
        (root / "analytics" / "events-seen.json").write_text(
            json.dumps({"schema_version": 1, "kind": "EventArrivalEvidence",
                        "collected_at": "2026-09-07T03:00:00Z", "window": "24h",
                        "source": "posthog", "events": seen}), encoding="utf-8")
    if plan_outcome is not None:
        (root / "planning").mkdir(parents=True)
        (root / "planning" / "plan.yaml").write_text(
            "schema_version: 1\nkind: delivery-plan\ngoals:\n"
            f"  - {{id: g1, title: онбординг, outcome: {str(plan_outcome).lower()}}}\n",
            encoding="utf-8")
    return root


# ── (1) единый путь: PRR -> verify -> verdict на примере PRR-001 ───────────────────────────────────
def test_single_call_runs_prr_verify_verdict_on_example(tmp_path):
    """Один вызов проходит все звенья на реальном примере PRR-001 (downstream not_run -> watch)."""
    root = _child(tmp_path)          # аналитики нет — как на PRR-001
    res = prl.run_post_release(str(EXAMPLE_PRR), root)

    # звено (a): PRR найден и провалидирован
    assert res["prr"]["found"] is True
    assert res["prr"]["id"] == "PRR-001"
    assert res["prr"]["valid"] is True and res["prr"]["errors"] == []
    # звено (b): verify_analytics_runtime отработал и дал машинный разбор гейта
    assert res["analytics_runtime"]["gate"] == "analytics_runtime_verification"
    assert res["analytics_runtime"]["status"] in ("fail", "warn", "pass")
    # звено (e): один сведённый вердикт + readout_decision присутствуют
    assert "verdict" in res and "readout_decision" in res
    # PRR-001 объявляет decision=watch -> проводка его сохраняет (PRR валиден)
    assert res["readout_decision"] == "watch"


# ── (2) без выгрузки аналитики — honest unknown/watch, НЕ healthy ──────────────────────────────────
def test_no_analytics_dump_is_unknown_not_healthy(tmp_path):
    """Нет выгрузки поступления -> events unknown, verdict unknown, решение watch. Никогда healthy."""
    root = _child(tmp_path, catalog=CATALOG, seen=None)   # каталог есть, выгрузки НЕТ
    res = prl.run_post_release(str(EXAMPLE_PRR), root)

    assert res["analytics_runtime"]["events_verified_live"] == "unknown"
    assert res["verdict"] == "unknown"
    assert res["readout_decision"] == "watch"
    # СЛОВА «healthy»/«verified» в вердикте не появляется ни при каких данных этой петли
    assert res["verdict"] not in ("healthy", "healthy_continue", "verified")
    assert res["readout_decision"] != "healthy_continue"


def test_message_says_cannot_recommend_release_by_consequence(tmp_path):
    """Продукту объясняем ПОСЛЕДСТВИЕМ: «выпуск рекомендовать не могу», без gate/PRR-жаргона наружу."""
    root = _child(tmp_path, catalog=CATALOG, seen=None)
    res = prl.run_post_release(str(EXAMPLE_PRR), root)
    text = presenter.render(presenter.from_post_release_loop(res), audience="product")
    assert "рекомендовать" in text.lower()
    # product-аудитория не видит внутренних имён в основном тексте (они — в технических деталях)
    head = text.split("Технические детали")[0]
    assert "events_verified_live" not in head
    assert "analytics_runtime_verification" not in head


# ── (3) три доказательства без producer'а -> not_measured, видно в выводе (1 из 4) ─────────────────
def test_three_evidences_without_producer_are_not_measured(tmp_path):
    """Гейт требует 4 доказательства, producer есть у одного; остальные 3 -> not_measured, и это видно."""
    root = _child(tmp_path, catalog=CATALOG, seen={"task.completed": 5,
                                                   "object.version_created": 2})
    res = prl.run_post_release(str(EXAMPLE_PRR), root)
    a = res["analytics_runtime"]

    assert a["evidence_with_producer"] == 1
    assert a["evidence_required"] == 4
    breakdown = a["evidence_breakdown"]
    # единственное с producer'ом — events_verified_live (тут verified: выгрузка есть и всё доехало)
    assert breakdown["events_verified_live"] == "verified"
    # три без producer'а — честно not_measured (источников им НЕ выдумываем)
    for name in ("no_pii_in_events", "cohort_identification_works", "dashboard_receives_data"):
        assert breakdown[name] == "not_measured"
    # «1 из 4» ВИДНО в человекочитаемом выводе и в заметках
    assert any("1" in n and "4" in n for n in res["notes"])
    assert "not_measured" in prl.render(res)


def test_events_arrive_but_verdict_is_only_partially_verified(tmp_path):
    """Даже когда события доезжают, вердикт лишь partially_verified — гейт закрыт 1 из 4, не «verified»."""
    root = _child(tmp_path, catalog=CATALOG, seen={"task.completed": 9,
                                                   "object.version_created": 3})
    res = prl.run_post_release(str(EXAMPLE_PRR), root)
    assert res["analytics_runtime"]["events_verified_live"] == "verified"
    assert res["verdict"] == "partially_verified"
    assert res["verdict"] != "verified"


def test_declared_event_missing_from_dump_is_a_negative_signal(tmp_path):
    """Объявленное событие не встретилось в выгрузке -> events not_verified -> attention/investigate."""
    root = _child(tmp_path, catalog=CATALOG, seen={"task.completed": 4})  # второе НЕ доехало
    res = prl.run_post_release(str(EXAMPLE_PRR), root)
    assert res["analytics_runtime"]["events_verified_live"] == "not_verified"
    assert res["verdict"] == "attention"
    # PRR-001 валиден и объявляет watch -> его решение уважается; сигнал негативности — в verdict


# ── (4) никакой goal.outcome НЕ флипается ─────────────────────────────────────────────────────────
def test_run_does_not_flip_any_goal_outcome(tmp_path):
    """Проводка возвращает вердикт, но goal.outcome в plan.yaml не трогает; outcome_flip_ready=False."""
    root = _child(tmp_path, catalog=CATALOG, seen={"task.completed": 5,
                                                   "object.version_created": 2},
                  plan_outcome=False)
    plan = root / "planning" / "plan.yaml"
    before = plan.read_text(encoding="utf-8")
    res = prl.run_post_release(str(EXAMPLE_PRR), root)
    after = plan.read_text(encoding="utf-8")

    assert before == after, "run_post_release не должен писать в plan.yaml"
    assert "outcome: false" in after           # исход остался НЕ достигнутым
    assert res["outcome_flip_ready"] is False   # флип ждёт реального выпуска (TODO #545)


# ── outcome-звено (опциональное): проекция + трассировка при наличии контракта ─────────────────────
def test_outcome_projection_without_readout_is_pending(tmp_path):
    """Дан OutcomeContract без Readout -> исход спроецирован, verdict честно pending (не «met»)."""
    root = _child(tmp_path, catalog=CATALOG, seen=None)
    res = prl.run_post_release(str(EXAMPLE_PRR), root, contract=CONTRACT, feature="csv-export")
    assert res["outcome"] is not None
    assert res["outcome"]["projected"] is True
    assert res["outcome"]["verdict"] == "pending"
    # трассировка «зачем функция» вернулась и честно называет пробелы (нет полного графа goal->feature)
    assert res["outcome"]["trace"] is not None
    assert isinstance(res["outcome"]["gaps"], list)


def test_no_contract_means_outcome_absent(tmp_path):
    """Без контракта outcome-звено просто не участвует (None), а не выдумывает исход."""
    root = _child(tmp_path, catalog=CATALOG, seen=None)
    res = prl.run_post_release(str(EXAMPLE_PRR), root)
    assert res["outcome"] is None


# ── PRR не найден — законный unknown, а не провал ─────────────────────────────────────────────────
def test_missing_prr_is_unknown_not_error(tmp_path):
    """Нет PRR-файла -> found False, вердикт unknown, honest note; это состояние, не ошибка."""
    root = _child(tmp_path, catalog=CATALOG, seen=None)
    res = prl.run_post_release(None, root)   # искать в дочке — не найдёт
    assert res["prr"]["found"] is False
    assert res["verdict"] == "unknown"
    assert any("PRR" in n for n in res["notes"])
