"""Селфтест validate_post_release_readout, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_post_release_readout import (  # noqa: F401 — имена, которые использует тело
    DEMO,
    SCHEMA,
    _load,
    check,
    json,
)


@pytest.mark.slow
def test_validate_post_release_readout_selftest():
    import copy
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    ex = json.loads(SCHEMA.read_text(encoding="utf-8"))["examples"][0]
    expect("пример PRR валиден (watch, not_run downstream)", check(ex) == [])
    if DEMO.is_dir():
        expect("реальный readout-demo целостен",
               all(check(_load(f)) == [] for f in sorted(DEMO.glob("PRR-*.yaml"))))

    # healthy_continue при not_run downstream -> ошибка
    hc = copy.deepcopy(ex)
    hc["readout_decision"] = "healthy_continue"
    expect("healthy_continue при downstream=not_run -> ошибка",
           any("downstream_ci=pass" in x for x in check(hc)))
    # валидный healthy_continue
    hc2 = copy.deepcopy(ex)
    hc2["downstream_ci"] = {"status": "pass", "ref": None}
    hc2["product_health"] = {"band": "healthy", "score": 90}
    hc2["readout_decision"] = "healthy_continue"
    expect("healthy_continue при pass+healthy+0 promise_broken -> валиден", check(hc2) == [])
    # sha_verified false
    nv = copy.deepcopy(ex)
    nv["delivery_receipt"]["sha_verified"] = False
    expect("sha_verified=false -> ошибка (readout только верифицированной доставки)",
           any("ВЕРИФИЦИРОВАННОЙ" in x for x in check(nv)))
    # rollback без сигнала
    rb = copy.deepcopy(hc2)
    rb["readout_decision"] = "rollback"
    expect("rollback без негативного сигнала -> ошибка",
           any("негативного сигнала" in x for x in check(rb)))
    # promise_broken>0 + healthy_continue
    pbk = copy.deepcopy(hc2)
    pbk["evolution"] = {"promise_broken": 1, "cost_realized": 0}
    expect("promise_broken>0 + healthy_continue -> ошибка",
           any("promise_broken>0" in x for x in check(pbk)))
    # rollback с сигналом -> валиден
    rb2 = copy.deepcopy(ex)
    rb2["downstream_ci"] = {"status": "fail", "ref": None}
    rb2["readout_decision"] = "rollback"
    expect("rollback при downstream=fail -> валиден", check(rb2) == [])
    expect("битый id -> ошибка", any("id должен" in x for x in check({**ex, "id": "PRR1"})))

    assert ok, "перенесённый селфтест validate_post_release_readout: см. строки FAIL в выводе"
