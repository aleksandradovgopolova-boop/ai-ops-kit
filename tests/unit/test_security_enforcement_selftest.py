"""Селфтест security_enforcement, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from security_enforcement import (  # noqa: F401 — имена, которые использует тело
    PKG,
    enforce_memory_entry,
    hashlib,
    key_preflight,
    verify_artifact,
)


@pytest.mark.slow
def test_security_enforcement_selftest():
    import yaml
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    # verify_artifact — реальный sha256
    data = b"skill-bytes-v1"
    digest = hashlib.sha256(data).hexdigest()
    okv, r = verify_artifact(data, {"kind": "skill", "install_verify": {"method": "sha256", "value": digest}})
    expect("verify_artifact: совпавший sha256 -> ok", okv is True)
    okv2, _ = verify_artifact(b"tampered", {"kind": "skill", "install_verify": {"method": "sha256", "value": digest}})
    expect("verify_artifact: подменённые байты -> НЕ ok (hash не совпал)", okv2 is False)
    okv3, _ = verify_artifact(data, {"kind": "mcp", "install_verify": {"method": "signature", "value": "x"}})
    expect("verify_artifact: signature офлайн -> block (fail-closed)", okv3 is False)
    okv4, _ = verify_artifact(b"", {"kind": "mcp"})
    expect("verify_artifact: код без install_verify -> block", okv4 is False)
    okv5, _ = verify_artifact(b"", {"kind": "model"})
    expect("verify_artifact: model без install_verify -> допустимо", okv5 is True)

    # enforce_memory_entry
    good = {"id": "m1", "provenance": {"origin": "user", "source_type": "human"},
            "expiry": {"mode": "ttl_days", "value": 30}, "self_ingested": False}
    okm, _ = enforce_memory_entry(good)
    expect("enforce_memory_entry: валидная запись -> ok", okm is True)
    bad = {"id": "m2", "provenance": {"origin": "agent", "source_type": "system"},
           "expiry": {"mode": "ttl_days", "value": 7}, "self_ingested": True}   # self без confirm
    okm2, viol = enforce_memory_entry(bad)
    expect("enforce_memory_entry: self-ingested без human_confirmed -> отклонена", okm2 is False and viol)

    # key_preflight
    klp = {"keys": [{"name": "a", "env_ref": "AKEY", "ttl_days": 90, "rotation_owner": "human"},
                    {"name": "b", "env_ref": "BKEY", "ttl_days": 30, "rotation_owner": "human"}]}
    rep = key_preflight(klp, {"AKEY": "x"}, critical=False)
    expect("key_preflight non-critical: отсутствие BKEY -> warning, ready=True", rep["ready"] and rep["warnings"])
    repc = key_preflight(klp, {"AKEY": "x"}, critical=True)
    expect("key_preflight critical: отсутствие ключа -> BLOCK, ready=False", repc["ready"] is False and repc["blocks"])
    repok = key_preflight(klp, {"AKEY": "x", "BKEY": "y"}, critical=True)
    expect("key_preflight critical: все ключи есть -> ready=True", repok["ready"] is True)
    # v3.7.13 TTL rotation timestamps
    klp_ttl = {"keys": [{"name": "K", "env_ref": "AKEY", "next_rotation_at": "2026-01-01"}]}
    r_over = key_preflight(klp_ttl, {"AKEY": "x"}, critical=True, now="2026-07-28")
    expect("key_preflight TTL: ротация просрочена + critical -> BLOCK",
           r_over["ready"] is False and any("ротация просрочена" in b for b in r_over["blocks"]))
    expect("key_preflight TTL: до срока -> ready", key_preflight(klp_ttl, {"AKEY": "x"}, critical=True, now="2025-12-01")["ready"] is True)
    expect("key_preflight TTL: без now ротация не проверяется", key_preflight(klp_ttl, {"AKEY": "x"}, critical=True)["ready"] is True)

    # интеграция с реальными demo-политиками
    kd = PKG / "examples" / "key-lifecycle-demo" / "KLP-001.yaml"
    if kd.exists():
        klp_real = yaml.safe_load(kd.read_text(encoding="utf-8"))
        expect("реальный KLP-001: preflight non-critical не падает",
               isinstance(key_preflight(klp_real, {}, critical=False)["checked"], list))

    assert ok, "перенесённый селфтест security_enforcement: см. строки FAIL в выводе"
