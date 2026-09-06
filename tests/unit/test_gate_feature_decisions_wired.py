"""#541: гейт `feature_decision_quality` проведён в контур прогона, а не только построен.

Механизм `gate_feature_decisions` был написан и покрыт юнит-тестами (test_decision_feature_target.py),
но НЕ стоял ни в одном гейте — фича, объявленная целью без baseline/target/guardrails, молча
проходила прогон. Здесь проверяется, что теперь:

  1. reachable  — гейт есть в реестре, исполняется детерминированно (validator), и исполнитель
                  гейтов реально его запускает (deterministic_run возвращает вердикт, не None);
  2. reds       — на неполном feature-decision в каталоге решений гейт краснеет (status=fail) и
                  называет, чего не хватает; на полном / пустом каталоге — зелёный;
  3. selected   — трек FEATURE_DECISIONS добавляет гейт в план по сигналу feature_decision_declared,
                  а без сигнала — честный explainable skip (гейт не выбран, причина названа).
"""
from __future__ import annotations

import yaml
import pytest

from ai_ops_kit.gates import gate_executor as ge
from ai_ops_kit.engine.run_plan import build_plan, validate_tracks
from ai_ops_kit.intelligence.decision_loop import propose

pytestmark = pytest.mark.unit

GATE_ID = "feature_decision_quality"
SIGNAL = "feature_decision_declared"


def _full_target() -> dict:
    return {
        "baseline": {"metric": "p95_latency_ms", "value": 800},
        "target": {"value": 400, "direction": "decrease"},
        "guardrails": [{"metric": "error_rate", "bound": "<0.5%"}],
    }


# ─── 1. reachable from the executor ──────────────────────────────────────────────────────────────

def test_gate_is_registered_and_executed_deterministically():
    gates = ge.load_gates()
    assert GATE_ID in gates, "гейт не объявлен в quality/gates.yaml — трек не сможет на него сослаться"
    gate = gates[GATE_ID]
    # исполняется машиной, а не мнением: иначе «зелёное» этого гейта было бы суждением
    assert ge.classify(gate) == "deterministic"
    assert ge.closed_by(gate) == "validator"
    assert gate.get("validator") == "validate-feature-decisions"


def test_executor_actually_runs_the_validator_not_none():
    """Ключ проводки: исполнитель гейтов знает, как запустить этот валидатор офлайн.

    Символический валидатор вернул бы None (нужен внешний evidence) — и гейт молча ждал бы того,
    чего в контуре нет. Триплет (status, checks, provided) доказывает, что путь исполняем."""
    run = ge.deterministic_run("validate-feature-decisions")
    assert run is not None, "deterministic_run не знает валидатор — гейт не исполняется в контуре"
    status, checks, provided = run
    assert status in ("pass", "warn", "fail")


# ─── 2. reds on missing feature_target ───────────────────────────────────────────────────────────

def _write_decisions(root, decision: dict):
    ddir = root / ".ai" / "project" / "decisions"
    ddir.mkdir(parents=True, exist_ok=True)
    (ddir / "2026-09-06-x.yaml").write_text(
        yaml.dump(decision, allow_unicode=True), encoding="utf-8")


def test_gate_reds_on_incomplete_feature_decision(tmp_path, monkeypatch):
    _write_decisions(tmp_path, {
        "schema_version": 1, "kind": "feature-decision", "id": "x",
        "feature_target": {"baseline": {"metric": "m", "value": 1}},  # нет target/guardrails
    })
    monkeypatch.chdir(tmp_path)
    gate = ge.load_gates()[GATE_ID]
    res = ge.evaluate_gate(GATE_ID, gate, {})
    assert res["status"] == "fail", res
    joined = " ".join(c["id"] for c in res["checks"])
    assert "target" in joined and "guardrails" in joined, joined


def test_gate_greens_on_complete_feature_decision(tmp_path, monkeypatch):
    propose(tmp_path, "ok", "полная фича", feature_target=_full_target())
    monkeypatch.chdir(tmp_path)
    gate = ge.load_gates()[GATE_ID]
    res = ge.evaluate_gate(GATE_ID, gate, {})
    assert res["status"] == "pass", res
    # бездоказательного pass не бывает: required_evidence подтверждён через provided
    assert "feature_target_declared" not in " ".join(res["warnings"])


def test_gate_greens_when_no_decisions_authored(tmp_path, monkeypatch):
    """Каталога решений нет — фич-решений просто нет, это не дефект (pass, не тихий провал)."""
    monkeypatch.chdir(tmp_path)
    gate = ge.load_gates()[GATE_ID]
    res = ge.evaluate_gate(GATE_ID, gate, {})
    assert res["status"] == "pass", res


# ─── 3. selection through the track ──────────────────────────────────────────────────────────────

def test_track_selects_the_gate_on_signal():
    plan = build_plan({"task_type": "feature", SIGNAL: True, "task_text": "фича"})
    assert GATE_ID in plan["gates"], "гейт не попал в план фича-задачи — трек не выбирает его"
    assert any(t["track"] == "FEATURE_DECISIONS" for t in plan["required_tracks"])


def test_track_is_skipped_with_a_reason_without_signal():
    plan = build_plan({"task_type": "feature", "task_text": "фича"})
    assert GATE_ID not in plan["gates"], "гейт выбран без сигнала — не-фича-задача его не требует"
    skipped = {t["track"]: t["reason"] for t in plan["skipped_tracks"]}
    assert "FEATURE_DECISIONS" in skipped
    assert skipped["FEATURE_DECISIONS"], "explainable skip обязан назвать причину"


def test_track_registry_stays_consistent():
    """Гейт трека резолвится в реестре гейтов, поля трека на месте (страж целостности tracks.yaml)."""
    assert validate_tracks() == []
