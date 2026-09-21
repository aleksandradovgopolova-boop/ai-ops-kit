"""T3 — недобравшие фичи поднимаются в `next` как ПРОДУКТОВОЕ РЕШЕНИЕ (outcome → decision candidates).

Доказывает пять свойств на ФИКСТУРАХ (чистые, без живого репозитория):
  1. РЕАЛЬНЫЙ `failed`-исход (промах цели по числам) → кандидат-РЕШЕНИЕ, чей `rationale` несёт
     «потому что <сдвиг метрики против цели>» — обоснование из снятого замера, не из головы;
  2. `met` + цель взята + гипотеза подтверждена → кандидата НЕТ (решать нечего);
  3. контракт есть, а отчёта НЕТ → кандидата нет И это честно помечено `not_measured` («ещё не
     измерено», а не «всё хорошо»);
  4. неподтверждённая гипотеза (refuted) при формально взятой цели → кандидат ЕСТЬ;
  5. `gather_candidates` объединяет решения-кандидаты с находками дочек и направлениями роадмапа.

Проектор ЧИСТ: загрузку файлов и вердикт (`evaluate_outcome`) делает слой CLI, поэтому здесь входы
собираются ровно так же — через `validate_product_objects.evaluate_outcome`, как это делает
`candidates_cli._collect_outcome_items`.
"""
from __future__ import annotations

import yaml
import pytest

from ai_ops_kit.intelligence import decision_candidates as dc
from ai_ops_kit.validation import validate_product_objects as vpo
from ai_ops_kit.engops import kit_feedback
from ai_ops_kit.cli.candidates_cli import gather_candidates

pytestmark = pytest.mark.unit

_METRIC = "конверсия оформления"


def _contract(baseline, target, *, goal=None):
    c = {
        "schema_version": 1, "kind": "OutcomeContract",
        "decision": "ускорить оформление заказа",
        "evaluation_period": "4 недели",
        "primary_metric": {"name": _METRIC, "source": "product-analytics"},
        "baseline": {"value": baseline, "measured_at": "2026-09-01", "source": "product-analytics"},
        "target": {"value": target, "by": "2026-10-01"},
        "guardrails": [{"name": "отказы оплаты", "must_not_exceed": 5}],
        "events": [{"name": "checkout_started"}],
        "decision_rules": {"continue": "держим", "change": "меняем", "stop": "стоп"},
    }
    if goal:
        c["goal"] = goal
    return c


def _readout(measured, *, hypothesis="confirmed", guardrail_within=True):
    return {
        "schema_version": 1, "kind": "OutcomeReadout",
        "contract": "outcome-contract.yaml",
        "measured": {"value": measured, "metric": _METRIC, "measured_at": "2026-10-01"},
        "hypothesis": hypothesis,
        "guardrails_observed": [{"name": "отказы оплаты", "within": guardrail_within}],
        "unexpected_effects": [],
        "next_decision": "решить, продолжать ли ускорение оформления",
        "back_to_discovery": "проверить, где теряются пользователи",
    }


def _item(feature, contract, readout):
    """(feature, contract, readout, evaluation) — как их собирает слой CLI перед проектором."""
    return (feature, contract, readout, vpo.evaluate_outcome(contract, readout))


# ── 1: реальный failed → кандидат-решение с «потому что …» ───────────────────────────────────────

def test_real_failed_outcome_yields_decision_candidate_with_because():
    contract, readout = _contract(42, 50), _readout(41)          # сдвинулась 42→41, цель 50 не взята
    ev = vpo.evaluate_outcome(contract, readout)
    assert ev["verdict"] == "failed" and ev["is_real_measurement"] is True   # предусловие

    proj = dc.project_decision_candidates([_item("express-checkout", contract, readout)])
    cands = proj["candidates"]
    assert len(cands) == 1
    c = cands[0]
    assert c["id"] == "cand-decision-express-checkout"
    assert c["source"] == "outcome-decision"
    assert c["source_feature"] == "express-checkout"
    assert c["decision_reason"] == "underperformed"
    assert c["status"] == "draft" and c["active"] is False
    assert c["requires_human_decision"] is True
    # Заголовок оформлен как РЕШЕНИЕ, а не техзадача.
    assert c["title"].startswith("Решить следующий шаг по фиче «express-checkout»")
    # rationale несёт «потому что <что произошло с продуктом>» — из снятого замера, не из головы.
    assert "потому что" in c["rationale"]
    assert "50" in c["rationale"] and "42" in c["rationale"]     # цель и старт — реальные числа


