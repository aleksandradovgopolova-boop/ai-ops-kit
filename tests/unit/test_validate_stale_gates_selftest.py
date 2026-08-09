"""Селфтест validate_stale_gates, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_stale_gates import (  # noqa: F401 — имена, которые использует тело
    Path,
    json,
    scan,
    sha256,
    tempfile,
)


@pytest.mark.slow
def test_validate_stale_gates_selftest():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        art = root / "change" / "requirements.md"
        art.parent.mkdir(parents=True)
        art.write_text("v1", encoding="utf-8")
        gate = root / "change" / "gates" / "requirements.gate.json"
        gate.parent.mkdir(parents=True)
        gate.write_text(json.dumps({
            "schema_version": 1, "gate": "requirements", "status": "pass", "blocking": True,
            "owner": "requirements-reviewer", "review_mode": "read-only",
            "artifact_hashes": {"change/requirements.md": "sha256:" + sha256(art)},
            "tested_revision": None, "expires_at": None,
        }), encoding="utf-8")

        ok = True
        # 1) свежий gate — не stale
        _, sb, _, _ = scan(root)
        if sb:
            ok = False; print("FAIL fresh gate помечен stale")
        else:
            print("PASS fresh gate не stale")
        # 2) артефакт изменён — stale
        art.write_text("v2 — изменили требования", encoding="utf-8")
        _, sb, _, _ = scan(root)
        if sb and "изменён" in sb[0][1][0]:
            print("PASS изменённый артефакт -> stale")
        else:
            ok = False; print("FAIL изменение артефакта не поймано")
        # 3) просроченный expires_at — stale
        art.write_text("v1", encoding="utf-8")
        g = json.loads(gate.read_text(encoding="utf-8"))
        g["expires_at"] = "2000-01-01T00:00:00Z"
        gate.write_text(json.dumps(g), encoding="utf-8")
        _, sb, _, _ = scan(root)
        if sb and any("expires_at" in r for r in sb[0][1]):
            print("PASS просроченный gate -> stale")
        else:
            ok = False; print("FAIL просрочка не поймана")

    assert ok, "перенесённый селфтест validate_stale_gates: см. строки FAIL в выводе"
