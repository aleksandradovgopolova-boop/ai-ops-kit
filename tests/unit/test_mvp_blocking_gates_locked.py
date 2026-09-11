"""Защёлка на инвариант «blocking-гейтов MVP-хребта <= 8» + его целостность.

ИНВАРИАНТ (AGENTS.md): для `quality/gates.yaml` — «blocking-гейтов MVP-хребта <= 8». Речь про
ВСЕГДА-включённый SDLC-хребет (`mvp_blocking_gates`): эти 8 гейтов блокируют выпуск безусловно.
Прочие `blocking: true` — доменные гейты (ux_review, deploy_readiness, ...), блокирующие УСЛОВНО,
только когда их фаза/условие применимы; суммарная блокирующая поверхность поэтому больше 8, и это
by design (пояснено комментарием в gates.yaml рядом с `mvp_blocking_gates`).

До этой защёлки «<= 8» держалось только прозой AGENTS.md — расширить хребет до 9 можно было молча.
Здесь проверяется и потолок, и то, что каждый элемент хребта реально существует в реестре и несёт
`blocking: true` (хребет не может ссылаться на несуществующий или неблокирующий гейт).
"""
from __future__ import annotations

import pytest

from ai_ops_kit.gates.gate_executor import PKG, load_gates, yaml

MVP_BACKBONE_CEILING = 8


def _mvp_blocking_gates() -> list:
    doc = yaml.safe_load((PKG / "quality" / "gates.yaml").read_text(encoding="utf-8"))
    return doc["mvp_blocking_gates"]


@pytest.mark.unit
class TestMvpBlockingGatesLocked:
    """SDLC-хребет: потолок 8 и целостность ссылок против живого реестра гейтов."""

    def test_backbone_size_is_within_ceiling(self):
        """`len(mvp_blocking_gates) <= 8` — расширение хребта до 9 краснит тест."""
        backbone = _mvp_blocking_gates()
        assert len(backbone) <= MVP_BACKBONE_CEILING, len(backbone)

    def test_every_backbone_gate_exists_in_registry(self):
        """Каждый элемент хребта — реальный гейт в `gates` (behavioral: зовём load_gates)."""
        gates = load_gates()
        missing = [g for g in _mvp_blocking_gates() if g not in gates]
        assert missing == [], missing

    def test_every_backbone_gate_is_blocking(self):
        """Каждый гейт хребта несёт `blocking: true` — хребет не может опираться на advisory."""
        gates = load_gates()
        not_blocking = [g for g in _mvp_blocking_gates() if not gates[g].get("blocking")]
        assert not_blocking == [], not_blocking

    def test_domain_gates_block_conditionally_beyond_backbone(self):
        """Суммарная блокирующая поверхность > хребта — доменные гейты блокируют условно (by design)."""
        gates = load_gates()
        blocking_total = sum(1 for g in gates.values() if g.get("blocking"))
        # Хребет — подмножество всех блокирующих; доменные добавляют условную поверхность сверху.
        assert blocking_total >= len(_mvp_blocking_gates())
