"""Селфтест validate_integration_trace, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_integration_trace import (  # noqa: F401 — имена, которые использует тело
    DEMO,
    SCHEMA,
    _chk_ig,
    _load,
    analyze,
    check,
    json,
)


@pytest.mark.slow
def test_validate_integration_trace_selftest():
    import copy
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    ex = json.loads(SCHEMA.read_text(encoding="utf-8"))["examples"][0]
    expect("пример IntegrationTrace валиден", check(ex) == [])
    a = analyze(ex)
    expect("анализ: speedup≈1.47, coordination=70, beneficial",
           a["speedup"] == round(280 / 190, 3) and a["coordination_overhead"] == 70 and a["beneficial"])
    if DEMO.is_dir():
        expect("реальный integration-trace-demo целостен",
               all(check(_load(f)) == [] for f in sorted(DEMO.glob("IT-*.yaml"))))

    def _mut(**over):
        d = copy.deepcopy(ex)
        d["integration"].update(over)
        return d

    expect("integration_sha == package_sha -> ошибка (не новый)",
           any("НОВЫЙ integration-SHA" in x for x in _chk_ig(ex, integration_sha="aaaaaaa")))
    expect("completed=true без rerun -> ошибка",
           any("aggregate_checks_rerun" in x for x in check(_mut(aggregate_checks_rerun=False))))
    expect("completed=true, new_sha=false -> ошибка",
           any("new_sha" in x for x in check(_mut(new_sha=False))))
    expect("conflicts>0 + completed=true -> ошибка (конфликт=block)",
           any("КОНФЛИКТ=BLOCK" in x for x in check(_mut(fan_in_conflicts=2))))
    # conflicts>0 + completed=false -> ок (заблокировано)
    blocked = copy.deepcopy(ex)
    blocked["integration"] = {"completed": False, "integration_sha": None, "new_sha": False,
                              "aggregate_checks_rerun": False, "fan_in_conflicts": 2}
    expect("conflicts>0 + completed=false -> валиден (fan-in заблокирован)", check(blocked) == [])
    # actual < max package
    bad_t = copy.deepcopy(ex)
    bad_t["wall_seconds_actual"] = 50
    expect("actual < max(package) -> ошибка", any("самого долгого" in x for x in check(bad_t)))
    # baseline != sum
    bad_b = copy.deepcopy(ex)
    bad_b["sequential_baseline_seconds"] = 999
    expect("baseline != сумма -> ошибка", any("сумма времён" in x for x in check(bad_b)))
    expect("битый id -> ошибка", any("id должен" in x for x in check({**ex, "id": "IT1"})))

    assert ok, "перенесённый селфтест validate_integration_trace: см. строки FAIL в выводе"
