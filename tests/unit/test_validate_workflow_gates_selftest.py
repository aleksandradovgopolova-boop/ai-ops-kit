"""Селфтест validate_workflow_gates, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_workflow_gates import (  # noqa: F401 — имена, которые использует тело
    check,
    load,
)


@pytest.mark.slow
def test_validate_workflow_gates_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    # реальный пакет: ошибок согласованности быть не должно (и WARN тоже: после track-aware
    # и wiring MVP-blocking гейтов остатка быть не должно)
    gates, wfs, mvp, track_gates = load()
    e, wn = check(gates, wfs, mvp, track_gates)
    expect("реальный пакет: workflow↔gate согласованы (0 ошибок)", e == [])
    expect("реальный пакет: 0 WARN (треки учтены, MVP-blocking подключены)", wn == [])

    # синтетика: гейт вне applicability -> ошибка
    g = {"g1": {"applicability": ["ENGINEERING"], "blocking": True}}
    w = {"VISUAL": {"quality_gates": ["g1"]}, "ENGINEERING": {}}
    e2, _ = check(g, w)
    expect("гейт вне applicability -> ошибка", any("g1" in x and "applicability" in x for x in e2))

    # синтетика: applicability=all -> ок
    g3 = {"g2": {"applicability": ["all"], "blocking": False}}
    w3 = {"VISUAL": {"quality_gates": ["g2"]}}
    e3, _ = check(g3, w3)
    expect("applicability=all -> без ошибок", e3 == [])

    # синтетика: несуществующий гейт -> ошибка
    e4, _ = check({}, {"QUICK": {"quality_gates": ["ghost"]}})
    expect("несуществующий гейт -> ошибка", any("ghost" in x for x in e4))

    # синтетика (v2.67): applicability ссылается на неизвестный workflow -> ошибка
    e5, _ = check({"g5": {"applicability": ["GHOSTWF"], "blocking": True}}, {"QUICK": {}})
    expect("applicability -> неизвестный workflow -> ошибка",
           any("GHOSTWF" in x and "неизвестный" in x for x in e5))

    # синтетика (v2.67): MVP-blocking применим, но недостижим (нет ни статически, ни в треке) -> ERROR
    e6, _ = check({"gm": {"applicability": ["QUICK"], "blocking": True}},
                  {"QUICK": {"quality_gates": []}}, mvp={"gm"}, track_gates=set())
    expect("MVP-blocking недостижим -> ERROR (orphan-guard)",
           any("gm" in x and "НЕдостижим" in x for x in e6))

    # синтетика (v2.67): тот же гейт, но покрыт треком -> НЕ ошибка (track-aware)
    e7, w7 = check({"gm": {"applicability": ["QUICK"], "blocking": True}},
                   {"QUICK": {"quality_gates": []}}, mvp={"gm"}, track_gates={"gm"})
    expect("MVP-blocking через трек -> достижим, без ошибки", e7 == [])

    # синтетика (v2.67): прочий blocking-гейт не покрыт -> WARN, не ERROR
    e8, w8 = check({"gw": {"applicability": ["QUICK"], "blocking": True}},
                   {"QUICK": {"quality_gates": []}}, mvp=set(), track_gates=set())
    expect("не-MVP blocking не покрыт -> WARN (не ERROR)", e8 == [] and any("gw" in x for x in w8))

    # синтетика (v2.67): enforced_by (напр. openspec-ci-guard) -> достижим извне, без ERROR/WARN
    e9, w9 = check({"go": {"applicability": ["QUICK"], "blocking": True, "enforced_by": "openspec-ci-guard"}},
                   {"QUICK": {"quality_gates": []}}, mvp={"go"}, track_gates=set())
    expect("enforced_by -> достижим извне, без ERROR и WARN", e9 == [] and w9 == [])

    assert ok, "перенесённый селфтест validate_workflow_gates: см. строки FAIL в выводе"
