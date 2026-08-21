"""AI-приоритизация (PR-9) и override человека (PR-20): вердикт объясним, unknown честен, override учтён.

Классифицированные задачи в dict-форме — живого GitHub нет. Override пишется/читается через YAML в
tmp_path, к живому реестру не обращаемся.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.planning import backlog_prioritize as bp


def _cls(number, impact="unknown", urgency="unknown", strategic="unknown", effort="unknown",
         confidence="medium", deps=None, title=""):
    return {"number": number, "title": title or f"t{number}", "impact": impact, "urgency": urgency,
            "strategic_alignment": strategic, "effort": effort, "confidence": confidence,
            "dependencies": deps or []}


@pytest.mark.unit
def test_high_signals_beat_unknown():
    hi = bp.score_issue(_cls(1, impact="high", urgency="high", strategic="high", confidence="high"))
    lo = bp.score_issue(_cls(2))
    assert hi.score > lo.score
    assert hi.priority in ("high", "critical") and lo.priority == "low"


@pytest.mark.unit
def test_all_unknown_is_low_confidence_not_high_priority():
    p = bp.score_issue(_cls(1))
    assert p.confidence == "low"                # 3 неизвестных ключевых атрибута
    assert p.priority == "low"                  # unknown не выдаёт себя за высокий приоритет
    assert "неизвестны" in p.explanation


@pytest.mark.unit
def test_explanation_lists_factors():
    p = bp.score_issue(_cls(1, impact="high", urgency="medium"))
    assert "польза" in p.explanation
    assert set(("impact", "urgency", "strategic", "cost_penalty")).issubset(p.factors)


@pytest.mark.unit
def test_blocking_boost_and_blocked_penalty():
    base = bp.score_issue(_cls(1, impact="high", urgency="high"))
    boosted = bp.score_issue(_cls(1, impact="high", urgency="high"), dependents=2)
    blocked = bp.score_issue(_cls(1, impact="high", urgency="high"), blocked_by_open=1)
    assert boosted.score > base.score           # блокирует других → выше
    assert blocked.score < base.score           # сама заблокирована → ниже
    assert "заблокирована" in blocked.explanation


@pytest.mark.unit
def test_cost_lowers_priority():
    cheap = bp.score_issue(_cls(1, impact="high", urgency="high", effort="low"))
    costly = bp.score_issue(_cls(1, impact="high", urgency="high", effort="high"))
    assert cheap.score > costly.score


@pytest.mark.unit
def test_override_roundtrip_and_applied(tmp_path):
    path = tmp_path / "ov.yaml"
    bp.save_override(path, number=5, priority="critical", reason="стратегический дедлайн", by="sasha")
    loaded = bp.load_overrides(path)
    assert loaded[5]["priority"] == "critical"
    assert loaded[5]["reason"] == "стратегический дедлайн"


@pytest.mark.unit
def test_override_beats_computed_and_shows_both(tmp_path):
    p = bp.score_issue(_cls(5))                 # расчётно low
    assert p.computed_priority == "low"
    p2 = bp._apply_override(p, {"priority": "high", "reason": "владелец знает контекст", "by": "sasha"})
    assert p2.priority == "high" and p2.overridden
    assert p2.computed_priority == "low"        # расчёт сохранён рядом с решением человека
    assert "ЧЕЛОВЕК" in p2.explanation and "было расчётно low" in p2.explanation


@pytest.mark.unit
def test_load_overrides_missing_file_is_empty(tmp_path):
    assert bp.load_overrides(tmp_path / "nope.yaml") == {}


class _FakeClient:
    def __init__(self, res):
        self._res = res
        self.repo = "o/r"

    def issues(self, state="open"):
        return self._res


@pytest.mark.unit
def test_prioritize_backlog_unavailable_is_not_empty():
    from ai_ops_kit.integrations.github import FetchResult
    rep = bp.prioritize_backlog(client=_FakeClient(FetchResult(False, reason="нет gh и токена")))
    assert rep.ok is False and "нет gh" in rep.reason
    assert rep.items == []


@pytest.mark.unit
def test_prioritize_backlog_end_to_end_sorted(tmp_path):
    from ai_ops_kit.integrations.github import FetchResult
    # Сырые issue-dict'ы — prioritize_backlog сам их классифицирует.
    items = [
        {"number": 1, "title": "critical сбой", "labels": ["bug", "critical"], "body": "", "state": "open"},
        {"number": 2, "title": "мелкое улучшение", "labels": [], "body": "", "state": "open"},
    ]
    rep = bp.prioritize_backlog(client=_FakeClient(FetchResult(True, items=items, source="gh")))
    assert rep.ok
    # #1 с critical-меткой (impact/urgency high) должен идти раньше #2.
    assert rep.items[0].number == 1
    assert rep.items[0].score > rep.items[1].score
