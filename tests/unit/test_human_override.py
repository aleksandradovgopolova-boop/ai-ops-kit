"""Тесты Human Override (PR-20): override — сигнал на будущее, а не ошибка; виден дальше."""
from __future__ import annotations

from ai_ops_kit.governance import decision_log as dl
from ai_ops_kit.governance import human_override as ho

REGISTRY = """\
schema_version: 1
kind: decisions-registry

episodes:
  - id: ep-existing
    question: Q
    decision: D
    reason: R
    reversibility: two-way
    date: 2026-08-01
"""


def _write(root):
    (root / "decisions").mkdir(exist_ok=True)
    (root / dl.REGISTRY_REL).write_text(REGISTRY, encoding="utf-8")


def test_override_recorded_as_signal_not_error(tmp_path):
    _write(tmp_path)
    ep = ho.record_override(
        tmp_path, target="priority:work-X", ai_recommendation="сделать X первым",
        human_decision="сначала Y", reason="стратегический сдвиг", date="2026-08-20")
    assert ep["human_overrode"] is True
    assert "не ошибка" in ep["outcome"]           # запись помечена как сигнал, не провал


def test_override_is_visible_to_future_decisions(tmp_path):
    _write(tmp_path)
    ho.record_override(tmp_path, target="roadmap", ai_recommendation="Now: A",
                       human_decision="Now: B", reason="клиентский запрос", date="2026-08-20")
    sigs = ho.override_signals(tmp_path)
    assert len(sigs) == 1
    s = sigs[0]
    assert s["target"] == "roadmap"
    assert s["human_decision"] == "Now: B"
    assert s["ai_recommendation"] == "Now: A"
    assert s["reason"] == "клиентский запрос"


def test_override_lands_in_decision_log(tmp_path):
    _write(tmp_path)
    ho.record_override(tmp_path, target="status:work-Y", ai_recommendation="done",
                       human_decision="todo", reason="не проверено", date="2026-08-20")
    ai = dl.ai_decisions(tmp_path)
    assert any(e.get("human_overrode") for e in ai)


def test_multiple_overrides_accumulate(tmp_path):
    _write(tmp_path)
    ho.record_override(tmp_path, target="priority:a", ai_recommendation="1",
                       human_decision="2", reason="r1", date="2026-08-20")
    ho.record_override(tmp_path, target="priority:b", ai_recommendation="3",
                       human_decision="4", reason="r2", date="2026-08-21")
    assert len(ho.overrides(tmp_path)) == 2


def test_non_override_ai_decisions_are_not_counted(tmp_path):
    _write(tmp_path)
    # обычное решение AI без override
    dl.log_ai_decision(tmp_path, decision_id="ai-plain", question="q", decision="d",
                       reason="r", date="2026-08-20", data="d", human_overrode=False)
    assert ho.overrides(tmp_path) == []
    assert ho.override_signals(tmp_path) == []
