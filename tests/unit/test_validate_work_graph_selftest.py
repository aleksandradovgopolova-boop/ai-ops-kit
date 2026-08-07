"""Селфтест validate_work_graph, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_work_graph import (  # noqa: F401 — имена, которые использует тело
    DEMO,
    _load,
    _overlap,
    check_bundle,
    check_ip,
    check_wg,
    cross_check,
)


@pytest.mark.slow
def test_validate_work_graph_selftest():
    import copy
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    # реальный демо-бандл целостен
    expect("реальный examples/work-graph-demo валиден и кросс-консистентен", check_bundle(DEMO) == [])

    wg = _load(DEMO / "work-graph.yaml")
    psd = _load(DEMO / "parallel-safety-decision.yaml")
    ip = _load(DEMO / "integration-plan.yaml")

    # топология: wiring раньше своей зависимости -> ошибка
    bad = copy.deepcopy(wg)
    bad["integration_order"] = ["wiring", "api", "ui"]
    expect("нетопологичный integration_order -> ошибка",
           any("топологичен" in x for x in check_wg(bad)))

    # depends_on на несуществующий пакет
    bad = copy.deepcopy(wg)
    bad["packages"][2]["depends_on"] = ["ghost"]
    expect("depends_on -> несуществующий пакет -> ошибка",
           any("несуществующий" in x for x in check_wg(bad)))

    # IP без integration-SHA инварианта
    expect("requires_new_integration_sha=false -> ошибка",
           any("requires_new_integration_sha" in x for x in check_ip({**ip, "requires_new_integration_sha": False})))

    # PSD parallel-safe при пересекающихся write_scope -> непоследовательно
    bad_wg = copy.deepcopy(wg)
    bad_wg["packages"][1]["write_scope"] = ["src/api/shared/**"]   # ui теперь пишет в src/api/*
    e = cross_check(bad_wg, psd, ip)
    expect("PSD parallel-safe при пересекающихся write_scope -> ошибка",
           any("пересекающиеся write_scope" in x for x in e))

    # PSD parallel-safe для зависимых пакетов -> непоследовательно
    bad_psd = copy.deepcopy(psd)
    bad_psd["classifications"] = [{"packages": ["api", "wiring"], "safe": True, "reason": "x"}]
    e = cross_check(wg, bad_psd, ip)
    expect("PSD parallel-safe для depends_on-связанных пакетов -> ошибка",
           any("связаны depends_on" in x for x in e))

    # PSD/IP ссылаются на чужой WG
    e = cross_check(wg, {**psd, "work_graph": "WG-999"}, ip)
    expect("PSD.work_graph != WorkGraph.id -> ошибка", any("PSD.work_graph" in x for x in e))

    # write_scope overlap helper
    expect("_overlap: src/api vs src/ui -> нет", _overlap(["src/api/**"], ["src/ui/**"]) is False)
    expect("_overlap: src/ vs src/api -> да", _overlap(["src/**"], ["src/api/**"]) is True)

    assert ok, "перенесённый селфтест validate_work_graph: см. строки FAIL в выводе"
