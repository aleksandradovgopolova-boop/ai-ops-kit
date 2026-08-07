"""Селфтест validate_supply_chain, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_supply_chain import (  # noqa: F401 — имена, которые использует тело
    DEFAULT,
    check,
    yaml,
)


@pytest.mark.slow
def test_validate_supply_chain_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    good = {"schema_version": 1, "kind": "SupplyChainPinPolicy", "policy_id": "SCP-001",
            "dependencies": [
                {"name": "claude-sonnet", "kind": "model", "source": "anthropic",
                 "pinned": {"type": "revision", "value": "claude-sonnet-5-20260101"}},
                {"name": "figma-mcp", "kind": "mcp", "source": "github.com/x/figma-mcp",
                 "pinned": {"type": "hash", "value": "a1b2c3d4e5f6"},
                 "install_verify": {"method": "sha256", "value": "deadbeefdeadbeef"}}]}
    expect("валидная SCP проходит", check(good) == [])
    expect("плавающий latest -> ошибка",
           any("плавающ" in x for x in check({**good, "dependencies": [
               {"name": "m", "kind": "model", "source": "s", "pinned": {"type": "revision", "value": "latest"}}]})))
    expect("mcp без install_verify -> ошибка",
           any("install_verify" in x for x in check({**good, "dependencies": [
               {"name": "srv", "kind": "mcp", "source": "s", "pinned": {"type": "hash", "value": "abcdef1"}}]})))
    expect("hash не hex -> ошибка",
           any("hex-hash" in x for x in check({**good, "dependencies": [
               {"name": "m", "kind": "model", "source": "s", "pinned": {"type": "hash", "value": "not-a-hash!"}}]})))
    expect("нет pinned -> ошибка",
           any("pinned" in x for x in check({**good, "dependencies": [
               {"name": "m", "kind": "model", "source": "s"}]})))
    expect("дубликат зависимости -> ошибка",
           any("дубликат" in x for x in check({**good, "dependencies": good["dependencies"] + [good["dependencies"][0]]})))

    if DEFAULT.exists():
        errs = check(yaml.safe_load(DEFAULT.read_text(encoding="utf-8")))
        expect(f"реальный {DEFAULT.name} валиден", errs == [])
        if errs:
            for x in errs:
                print("   -", x)

    assert ok, "перенесённый селфтест validate_supply_chain: см. строки FAIL в выводе"
