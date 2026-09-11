"""Кластер обучения проведён в контур пост-релизным путём (#584/#586).

Доказательство built≠wired → built: `run_post_release` РАНТАЙМ-ПУТЁМ зовёт `outcome_analytics` и
`evolution_triggers` (dormant-inventory их больше не помечает — отдельный контракт-тест), а из
измеренного исхода рождается прецедент (факт + число случаев, без причинности).
"""
from __future__ import annotations

from pathlib import Path

import yaml

from ai_ops_kit.cli import post_release_loop as prl

PKG_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_PRR = PKG_ROOT / "examples" / "readout-demo" / "PRR-001.yaml"

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


def _readout(value, *, target_met="yes"):
    return {"schema_version": 1, "kind": "OutcomeReadout",
            "measured": {"metric": "activation_rate", "value": value, "measured_at": "2026-09-16"},
            "target_met": target_met, "hypothesis": "confirmed"}


def _child(tmp_path):
    root = tmp_path / "product"
    root.mkdir(parents=True)
    return root


def test_cost_analytics_is_wired_into_runtime(tmp_path):
    """Пост-релизный путь зовёт outcome_analytics — ключ cost_analytics всегда в результате."""
    res = prl.run_post_release(str(EXAMPLE_PRR), _child(tmp_path))
    assert "cost_analytics" in res
    assert res["cost_analytics"]["available"] is True
    # Нет журнала расхода в синтетической дочке — честный дефолт, а не выдуманные числа.
    assert res["cost_analytics"]["measured"] is False


def test_attention_is_wired_into_runtime(tmp_path):
    """#676: пост-релизный путь зовёт attention_bus — ключ attention всегда в результате, и снятый
    повод остаётся в замере (нижняя граница человеческого внимания на путь к исходу)."""
    from ai_ops_kit.lifecycle import attention_bus
    root = _child(tmp_path)
    attention_bus.record(root, key="preflight:w1", source="прогон: preflight",
                         reason="работа остановлена", kind=attention_bus.BLOCKED, work_id="w1")
    attention_bus.record(root, key="gov:w1", source="граница решений",
                         reason="решение за человеком", kind=attention_bus.DECISION, work_id="w1")
    attention_bus.resolve(root, "preflight:w1")   # снят — но замер #676 его помнит

    res = prl.run_post_release(str(EXAMPLE_PRR), root)
    att = res["attention"]
    assert att["available"] is True
    assert att["total"] == 2 and att["decision"] == 1 and att["blocked"] == 1 and att["pending"] == 1
    assert "человеческое внимание: 2" in prl.render(res)


def test_attention_zero_when_no_calls(tmp_path):
    """Пустая шина -> 0 обращений (честный дефолт), строку в разборе не печатаем."""
    res = prl.run_post_release(str(EXAMPLE_PRR), _child(tmp_path))
    assert res["attention"] == {"available": True, "total": 0, "decision": 0,
                                "blocked": 0, "pending": 0, "resolved": 0}
    assert "человеческое внимание" not in prl.render(res)


def test_evolution_triggers_wired_honest_default(tmp_path):
    """evolution_triggers зовётся; без ADR/health — available:false с причиной, не выдуманные триггеры."""
    res = prl.run_post_release(str(EXAMPLE_PRR), _child(tmp_path))
    ev = res["evolution_triggers"]
    assert ev["available"] is False and ev["trigger_count"] == 0
    assert ev["reason"]


def test_evolution_triggers_fire_with_adr_and_health(tmp_path):
    """С реестром ADR (обещает improve) и просевшим health-отчётом триггер срабатывает (реальный путь)."""
    root = _child(tmp_path)
    adr_dir = root / "decisions" / "adr"
    adr_dir.mkdir(parents=True)
    adr = {"schema_version": 1, "kind": "ArchitectureDecision", "id": "ADR-0001",
           "status": "accepted", "title": "t", "context": "c", "decision": "d",
           "consequences": {"positive": ["p"], "negative": ["n"]},
           "quality_attributes": [{"attribute": "reliability", "effect": "improves"}]}
    (adr_dir / "ADR-0001.yaml").write_text(yaml.safe_dump(adr, allow_unicode=True), encoding="utf-8")
    health = {"schema_version": 1, "kind": "product-health-report", "scope": "s", "period": "p",
              "health_score": {"band": "red"},
              "metrics": {"reliability": {"normalized": 0.3}}}
    (root / "product-health-report.json").write_text(
        __import__("json").dumps(health), encoding="utf-8")
    res = prl.run_post_release(str(EXAMPLE_PRR), root)
    ev = res["evolution_triggers"]
    assert ev["available"] is True
    assert ev["trigger_count"] >= 1
    assert any(t["kind"] == "promise_broken" for t in ev["triggers"])


def test_measured_outcome_yields_precedent_single_case(tmp_path):
    """Измеренный исход → прецедент 1 случая (не «правило»), без поля причинности (#586)."""
    res = prl.run_post_release(str(EXAMPLE_PRR), _child(tmp_path),
                               contract=CONTRACT, readout=_readout(40))
    p = res["precedent"]
    assert p is not None
    assert p["case_count"] == 1 and p["confidence"] == "single-case"
    assert not ({"causation", "rule", "transferable", "recommendation"} & set(p))


def test_no_measure_no_precedent(tmp_path):
    """Без замера (unknown) прецедента нет — данных для него ещё нет."""
    res = prl.run_post_release(str(EXAMPLE_PRR), _child(tmp_path))
    assert res["precedent"] is None
