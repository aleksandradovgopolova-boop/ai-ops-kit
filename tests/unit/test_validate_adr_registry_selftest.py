"""Селфтест validate_adr_registry, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_adr_registry import (  # noqa: F401 — имена, которые использует тело
    DEFAULT_DIR,
    Path,
    check_registry,
    yaml,
)


@pytest.mark.slow
def test_validate_adr_registry_selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    # реальный реестр кита должен быть целостен
    real_errs, real_adrs = check_registry(DEFAULT_DIR)
    expect(f"реальный decisions/adr целостен ({len(real_adrs)} ADR)", real_errs == [])

    def _valid(aid, **over):
        d = {"schema_version": 1, "kind": "ArchitectureDecision", "id": aid,
             "title": "t", "status": "accepted", "context": "c", "decision": "d",
             "consequences": {"positive": ["p"], "negative": ["n"]}}
        d.update(over)
        return d

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "ADR-001.yaml").write_text(yaml.safe_dump(_valid("ADR-001")), encoding="utf-8")
        e, a = check_registry(d)
        expect("минимальный валидный реестр целостен", e == [] and set(a) == {"ADR-001"})

        # имя файла != id
        (d / "ADR-009.yaml").write_text(yaml.safe_dump(_valid("ADR-777")), encoding="utf-8")
        e, _ = check_registry(d)
        expect("имя файла != id -> ошибка", any("имя файла" in x for x in e))
        (d / "ADR-009.yaml").unlink()

        # односторонний supersede -> несогласовано
        (d / "ADR-002.yaml").write_text(yaml.safe_dump(
            _valid("ADR-002", supersedes="ADR-001")), encoding="utf-8")
        e, _ = check_registry(d)
        expect("A.supersedes=B без B.superseded_by=A -> несогласовано",
               any("несогласовано" in x for x in e))
        # двусторонний -> ок
        (d / "ADR-001.yaml").write_text(yaml.safe_dump(
            _valid("ADR-001", status="superseded", superseded_by="ADR-002")), encoding="utf-8")
        e, _ = check_registry(d)
        expect("двусторонняя supersede-цепочка -> целостна", e == [])

        # dangling related
        (d / "ADR-003.yaml").write_text(yaml.safe_dump(
            _valid("ADR-003", related=["ADR-404"])), encoding="utf-8")
        e, _ = check_registry(d)
        expect("dangling related -> ошибка", any("related" in x for x in e))
        (d / "ADR-003.yaml").unlink()

        # битый ui_impact (fitness к gate_policy)
        (d / "ADR-005.yaml").write_text(yaml.safe_dump(
            _valid("ADR-005", ui_impact="mega")), encoding="utf-8")
        e, _ = check_registry(d)
        expect("ui_impact вне gate_policy.UI_IMPACT -> ошибка (fitness)",
               any("UI_IMPACT" in x for x in e))

    assert ok, "перенесённый селфтест validate_adr_registry: см. строки FAIL в выводе"
