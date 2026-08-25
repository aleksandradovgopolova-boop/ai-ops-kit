"""D2: Цены per-token живут в registry/models.yaml, orchestrator_usage читает их оттуда.

Sync-тест: _PRICE_PER_MTOK в коде совпадает с pricing.per_mtok из registry/models.yaml.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REGISTRY_PATH = _REPO_ROOT / "registry" / "models.yaml"


def _registry_pricing() -> dict:
    """Прочитать pricing.per_mtok из registry/models.yaml напрямую."""
    data = yaml.safe_load(_REGISTRY_PATH.read_text(encoding="utf-8"))
    result = {}
    for m in data.get("models", []):
        mid = m.get("id")
        pricing = m.get("pricing") or {}
        per_mtok = pricing.get("per_mtok") or {}
        p_in = per_mtok.get("input")
        p_out = per_mtok.get("output")
        if mid and isinstance(p_in, (int, float)) and isinstance(p_out, (int, float)):
            result[mid] = {"in": float(p_in), "out": float(p_out)}
    return result


@pytest.mark.unit
def test_pricing_matches_registry():
    """_PRICE_PER_MTOK в orchestrator_usage совпадает с registry/models.yaml."""
    from ai_ops_kit.providers.orchestrator_usage import _PRICE_PER_MTOK

    registry = _registry_pricing()
    for model_id, expected_price in registry.items():
        assert model_id in _PRICE_PER_MTOK, (
            f"Модель {model_id!r} имеет pricing в registry/models.yaml, "
            f"но отсутствует в _PRICE_PER_MTOK"
        )
        assert abs(_PRICE_PER_MTOK[model_id]["in"] - expected_price["in"]) < 0.001, (
            f"_PRICE_PER_MTOK[{model_id!r}]['in'] = {_PRICE_PER_MTOK[model_id]['in']}, "
            f"но в registry = {expected_price['in']}"
        )
        assert abs(_PRICE_PER_MTOK[model_id]["out"] - expected_price["out"]) < 0.001, (
            f"_PRICE_PER_MTOK[{model_id!r}]['out'] = {_PRICE_PER_MTOK[model_id]['out']}, "
            f"но в registry = {expected_price['out']}"
        )


@pytest.mark.unit
def test_pricing_no_extra_models():
    """_PRICE_PER_MTOK не содержит моделей, которых нет в реестре (устаревшие записи)."""
    from ai_ops_kit.providers.orchestrator_usage import _PRICE_PER_MTOK

    registry = _registry_pricing()
    extra = set(_PRICE_PER_MTOK.keys()) - set(registry.keys())
    assert not extra, (
        f"_PRICE_PER_MTOK содержит модели, отсутствующие в registry/models.yaml: {sorted(extra)}. "
        f"Удалите устаревшие записи — реестр единственный SoT."
    )


@pytest.mark.unit
def test_pricing_deepseek_chat_present():
    """deepseek-chat имеет цену в реестре — критично для оценки cost."""
    from ai_ops_kit.providers.orchestrator_usage import _PRICE_PER_MTOK

    assert "deepseek-chat" in _PRICE_PER_MTOK
    assert _PRICE_PER_MTOK["deepseek-chat"]["in"] == 0.27
    assert _PRICE_PER_MTOK["deepseek-chat"]["out"] == 1.10


@pytest.mark.unit
def test_pricing_registry_has_status():
    """Каждая запись pricing в реестре имеет поле status (documented/inferred/pending)."""
    data = yaml.safe_load(_REGISTRY_PATH.read_text(encoding="utf-8"))
    for m in data.get("models", []):
        pricing = m.get("pricing")
        if pricing is None:
            continue  # pricing опционален
        mid = m.get("id")
        assert "status" in pricing, (
            f"Модель {mid!r} имеет pricing, но без поля status. "
            f"status обязателен: documented/inferred/pending."
        )
        assert pricing["status"] in ("documented", "inferred", "pending"), (
            f"Модель {mid!r}: pricing.status={pricing['status']!r} — "
            f"допустимы только documented/inferred/pending"
        )


@pytest.mark.unit
def test_pricing_loads_at_import():
    """_PRICE_PER_MTOK загружается при импорте модуля (не пустой)."""
    from ai_ops_kit.providers.orchestrator_usage import _PRICE_PER_MTOK

    assert len(_PRICE_PER_MTOK) > 0, "_PRICE_PER_MTOK пуст — registry/models.yaml не прочитан"


@pytest.mark.unit
def test_record_call_uses_registry_price():
    """_record_call оценивает cost по ценам из реестра (не по хардкоду)."""
    from ai_ops_kit.providers.orchestrator_usage import _record_call, drain_call_stats, _PRICE_PER_MTOK

    # Записываем вызов с токенами для модели из реестра
    _record_call("deepseek-chat", 1000, 500, 1.5, provider="deepseek")
    stats = drain_call_stats()
    assert len(stats) == 1
    rec = stats[0]
    # Ожидаемая стоимость: 1000/1e6 * 0.27 + 500/1e6 * 1.10 = 0.00027 + 0.00055 = 0.00082
    expected = round(1000 / 1e6 * _PRICE_PER_MTOK["deepseek-chat"]["in"]
                     + 500 / 1e6 * _PRICE_PER_MTOK["deepseek-chat"]["out"], 6)
    assert rec["cost_status"] == "estimated"
    assert abs(rec["cost"] - expected) < 1e-9