# ── 2: met + цель взята + гипотеза подтверждена → кандидата нет ──────────────────────────────────

def test_met_and_target_reached_yields_no_candidate():
    contract, readout = _contract(42, 50), _readout(55, hypothesis="confirmed")
    ev = vpo.evaluate_outcome(contract, readout)
    assert ev["verdict"] == "met"                                # предусловие
    proj = dc.project_decision_candidates([_item("express-checkout", contract, readout)])
    assert proj["candidates"] == []
    assert proj["not_measured"] == []                            # измерено — не пункт «ещё не измерено»
    assert proj["considered"] == 1


# ── 3: контракт есть, отчёта НЕТ → кандидата нет, честно not_measured ────────────────────────────

def test_contract_without_readout_is_honest_not_measured_not_a_decision():
    contract = _contract(42, 50)
    proj = dc.project_decision_candidates([_item("express-checkout", contract, None)])
    assert proj["candidates"] == []                              # решать пока не по чему
    assert len(proj["not_measured"]) == 1
    nm = proj["not_measured"][0]
    assert nm["feature"] == "express-checkout"
    assert "ещё не измерено" in nm["reason"]                     # НЕ «всё хорошо», НЕ «решать нечего»


# ── 4: неподтверждённая гипотеза (refuted) при взятой цели → кандидат есть ───────────────────────

def test_unconfirmed_hypothesis_yields_decision_candidate():
    # Цель формально взята (met), НО гипотеза опровергнута — решение всё равно назрело.
    contract, readout = _contract(42, 50), _readout(55, hypothesis="refuted")
    ev = vpo.evaluate_outcome(contract, readout)
    assert ev["verdict"] == "met"                                # цель по числам взята
    proj = dc.project_decision_candidates([_item("express-checkout", contract, readout)])
    cands = proj["candidates"]
    assert len(cands) == 1
    c = cands[0]
    assert c["decision_reason"] == "hypothesis_unconfirmed"
    # Заголовок — РЕШЕНИЕ про гипотезу, а НЕ поздравление успешной ветки insight («Закрепить результат…»).
    assert c["title"].startswith("Решить следующий шаг по фиче «express-checkout»")
    assert "Закрепить результат" not in c["title"]
    # rationale говорит ПРО ГИПОТЕЗУ (опровергнута), а не «метрика дошла до цели».
    assert "потому что" in c["rationale"]
    assert "опровергнута" in c["rationale"]
    assert "формально взята" in c["rationale"]                   # цель взята — но это не повод молчать
    assert "дошла до" not in c["rationale"] and "достигла цели" not in c["rationale"]


def test_inconclusive_hypothesis_also_counts_as_unconfirmed():
    contract, readout = _contract(42, 50), _readout(55, hypothesis="inconclusive")
    proj = dc.project_decision_candidates([_item("express-checkout", contract, readout)])
    assert len(proj["candidates"]) == 1
    c = proj["candidates"][0]
    assert c["decision_reason"] == "hypothesis_unconfirmed"
    # Тоже РЕШЕНИЕ про гипотезу, а не поздравление.
    assert c["title"].startswith("Решить следующий шаг по фиче «express-checkout»")
    assert "Закрепить результат" not in c["title"]
    assert "потому что" in c["rationale"]
    assert "не разрешилась" in c["rationale"]
    assert "дошла до" not in c["rationale"] and "достигла цели" not in c["rationale"]


def test_readout_present_but_not_comparable_is_not_measured_not_silent():
    """Замер СНЯТ, но не сравним с целью (нет measured_at) → verdict unknown. Это «ещё не измерено»,
    а НЕ «ок»: кандидата нет, но фича обязана попасть в not_measured, а не молча пропасть (баг 1)."""
    contract = _contract(42, 50)
    readout = {
        "schema_version": 1, "kind": "OutcomeReadout", "contract": "outcome-contract.yaml",
        "measured": {"value": 55, "metric": _METRIC, "measured_at": ""},   # ЗАМЕР БЕЗ ДАТЫ
        "hypothesis": "confirmed",                                          # по гипотезе тоже не назрело
        "guardrails_observed": [{"name": "отказы оплаты", "within": True}],
        "unexpected_effects": [], "next_decision": "…", "back_to_discovery": "…",
    }
    ev = vpo.evaluate_outcome(contract, readout)
    assert ev["verdict"] == "unknown" and ev["is_real_measurement"] is False   # предусловие
    proj = dc.project_decision_candidates([_item("express-checkout", contract, readout)])
    assert proj["candidates"] == []                              # решать нечем — кандидата нет
    assert len(proj["not_measured"]) == 1                        # НО фича не пропала молча
    assert proj["not_measured"][0]["feature"] == "express-checkout"
    assert "не сравним с целью" in proj["not_measured"][0]["reason"]


