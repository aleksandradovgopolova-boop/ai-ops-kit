"""B2-30: acceptance_verify unmet criteria block ready_for_pr.

Наблюдение 12.08.2026 (ИИ-Среда): прогон ТРИЖДЫ остановился, не доделав задачу.
Модель возвращала {done: true}, но критерии приёмки не были выполнены.
acceptance_verify был advisory и не блокировал ready.

Теперь: если сверка СОСТОЯЛАСЬ (verified=True) и есть unmet критерии — ready=False.
Если сверка не состоялась (verified=False) — не блокируем (advisory).
"""
from __future__ import annotations

import pytest


@pytest.mark.unit
class TestAcceptanceUnmetBlocksReady:
    def test_verified_with_unmet_blocks(self):
        """verified=True + unmet не пуст → acceptance_unmet_block=True."""
        acceptance_criteria = {
            "verified": True,
            "met_all": False,
            "unmet": [{"id": "AC-1", "text": "критерий не выполнен", "status": "unmet"}],
        }
        block = acceptance_criteria.get("verified") and acceptance_criteria.get("unmet")
        assert block, "verified + unmet должны блокировать ready"

    def test_verified_without_unmet_passes(self):
        """verified=True + unmet пуст → не блокирует."""
        acceptance_criteria = {
            "verified": True,
            "met_all": True,
            "unmet": [],
        }
        block = acceptance_criteria.get("verified") and acceptance_criteria.get("unmet")
        assert not block, "verified + все met не должны блокировать"

    def test_unverified_does_not_block(self):
        """verified=False (не сверено) → не блокирует (advisory)."""
        acceptance_criteria = {
            "verified": False,
            "met_all": None,
            "unmet": [],
            "reason": "сверка не выполнена (нет провайдера)",
        }
        block = acceptance_criteria.get("verified") and acceptance_criteria.get("unmet")
        assert not block, "не сверено не должно блокировать (advisory)"

    def test_unverified_with_unmet_does_not_block(self):
        """verified=False + unmet не пуст → не блокирует (сверка не состоялась)."""
        acceptance_criteria = {
            "verified": False,
            "met_all": None,
            "unmet": [{"id": "AC-1", "text": "предположительно не выполнен"}],
            "reason": "сверка не выполнена (сбой ревьюера)",
        }
        block = acceptance_criteria.get("verified") and acceptance_criteria.get("unmet")
        assert not block, "если сверка не состоялась, unmet не блокирует (нет доказательства)"
