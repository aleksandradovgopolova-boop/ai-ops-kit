"""Тест сверяет _EVIDENCE_KEYS в gate_executor с schemas/gate-evidence.schema.json.

gate_executor валидирует evidence по _EVIDENCE_KEYS и цитирует схему, но схему не читает.
Если они разошлись — валидация в коде пропускает то, что схема запрещает (или наоборот).
Тест краснеет на расхождении код↔схема, заставляя держать их синхронными.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
           Path(__file__).resolve().parents[2])


def _load_schema_keys() -> set[str]:
    """Прочитать свойства верхнего уровня из schemas/gate-evidence.schema.json."""
    schema_path = PKG / "schemas" / "gate-evidence.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    # additionalProperties описывает форму каждого gate_id: {...}
    entry_schema = schema["additionalProperties"]
    return set(entry_schema.get("properties", {}).keys())


def _load_code_keys() -> set[str]:
    """Прочитать _EVIDENCE_KEYS из gate_executor."""
    from ai_ops_kit.gates.gate_executor import _EVIDENCE_KEYS
    return set(_EVIDENCE_KEYS)


def test_evidence_keys_match_schema():
    """_EVIDENCE_KEYS в коде == свойства в schemas/gate-evidence.schema.json.

    Расхождение означает: код пропускает поля, которые схема запрещает (или наоборот).
    additionalProperties: false в схеме — источник истины о допустимых полях.
    """
    schema_keys = _load_schema_keys()
    code_keys = _load_code_keys()

    extra_in_code = code_keys - schema_keys
    extra_in_schema = schema_keys - code_keys

    assert not extra_in_code, (
        f"_EVIDENCE_KEYS содержит поля, которых нет в схеме: {sorted(extra_in_code)}. "
        f"Добавьте их в schemas/gate-evidence.schema.json или удалите из кода."
    )
    assert not extra_in_schema, (
        f"Схема содержит поля, которых нет в _EVIDENCE_KEYS: {sorted(extra_in_schema)}. "
        f"Добавьте их в _EVIDENCE_KEYS или удалите из схемы."
    )
    assert code_keys == schema_keys, (
        f"_EVIDENCE_KEYS и схема разошлись: код={sorted(code_keys)}, схема={sorted(schema_keys)}"
    )
