"""Стоимость успешного ИСХОДА + estimate→actual→delta — #637.

Главный экономический KPI кита — не token cost, а стоимость доставленного исхода (AI-стоимость +
внимание человека), плюс пост-фактум «работа стоила $X вместо ожидаемых $Y». Экономика уже сильна
(бюджет привязан к единице работы, cost_per_successful_change с честным None); два пробела —
монетизация внимания человека и единое сведение оценки с фактом. Эти тесты держат оба + честность
usage_ledger (неизвестное = unavailable, никогда 0) и инвариант «провал = чистые потери».
"""
from __future__ import annotations

import pytest

from ai_ops_kit.providers import cost_account as ca


# ─── cost_per_successful_outcome: нагруженная стоимость ──────────────────────────────────────────

@pytest.mark.unit
def test_outcome_adds_human_attention_when_rate_and_count_known():
    r = ca.cost_per_successful_outcome(
        {"calls_cost": 2.0, "manual_interventions": 3, "delivered_verified": True},
        human_attention_cost_usd=0.5)
    assert r["ai_cost"] == 2.0
    assert r["human_attention_cost"] == 1.5           # 3 * 0.5
    assert r["loaded_cost"] == 3.5
    assert r["cost_per_outcome"] == 3.5
    assert r["complete"] is True and r["lower_bound"] is False


@pytest.mark.unit
def test_failed_outcome_is_pure_loss_even_with_human_cost():
    r = ca.cost_per_successful_outcome(
        {"calls_cost": 2.0, "manual_interventions": 3, "delivered_verified": False},
        human_attention_cost_usd=0.5)
    assert r["cost_per_outcome"] is None              # провал = чистые потери
    assert r["loaded_cost"] == 3.5                    # стоимость есть, исхода нет


@pytest.mark.unit
def test_missing_rate_makes_human_unavailable_never_zero():
    r = ca.cost_per_successful_outcome(
        {"calls_cost": 2.0, "manual_interventions": 4, "delivered_verified": True})
    assert r["human_attention_cost"] is None          # unavailable, НЕ 0
    assert r["complete"] is False and r["lower_bound"] is True
    assert r["loaded_cost"] == 2.0                    # нижняя граница = AI-часть
    assert "unavailable" in r["note"]


@pytest.mark.unit
def test_unknown_intervention_count_is_unavailable_never_zero():
    r = ca.cost_per_successful_outcome(
        {"calls_cost": 1.0, "delivered_verified": True}, human_attention_cost_usd=0.5)
    assert r["manual_interventions"] is None          # не задано -> неизвестно
    assert r["human_attention_cost"] is None and r["lower_bound"] is True


@pytest.mark.unit
def test_zero_interventions_with_a_rate_is_a_real_zero_not_unavailable():
    r = ca.cost_per_successful_outcome(
        {"calls_cost": 1.0, "manual_interventions": 0, "delivered_verified": True},
        human_attention_cost_usd=0.5)
    assert r["human_attention_cost"] == 0.0 and r["complete"] is True    # известный ноль != unavailable


@pytest.mark.unit
def test_human_attention_cost_read_from_child_config(tmp_path):
    (tmp_path / ".ai-ops.yaml").write_text(
        "engineering_operating_model:\n  economics:\n"
        "    human_attention_cost_per_intervention_usd: 1.25\n", encoding="utf-8")
    assert ca.human_attention_cost(tmp_path) == 1.25
    assert ca.human_attention_cost(tmp_path / "nope") is None    # нет файла -> None (не 0)


@pytest.mark.unit
def test_human_attention_cost_absent_key_is_none():
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / ".ai-ops.yaml").write_text("engineering_operating_model: {}\n", encoding="utf-8")
        assert ca.human_attention_cost(Path(d)) is None


# ─── estimate_vs_actual: пост-фактум дельта ──────────────────────────────────────────────────────

@pytest.mark.unit
def test_delta_is_actual_minus_estimate_with_human_line():
    r = ca.estimate_vs_actual(
        {"estimate_status": "measured_history", "cost_median": 2.0, "cost_max": 3.0},
        {"cost_usd_est": 2.5})
    assert r["estimate_usd"] == 2.0 and r["actual_usd"] == 2.5
    assert r["delta_usd"] == 0.5 and r["delta_pct"] == 25.0
    assert r["over_max"] is False and r["status"] == "measured"
    assert "вместо ожидаемых" in r["note"]


@pytest.mark.unit
def test_delta_flags_over_the_expected_max():
    r = ca.estimate_vs_actual(
        {"estimate_status": "measured_history", "cost_median": 2.0, "cost_max": 3.0},
        {"cost_usd_est": 4.0})
    assert r["over_max"] is True and "выше ожидаемого максимума" in r["note"]


@pytest.mark.unit
def test_delta_is_unavailable_when_no_estimate():
    r = ca.estimate_vs_actual({"estimate_status": "unavailable", "cost_median": None},
                              {"cost_usd_est": 2.5})
    assert r["delta_usd"] is None and r["status"] == "unavailable"
    assert "unavailable" in r["note"]                 # не 0


@pytest.mark.unit
def test_delta_is_unavailable_when_actual_unknown():
    r = ca.estimate_vs_actual({"estimate_status": "measured_history", "cost_median": 2.0},
                              {"cost_usd_est": None})
    assert r["delta_usd"] is None and r["status"] == "unavailable"


@pytest.mark.unit
def test_delta_accepts_a_bare_number_as_actual():
    r = ca.estimate_vs_actual({"estimate_status": "measured_history", "cost_median": 2.0}, 3.0)
    assert r["actual_usd"] == 3.0 and r["delta_usd"] == 1.0


# ─── проводка в контур: run report несёт roid_outcome и cost_delta ───────────────────────────────

@pytest.mark.unit
def test_run_report_carries_outcome_kpi_and_delta_wiring():
    """Модуль проведён: lifecycle кладёт roid_outcome, reporting — cost_delta (built != wired guard)."""
    import ast
    from pathlib import Path
    kit = Path(__file__).resolve().parents[2]
    life = (kit / "ai_ops_kit" / "engine" / "ai_ops_run_lifecycle.py").read_text(encoding="utf-8")
    rep = (kit / "ai_ops_kit" / "engine" / "ai_ops_run_reporting.py").read_text(encoding="utf-8")
    assert "roid_outcome_report" in life and 'rep["roid_outcome"]' in life
    assert "estimate_vs_actual" in rep and 'rep["cost_delta"]' in rep
    ast.parse(life); ast.parse(rep)          # правки синтаксически валидны
