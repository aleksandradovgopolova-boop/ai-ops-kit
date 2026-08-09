"""Селфтест validate_key_lifecycle, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_key_lifecycle import (  # noqa: F401 — имена, которые использует тело
    DEFAULT,
    check,
    yaml,
)


@pytest.mark.slow
def test_validate_key_lifecycle_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    base = {"schema_version": 1, "kind": "KeyLifecyclePolicy", "policy_id": "KLP-001",
            "keys": [{"name": "anthropic", "env_ref": "ANTHROPIC_API_KEY", "ttl_days": 90, "rotation_owner": "human"}],
            "per_agent_identity": {"supported": False, "note": "единый ключ на движок; per-agent identity пока нет"}}
    expect("валидная KLP проходит", check(base) == [])
    expect("ttl_days<=0 -> ошибка",
           any("ttl_days" in x for x in check({**base, "keys": [
               {"name": "k", "env_ref": "K", "ttl_days": 0, "rotation_owner": "human"}]})))
    expect("нет env_ref -> ошибка",
           any("env_ref" in x for x in check({**base, "keys": [
               {"name": "k", "env_ref": "", "ttl_days": 30, "rotation_owner": "human"}]})))
    expect("значение секрета в политике -> ошибка",
           any("ЗНАЧЕНИЕ секрета" in x for x in check({**base, "keys": [
               {"name": "k", "env_ref": "K", "ttl_days": 30, "rotation_owner": "human", "note": "sk-abcdefghijklmnop"}]})))
    expect("per_agent_identity.supported=true без evidence -> ошибка",
           any("без доказательства" in x for x in check({**base, "per_agent_identity": {"supported": True, "note": "есть"}})))
    expect("supported=true с evidence -> ок",
           check({**base, "per_agent_identity": {"supported": True, "note": "mTLS per agent", "evidence": ["spiffe-id"]}}) == [])
    expect("нет per_agent_identity -> ошибка", any("per_agent_identity" in x for x in check({k: v for k, v in base.items() if k != "per_agent_identity"})))

    if DEFAULT.exists():
        errs = check(yaml.safe_load(DEFAULT.read_text(encoding="utf-8")))
        expect(f"реальный {DEFAULT.name} валиден", errs == [])
        for x in errs:
            print("   -", x)

    assert ok, "перенесённый селфтест validate_key_lifecycle: см. строки FAIL в выводе"
