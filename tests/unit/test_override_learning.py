"""Тесты learning from human overrides — прошлые override'ы меняют рекомендации."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ai_ops_kit.governance import override_learning
from ai_ops_kit.governance.decision_log import REGISTRY_REL


def _write_registry(root: Path, episodes: list[dict]):
    """Записывает decisions/registry.yaml с эпизодами."""
    reg = root / REGISTRY_REL
    reg.parent.mkdir(parents=True, exist_ok=True)
    data = {"episodes": episodes}
    reg.write_text(yaml.dump(data, allow_unicode=True))


def _ai_episode_with_override(
    *, decision_id: str, target: str, human_decision: str, ai_recommendation: str = "do X"
) -> dict:
    """Создаёт AI-эпизод с human_overrode=true."""
    return {
        "id": decision_id,
        "actor": "ai",
        "question": f"Переопределить {target}?",
        "decision": human_decision,
        "reason": "human knows better",
        "date": "2026-08-25",
        "data": f"AI рекомендовал: {ai_recommendation}",
        "outcome": "override",
        "human_overrode": True,
        "context": {"override_target": target, "ai_recommendation": ai_recommendation},
    }


class TestAdjustPriority:
    def test_no_overrides_no_change(self, tmp_path: Path):
        _write_registry(tmp_path, [])
        result = override_learning.adjust_priority(
            tmp_path, work_id="work-1", base_score=0.5
        )
        assert result["adjusted_score"] == 0.5
        assert result["override_count"] == 0
        assert "без override'ов" in result["explanation"]

    def test_override_changes_recommendation(self, tmp_path: Path):
        """ГЛАВНЫЙ ТЕСТ: рекомендация С override отличается от такой же БЕЗ override."""
        # Без override'ов
        _write_registry(tmp_path, [])
        without = override_learning.adjust_priority(
            tmp_path, work_id="work-1", base_score=0.5
        )

        # С override (человек повысил приоритет)
        episode = _ai_episode_with_override(
            decision_id="ov-1",
            target="priority:work-1",
            human_decision="priority up — это важнее",
        )
        _write_registry(tmp_path, [episode])
        with_override = override_learning.adjust_priority(
            tmp_path, work_id="work-1", base_score=0.5
        )

        # Ключевое утверждение: рекомендации РАЗНЫЕ
        assert with_override["adjusted_score"] != without["adjusted_score"]
        assert with_override["adjusted_score"] > 0.5  # повысился
        assert with_override["override_count"] == 1

    def test_downward_override_decreases(self, tmp_path: Path):
        episode = _ai_episode_with_override(
            decision_id="ov-2",
            target="priority:work-2",
            human_decision="priority down — не срочно",
        )
        _write_registry(tmp_path, [episode])
        result = override_learning.adjust_priority(
            tmp_path, work_id="work-2", base_score=0.7
        )
        assert result["adjusted_score"] < 0.7

    def test_multiple_overrides_stronger_shift(self, tmp_path: Path):
        episodes = [
            _ai_episode_with_override(
                decision_id=f"ov-{i}",
                target="priority:work-3",
                human_decision="priority up",
            )
            for i in range(3)
        ]
        _write_registry(tmp_path, episodes)
        result = override_learning.adjust_priority(
            tmp_path, work_id="work-3", base_score=0.5
        )
        # 3 override × 0.15 = 0.45, но ограничено MAX_SHIFT=0.4
        assert result["override_shift"] == pytest.approx(0.4, abs=0.01)

    def test_mixed_overrides_cancel(self, tmp_path: Path):
        episodes = [
            _ai_episode_with_override(
                decision_id="ov-up", target="priority:work-4", human_decision="up"
            ),
            _ai_episode_with_override(
                decision_id="ov-down", target="priority:work-4", human_decision="down"
            ),
        ]
        _write_registry(tmp_path, episodes)
        result = override_learning.adjust_priority(
            tmp_path, work_id="work-4", base_score=0.5
        )
        # 1 up - 1 down = 0, сдвиг нулевой
        assert result["adjusted_score"] == 0.5

    def test_score_clamped_to_0_1(self, tmp_path: Path):
        # Много override'ов вверх из почти максимального score
        episodes = [
            _ai_episode_with_override(
                decision_id=f"ov-{i}", target="priority:x", human_decision="up"
            )
            for i in range(5)
        ]
        _write_registry(tmp_path, episodes)
        result = override_learning.adjust_priority(
            tmp_path, work_id="x", base_score=0.9
        )
        assert 0.0 <= result["adjusted_score"] <= 1.0


class TestAdjustRisk:
    def test_no_overrides_no_change(self, tmp_path: Path):
        _write_registry(tmp_path, [])
        result = override_learning.adjust_risk(
            tmp_path, risk_category="delivery", base_severity=0.7
        )
        assert result["adjusted_severity"] == 0.7
        assert result["override_count"] == 0

    def test_rejected_risk_lowered(self, tmp_path: Path):
        episode = _ai_episode_with_override(
            decision_id="risk-ov-1",
            target="risk:delivery",
            human_decision="reject — не риск",
        )
        _write_registry(tmp_path, [episode])
        result = override_learning.adjust_risk(
            tmp_path, risk_category="delivery", base_severity=0.8
        )
        assert result["adjusted_severity"] < 0.8

    def test_confirmed_risk_not_lowered(self, tmp_path: Path):
        episode = _ai_episode_with_override(
            decision_id="risk-ov-2",
            target="risk:delivery",
            human_decision="accept — риск реален",
        )
        _write_registry(tmp_path, [episode])
        result = override_learning.adjust_risk(
            tmp_path, risk_category="delivery", base_severity=0.8
        )
        # 'accept' = 'up' = подтверждение; для рисков это НЕ снижает severity
        assert result["adjusted_severity"] >= 0.8
