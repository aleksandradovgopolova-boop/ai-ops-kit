"""D1: MODEL_CONTEXT читается из registry/models.yaml, а не захардкожен.

Sync-тест: значения в коде (MODEL_CONTEXT) совпадают с registry/models.yaml.
Если реестр обновлён — код автоматически подхватывает новые значения.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

# Путь к пакету (tests/ -> корень репо)
_REPO_ROOT = Path(__file__).resolve().parents[2]
_REGISTRY_PATH = _REPO_ROOT / "registry" / "models.yaml"


def _registry_context_windows() -> dict:
    """Прочитать context_window.value из registry/models.yaml напрямую."""
    data = yaml.safe_load(_REGISTRY_PATH.read_text(encoding="utf-8"))
    result = {}
    for m in data.get("models", []):
        mid = m.get("id")
        cw = m.get("context_window") or {}
        val = cw.get("value")
        if mid and isinstance(val, int) and val > 0:
            result[mid] = val
    return result


@pytest.mark.unit
def test_model_context_matches_registry():
    """MODEL_CONTEXT в коде совпадает с registry/models.yaml (sync-тест)."""
    from ai_ops_kit.context.context_compiler import MODEL_CONTEXT

    registry = _registry_context_windows()
    # Каждое значение из реестра должно быть в MODEL_CONTEXT с тем же числом
    for model_id, expected_window in registry.items():
        assert model_id in MODEL_CONTEXT, (
            f"Модель {model_id!r} есть в registry/models.yaml (context_window={expected_window}), "
            f"но отсутствует в MODEL_CONTEXT"
        )
        assert MODEL_CONTEXT[model_id] == expected_window, (
            f"MODEL_CONTEXT[{model_id!r}] = {MODEL_CONTEXT[model_id]}, "
            f"но в registry/models.yaml = {expected_window}"
        )


@pytest.mark.unit
def test_model_context_has_no_extra_models():
    """MODEL_CONTEXT не содержит моделей, которых нет в реестре (устаревшие записи)."""
    from ai_ops_kit.context.context_compiler import MODEL_CONTEXT

    registry = _registry_context_windows()
    extra = set(MODEL_CONTEXT.keys()) - set(registry.keys())
    assert not extra, (
        f"MODEL_CONTEXT содержит модели, отсутствующие в registry/models.yaml: {sorted(extra)}. "
        f"Удалите устаревшие записи — реестр единственный SoT."
    )


@pytest.mark.unit
def test_model_context_deepseek_chat_present():
    """deepseek-chat (основная рабочая модель) имеет окно 64000 — критично для бюджета payload."""
    from ai_ops_kit.context.context_compiler import MODEL_CONTEXT

    assert "deepseek-chat" in MODEL_CONTEXT
    assert MODEL_CONTEXT["deepseek-chat"] == 64_000


@pytest.mark.unit
def test_model_context_loads_at_import():
    """MODEL_CONTEXT загружается при импорте модуля (не пустой)."""
    from ai_ops_kit.context.context_compiler import MODEL_CONTEXT

    assert len(MODEL_CONTEXT) > 0, "MODEL_CONTEXT пуст — registry/models.yaml не прочитан"
