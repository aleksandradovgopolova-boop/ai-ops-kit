"""Промпты ревьюера и автора обёрнуты в XML-якори.

Работа `reviewer-prompt-uses-xml-anchors-measured` (цель `green-means-checked`).

Утверждение (подтверждено направлением Anthropic): чёткие секционные якори (XML-теги)
держат точность на длинном контексте лучше, чем сплошной блок с маркерами `=== ... ===`.

Границы: НЕ трогаем JSON-схемы на диске; не меняем формат ВЫВОДА; речь только о разметке
ВХОДА промптов (роль, задача, критерии, дифф, правила).
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract]


class TestReviewerPromptXmlAnchors:
    """Промпты ревьюера содержат XML-якори."""

    def test_acceptance_proposer_has_xml_tags(self):
        """make_acceptance_proposer строит промпт с <role>, <task>, <criteria>, <diff>."""
        from ai_ops_kit.engine.acceptance_verify import make_acceptance_proposer

        def fake_provider(prompt):
            # Захватываем промпт и возвращаем валидный JSON
            fake_provider.last_prompt = prompt
            return '{"kind":"acceptance-result","criteria":[]}'

        criteria = [{"id": "AC-1", "text": "test criterion"}]
        proposer = make_acceptance_proposer(fake_provider, criteria, revision="abc123")
        proposer("fake context with diff")

        prompt = fake_provider.last_prompt
        for tag in ("<role>", "</role>", "<task>", "</task>",
                    "<criteria>", "</criteria>", "<diff>", "</diff>",
                    "<rules>", "</rules>"):
            assert tag in prompt, (
                f"промпт ревьюера приёмки не содержит XML-якорь {tag} — "
                f"секции не размечены для LLM (reviewer-prompt-uses-xml-anchors-measured)")

    def test_gate_reviewer_proposer_has_xml_tags(self):
        """make_reviewer_proposer строит промпт с <role>, <diff>, <rules>."""
        from ai_ops_kit.engine.tool_loop import make_reviewer_proposer

        def fake_provider(prompt):
            fake_provider.last_prompt = prompt
            return '{"kind":"reviewer-result","gate":"test","status":"pass","checks":[],"blockers":[]}'

        proposer = make_reviewer_proposer(
            fake_provider, gate_id="test_gate",
            checklist="1. Check X\n2. Check Y",
            required_evidence=["file_exists"],
            reviewed_revision="abc123")
        proposer("fake diff context")

        prompt = fake_provider.last_prompt
        for tag in ("<role>", "</role>", "<diff>", "</diff>",
                    "<rules>", "</rules>", "<criteria>", "</criteria>"):
            assert tag in prompt, (
                f"промпт ревьюера гейта не содержит XML-якорь {tag} — "
                f"секции не размечены для LLM (reviewer-prompt-uses-xml-anchors-measured)")

    def test_no_old_style_markers_in_reviewer_prompts(self):
        """Старые маркеры `=== ЗАДАЧА ===` и `=== КОНТЕКСТ ===` заменены XML-якорями."""
        from ai_ops_kit.engine import acceptance_verify, tool_loop

        for mod in (acceptance_verify, tool_loop):
            source = inspect.getsource(mod)
            assert "=== ЗАДАЧА ===" not in source, (
                f"{mod.__name__}: старый маркер '=== ЗАДАЧА ===' не заменён XML-якорем")
            assert "=== КОНТЕКСТ" not in source, (
                f"{mod.__name__}: старый маркер '=== КОНТЕКСТ' не заменён XML-якорем")