def test_non_numeric_contract_readout_is_not_measured_not_silent():
    """Нечисловой контракт (текстовые baseline/target) → сравнить нечем → unknown → not_measured,
    даже когда замер по форме заполнен и гипотеза подтверждена (баг 1, второй путь unknown)."""
    contract = _contract("много", "ещё больше")                 # нечисловые baseline/target
    readout = _readout(58, hypothesis="confirmed")              # замер по форме полон
    ev = vpo.evaluate_outcome(contract, readout)
    assert ev["verdict"] == "unknown" and ev["is_real_measurement"] is False
    proj = dc.project_decision_candidates([_item("express-checkout", contract, readout)])
    assert proj["candidates"] == []
    assert len(proj["not_measured"]) == 1
    assert "не сравним с целью" in proj["not_measured"][0]["reason"]


def test_projector_never_raises_on_garbage_input():
    """Кривые входы не роняют проекцию (обратный канал обогащает очередь, не является предусловием)."""
    proj = dc.project_decision_candidates([None, ("only-two", {}), (1, 2, 3, 4), "не кортеж"])
    assert proj["kind"] == "OutcomeDecisionCandidates"
    assert proj["candidates"] == []


# ── 5: union трёх источников (решения + находки + направления роадмапа) ──────────────────────────

_CANARY = "# CANARY-KEEP-ME: комментарий обязан пережить сбор кандидатов"

_PLAN_TEXT = f"""schema_version: 1
kind: delivery-plan
goals:
  - id: covered-direction
    title: Покрытое направление
    outcome:
      shipped_thing: false
  - id: uncovered-direction
    title: Непокрытое направление
    outcome:
      new_thing: false
work:
  {_CANARY}
  - id: existing-work
    title: Существующая работа под покрытым направлением
    type: engineering
    goal: covered-direction
    status: todo
    owner_role: engineer
    write_scope: [src/]
"""


def _fixture_repo(tmp_path):
    (tmp_path / "planning").mkdir(parents=True, exist_ok=True)
    (tmp_path / "planning" / "plan.yaml").write_text(_PLAN_TEXT, encoding="utf-8")
    return tmp_path


def _write_outcome(repo, feature, contract, readout):
    d = repo / "features" / feature
    d.mkdir(parents=True, exist_ok=True)
    (d / "outcome-contract.yaml").write_text(
        yaml.safe_dump(contract, allow_unicode=True), encoding="utf-8")
    if readout is not None:
        (d / "outcome-readout.yaml").write_text(
            yaml.safe_dump(readout, allow_unicode=True), encoding="utf-8")


def _write_obs(repo, oid, *, state="delivered"):
    d = repo / kit_feedback.KIT_DIR
    d.mkdir(parents=True, exist_ok=True)
    doc = {"schema_version": 1, "kind": "KitObservation", "id": oid,
           "at": "2026-09-21T00:00:00+00:00", "statement": f"наблюдение {oid} из прогона",
           "observation_class": "defect", "severity": "p1", "state": state,
           "child": {"name": "bnbm", "path": "/tmp/bnbm"},
           "evidence": [{"kind": "note", "text": "e"}]}
    (d / f"{oid}.yaml").write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")


def test_gather_candidates_union_includes_decision_finding_and_roadmap(tmp_path):
    repo = _fixture_repo(tmp_path)
    _write_outcome(repo, "express-checkout", _contract(42, 50), _readout(41))  # недобравший исход
    _write_obs(repo, "obs-open", state="delivered")                            # открытая находка

    cands = gather_candidates(repo)
    ids = [c.get("id") for c in cands]
    assert "cand-decision-express-checkout" in ids                 # источник исходов (T3)
    assert "cand-dir-uncovered-direction" in ids                   # источник роадмапа
    assert any(c.get("source_observation") == "obs-open" for c in cands)  # источник находок
    # источники честно помечены
    sources = {c.get("source") for c in cands}
    assert {"outcome-decision", "roadmap-direction", "child-finding"} <= sources
