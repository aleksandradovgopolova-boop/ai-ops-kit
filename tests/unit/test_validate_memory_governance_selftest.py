"""Селфтест validate_memory_governance, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_memory_governance import (  # noqa: F401 — имена, которые использует тело
    DEFAULT,
    check,
    yaml,
)


@pytest.mark.slow
def test_validate_memory_governance_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    base = {"schema_version": 1, "kind": "MemoryGovernancePolicy", "policy_id": "MGP-001",
            "entries": [{"id": "m1", "provenance": {"origin": "user", "source_type": "human"},
                         "expiry": {"mode": "ttl_days", "value": 90}, "self_ingested": False}]}
    expect("валидная MGP проходит", check(base) == [])
    expect("нет provenance.origin -> ошибка",
           any("provenance.origin" in x for x in check({**base, "entries": [
               {"id": "m", "provenance": {"source_type": "human"}, "expiry": {"mode": "ttl_days", "value": 1}, "self_ingested": False}]})))
    expect("derived без upstream -> ошибка",
           any("upstream" in x for x in check({**base, "entries": [
               {"id": "m", "provenance": {"origin": "o", "source_type": "derived"}, "expiry": {"mode": "permanent", "justification": "j"}, "self_ingested": False}]})))
    expect("permanent без justification -> ошибка",
           any("justification" in x for x in check({**base, "entries": [
               {"id": "m", "provenance": {"origin": "o", "source_type": "human"}, "expiry": {"mode": "permanent"}, "self_ingested": False}]})))
    expect("ttl_days<=0 -> ошибка",
           any("ttl_days" in x for x in check({**base, "entries": [
               {"id": "m", "provenance": {"origin": "o", "source_type": "human"}, "expiry": {"mode": "ttl_days", "value": 0}, "self_ingested": False}]})))
    expect("self_ingested без human_confirmed -> ошибка (no-self-ingestion)",
           any("self-ingestion" in x for x in check({**base, "entries": [
               {"id": "m", "provenance": {"origin": "agent", "source_type": "system"}, "expiry": {"mode": "ttl_days", "value": 7}, "self_ingested": True}]})))
    expect("self_ingested + human_confirmed -> ок",
           check({**base, "entries": [
               {"id": "m", "provenance": {"origin": "agent", "source_type": "system"}, "expiry": {"mode": "ttl_days", "value": 7}, "self_ingested": True, "human_confirmed": True}]}) == [])

    if DEFAULT.exists():
        errs = check(yaml.safe_load(DEFAULT.read_text(encoding="utf-8")))
        expect(f"реальный {DEFAULT.name} валиден", errs == [])
        for x in errs:
            print("   -", x)

    assert ok, "перенесённый селфтест validate_memory_governance: см. строки FAIL в выводе"
