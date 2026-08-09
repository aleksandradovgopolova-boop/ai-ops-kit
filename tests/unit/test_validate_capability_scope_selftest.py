"""Селфтест validate_capability_scope, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_capability_scope import (  # noqa: F401 — имена, которые использует тело
    DEMO,
    SCHEMA,
    WG_DEMO,
    _load,
    _load_dir,
    check,
    check_coverage,
    json,
)


@pytest.mark.slow
def test_validate_capability_scope_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    ex = json.loads(SCHEMA.read_text(encoding="utf-8"))["examples"][0]
    expect("пример из схемы валиден", check(ex) == [])
    expect("network без justification -> ошибка (least-privilege)",
           any("network" in x for x in check({**ex,
               "allowed_permissions": ["read-only", "network"]})))
    expect("network c justification -> валиден",
           check({**ex, "allowed_permissions": ["read-only", "network"],
                  "justification": {"network": "внешний вызов платёжного API"}}) == [])
    expect("execution без justification -> ошибка",
           any("execution" in x for x in check({**ex,
               "allowed_permissions": ["execution"]})))
    expect("неизвестный уровень -> ошибка",
           any("неизвестный уровень" in x for x in check({**ex, "allowed_permissions": ["god-mode"]})))
    expect("битый id -> ошибка", any("id" in x for x in check({**ex, "id": "PCS1"})))

    # покрытие
    wg = {"id": "WG-001", "packages": [{"id": "api"}, {"id": "ui"}, {"id": "wiring"}]}
    full = [{"id": "PCS-001", "work_graph": "WG-001", "package": "api"},
            {"id": "PCS-002", "work_graph": "WG-001", "package": "ui"},
            {"id": "PCS-003", "work_graph": "WG-001", "package": "wiring"}]
    expect("полное покрытие пакетов -> ок", check_coverage(wg, full) == [])
    expect("пакет без PCS -> нарушение инварианта",
           any("БЕЗ capability-scope" in x for x in check_coverage(wg, full[:2])))
    expect("PCS на пакет вне WG -> ошибка",
           any("вне WG-001" in x for x in check_coverage(wg,
               full + [{"id": "PCS-009", "work_graph": "WG-001", "package": "ghost"}])))
    expect("дубль PCS на пакет -> ошибка",
           any(">1 PCS" in x for x in check_coverage(wg,
               full + [{"id": "PCS-009", "work_graph": "WG-001", "package": "api"}])))

    # реальный демо: PCS структурно валидны + покрывают WG-001
    real = _load_dir(DEMO)
    expect(f"реальные PCS в examples/capability-demo валидны ({len(real)})",
           all(check(p) == [] for p in real) and len(real) >= 1)
    if WG_DEMO.exists() and real:
        expect("реальные PCS покрывают WG-001 (каждый пакет имеет scope)",
               check_coverage(_load(WG_DEMO), real) == [])

    assert ok, "перенесённый селфтест validate_capability_scope: см. строки FAIL в выводе"
