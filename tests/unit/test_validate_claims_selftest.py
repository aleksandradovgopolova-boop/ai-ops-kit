"""Селфтест validate_claims, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_claims import (  # noqa: F401 — имена, которые использует тело
    PKG,
    Path,
    build,
    tempfile,
    yaml,
)


@pytest.mark.slow
def test_validate_claims_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / "types.ts").write_text(
            "export enum MaterialStatus { DRAFT='DRAFT', ORDERED='ORDERED' }\n", encoding="utf-8")
        cf = base / "claims.yaml"
        cf.write_text(yaml.safe_dump({"schema_version": 1, "kind": "claims", "claims": [
            {"id": "file-ok", "type": "file-exists", "source": {"path": "types.ts"}},
            {"id": "symbol-ok", "type": "symbol-exists",
             "source": {"path": "types.ts", "symbol": "MaterialStatus"}},
            {"id": "enum-ok", "type": "enum-values",
             "source": {"path": "types.ts", "values": ["DRAFT", "ORDERED"]}},
            # намеренный слом: код НЕ содержит DELIVERED -> проверку обязаны увидеть падающей
            {"id": "enum-drift", "type": "enum-values",
             "source": {"path": "types.ts", "values": ["DRAFT", "DELIVERED"]}},
            {"id": "file-drift", "type": "file-exists", "source": {"path": "missing.ts"}},
            # count: 2 строки '=' -> ожидаем 2 (ok) и намеренно-неверные 3 (drift)
            {"id": "count-ok", "type": "count",
             "source": {"path": "types.ts", "pattern": "'[A-Z]+'", "expected": 2}},
            {"id": "count-drift", "type": "count",
             "source": {"path": "types.ts", "pattern": "'[A-Z]+'", "expected": 3}},
        ]}), encoding="utf-8")
        res = {r["id"]: r["status"] for r in build(cf)}
        expect("file-exists проходит", res["file-ok"] == "ok")
        expect("symbol-exists проходит", res["symbol-ok"] == "ok")
        expect("enum-values проходит", res["enum-ok"] == "ok")
        expect("enum-drift ВИДЕН падающим (принцип team-os)", res["enum-drift"] == "drift")
        expect("file-drift виден падающим", res["file-drift"] == "drift")
        expect("count совпадает -> ok", res["count-ok"] == "ok")
        expect("count расходится ВИДЕН падающим", res["count-drift"] == "drift")

    # реальные self-claims кита должны выполняться
    kit_claims = PKG / "knowledge" / "claims.yaml"
    if kit_claims.exists():
        bad = [r for r in build(kit_claims) if r["status"] != "ok"]
        expect("self-claims кита выполняются", bad == [])

    assert ok, "перенесённый селфтест validate_claims: см. строки FAIL в выводе"
