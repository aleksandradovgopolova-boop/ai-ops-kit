"""Быстрый путь (заявка владельца): size:small + risk:low, не эскалированное к L2+, идёт мимо
плана (author) и приёмки (review) — остаётся обычный PR (ревью человека + CI).

Опасное быстрый путь НЕ открывает: классификатор эскалирует необратимое/секретное/высокий риск
к L3, и пометить рискованное как small не поможет — уровень считает сигналы риска, не size.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.cli.ai_ops_cli import resolve_flags


@pytest.mark.unit
class TestFastPath:
    def test_small_low_engineering_skips_plan_and_acceptance(self):
        f = resolve_flags({"task_type": "ENGINEERING", "size": "small", "risk": "low"})
        assert f.get("fast_path") is True
        assert f["review"] is False and f["author"] is False

    def test_quick_small_low_is_fast_path(self):
        f = resolve_flags({"task_type": "QUICK", "size": "small", "risk": "low"})
        assert f.get("fast_path") is True
        assert f["review"] is False and f["author"] is False

    def test_product_keeps_full_path(self):
        # PRODUCT (L2) — продуктовая ставка, церемония остаётся даже при small/low.
        f = resolve_flags({"task_type": "PRODUCT", "size": "small", "risk": "low"})
        assert f.get("fast_path") is not True
        assert f["review"] is True and f["author"] is True

    def test_irreversible_small_low_forced_to_full_path(self):
        # size small, risk low, НО необратимо -> классификатор -> L3 -> быстрый путь закрыт.
        f = resolve_flags({"task_type": "ENGINEERING", "size": "small", "risk": "low",
                           "irreversible": True})
        assert f.get("fast_path") is not True
        assert f["review"] is True and f["author"] is True

    def test_secret_boundary_small_low_forced_to_full_path(self):
        f = resolve_flags({"task_type": "ENGINEERING", "size": "small", "risk": "low",
                           "secret_boundary": True})
        assert f.get("fast_path") is not True
        assert f["review"] is True and f["author"] is True

    def test_medium_size_keeps_full_path(self):
        f = resolve_flags({"task_type": "ENGINEERING", "size": "medium", "risk": "low"})
        assert f.get("fast_path") is not True
        assert f["review"] is True and f["author"] is True

    def test_high_risk_keeps_full_path(self):
        f = resolve_flags({"task_type": "ENGINEERING", "size": "small", "risk": "high"})
        assert f.get("fast_path") is not True
        assert f["review"] is True and f["author"] is True
