"""Гранулярные тесты context_cost (мигрировано из test_context_cost_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.context.context_cost import (
    Path,
    estimate,
    estimate_tokens,
    summary_line,
)


@pytest.mark.unit
class TestEstimateTokens:
    def test_cyrillic_more_expensive(self):
        assert estimate_tokens("абвг" * 25) > estimate_tokens("abcd" * 25)

    def test_empty_text_zero(self):
        assert estimate_tokens("") == 0


@pytest.fixture
def cost_repo(tmp_path):
    root = tmp_path
    cc = root / ".ai/project/context/product"
    cc.mkdir(parents=True)
    (cc.parent / "now.md").write_text("---\nread_tier: 1\n---\n" + "снимок " * 50, encoding="utf-8")
    (cc / "ProductStatus.md").write_text("---\nread_tier: 1\n---\n" + "статус " * 50, encoding="utf-8")
    (cc / "MetricCatalog.md").write_text("---\nread_tier: 3\n---\n" + "метрика " * 500, encoding="utf-8")
    (root / "CLAUDE.md").write_text("правила " * 30, encoding="utf-8")
    sk = root / ".claude/skills/demo"
    sk.mkdir(parents=True)
    (sk / "SKILL.md").write_text("---\nname: demo\ndescription: короткое описание скилла\n---\n# тело",
                                 encoding="utf-8")
    (root / ".ai-ops.yaml").write_text("context_budget:\n  session_start_tokens: 200\n", encoding="utf-8")
    return root


@pytest.mark.unit
class TestEstimate:
    def test_tier1_includes_now_and_status(self, cost_repo):
        rep = estimate(str(cost_repo))
        tier1_paths = [i["path"] for i in rep["items"] if i["bucket"] == "tier1_context"]
        assert len(tier1_paths) == 2

    def test_tier3_not_in_start(self, cost_repo):
        rep = estimate(str(cost_repo))
        tier1_paths = [i["path"] for i in rep["items"] if i["bucket"] == "tier1_context"]
        assert not any("MetricCatalog" in p for p in tier1_paths)

    def test_claude_md_counted(self, cost_repo):
        rep = estimate(str(cost_repo))
        assert "claude_md" in rep["buckets"]

    def test_skill_description_counted(self, cost_repo):
        rep = estimate(str(cost_repo))
        assert rep["buckets"].get("skill_descriptions", 0) > 0

    def test_budget_from_config(self, cost_repo):
        rep = estimate(str(cost_repo))
        assert rep["budget"] == 200

    def test_small_budget_exceeded(self, cost_repo):
        rep = estimate(str(cost_repo))
        assert rep["total_tokens"] > 200 and rep["within_budget"] is False

    def test_budget_override(self, cost_repo):
        assert estimate(str(cost_repo), budget=10_000)["within_budget"] is True

    def test_summary_line(self, cost_repo):
        assert "стоимость старта" in summary_line(str(cost_repo))
