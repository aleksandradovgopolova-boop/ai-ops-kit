"""Селфтест validate_surface_wiring, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_surface_wiring import (  # noqa: F401 — имена, которые использует тело
    check,
)


@pytest.mark.slow
def test_validate_surface_wiring_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    clean = {"core": ["/api/catalog"],
             "wrappers": {"prod": ["/api/catalog"], "dev": ["/api/catalog"], "serverless": ["/api/catalog"]},
             "client": ["/api/catalog"]}
    expect("согласованная поверхность -> без errors", check(clean)["errors"] == [])

    # ровно дефект /api/catalog: ядро умеет, ни одна обёртка не смонтировала, клиент вызывает
    drift = {"core": ["/api/catalog"], "wrappers": {"prod": [], "dev": []}, "client": ["/api/catalog"]}
    e = check(drift)["errors"]
    expect("drift СРАБАТЫВАЕТ: core route не в обёртках", any("НЕ смонтирован" in x for x in e))
    expect("drift СРАБАТЫВАЕТ: client путь не обслуживается", any("не обслуживается ни одной" in x for x in e))

    # смонтировано в одном контуре, забыто в другом -> частичный drift ловится
    partial = {"core": ["/api/catalog"], "wrappers": {"prod": ["/api/catalog"], "dev": []}, "client": ["/api/catalog"]}
    expect("частичный drift (dev забыл) -> error именно по dev",
           any("'dev'" in x for x in check(partial)["errors"]))

    # префиксный маунт: /api/catalog обслуживает /api/catalog/123
    pref = {"core": [], "wrappers": {"prod": ["/api/catalog"]}, "client": ["/api/catalog/123"]}
    expect("префиксный маунт покрывает вложенный путь", check(pref)["errors"] == [])

    # смонтировано, но никто не вызывает -> advisory (не error)
    unused = {"core": ["/api/catalog"], "wrappers": {"prod": ["/api/catalog", "/api/legacy"]}, "client": ["/api/catalog"]}
    u = check(unused)
    expect("смонтировано-но-невызвано -> advisory, не error",
           u["errors"] == [] and any("/api/legacy" in a for a in u["advisories"]))

    expect("manifest не объект -> честная ошибка", check(None)["errors"] != [])

    assert ok, "перенесённый селфтест validate_surface_wiring: см. строки FAIL в выводе"
