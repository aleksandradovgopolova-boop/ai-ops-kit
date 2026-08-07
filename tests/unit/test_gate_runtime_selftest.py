"""Селфтест gate_runtime, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from gate_runtime import (  # noqa: F401 — имена, которые использует тело
    can_deliver,
    decide,
    gate_result_v2,
)


@pytest.mark.slow
def test_gate_runtime_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    uf = {"ui_changed": True, "ui_impact": "user_facing"}
    intn = {"ui_changed": True, "ui_impact": "internal"}

    def _valid(r):
        return gate_result_v2.check(r) == []

    r, m = decide("ux_review", uf, ["pass"])
    expect("pass -> v2 pass, валиден", r["status"] == "pass" and _valid(r) and not m["human_handoff"])
    r, m = decide("ux_review", uf, ["fail"])
    expect("fail -> v2 fail(blocking)+blockers, валиден",
           r["status"] == "fail" and r["enforcement"] == "blocking" and r["blockers"] and _valid(r))
    # warn на internal ux (advisory-тир) -> abstain(advisory)
    r, m = decide("ux_review", intn, ["warn"])
    expect("warn на internal ux -> abstain(advisory), валиден",
           r["status"] == "abstain" and r["enforcement"] == "advisory" and _valid(r)
           and m["terminal"] == "abstain-advisory")
    # warn на user_facing без evidence -> fail(blocking)
    r, m = decide("ux_review", uf, ["warn"], evidence_status="not_run")
    expect("warn на user_facing без evidence -> fail(blocking)", r["status"] == "fail" and _valid(r))
    # warn на user_facing + evidence=pass -> abstain(advisory)
    r, m = decide("visual_regression", uf, ["warn"], evidence_status="pass")
    expect("warn + evidence=pass -> abstain(advisory)", r["status"] == "abstain" and _valid(r))
    # abstain -> retry -> pass
    r, m = decide("ux_review", uf, ["abstain", "pass"], max_retries=1)
    expect("abstain->retry->pass: pass, retries=1", r["status"] == "pass" and m["retries"] == 1)
    # abstain, abstain (retry исчерпан) -> BLOCKING human handoff (не advisory!)
    r, m = decide("ux_review", uf, ["abstain", "abstain"], max_retries=1)
    expect("повторный abstain -> blocking-abstain(pending_human), доставка ЗАПРЕЩЕНА, не advisory",
           r["status"] == "abstain" and r["enforcement"] == "blocking"
           and r["resolution"] == "pending_human" and r["delivery_allowed"] is False
           and r["human_handoff"] is True and m["human_handoff"] is True and _valid(r))
    # to_v1(blocking-abstain) -> fail (старый потребитель не примет advisory за разрешение)
    expect("to_v1(blocking-abstain) -> v1 fail (не warn)",
           gate_result_v2.to_v1(r)["status"] == "fail")
    # no verdict -> blocking handoff
    r, m = decide("ux_review", uf, [])
    expect("нет вердикта -> blocking-abstain(pending_human), доставка запрещена (fail-closed)",
           m["human_handoff"] is True and r["enforcement"] == "blocking"
           and r["delivery_allowed"] is False and _valid(r))
    # can_deliver: пройденные + advisory-abstain разрешают; blocking-abstain держит закрытым
    p, _ = decide("ux_review", uf, ["pass"])
    adv, _ = decide("ux_review", intn, ["warn"])
    ba, _ = decide("accessibility_review", uf, ["abstain", "abstain"])
    okd, bl = can_deliver([p, adv])
    expect("can_deliver: pass + advisory-abstain -> доставка разрешена", okd is True and bl == [])
    okd2, bl2 = can_deliver([p, ba])
    expect("can_deliver: blocking-abstain среди гейтов -> доставка ЗАПРЕЩЕНА",
           okd2 is False and any("pending_human" in b for b in bl2))

    # v3.6.7d: tested_revision привязка
    rr, _ = decide("ux_review", uf, ["pass"], tested_revision="sha1", evidence=["reviewed @ sha1"])
    expect("decide стампит tested_revision + evidence",
           rr["tested_revision"] == "sha1" and rr["evidence"] == ["reviewed @ sha1"])
    okr, _ = can_deliver([rr], expected_revision="sha1")
    expect("can_deliver: tested_revision совпадает с ожидаемым -> разрешено", okr is True)
    okr2, blr = can_deliver([rr], expected_revision="sha2")
    expect("can_deliver: tested_revision != ожидаемый -> ЗАПРЕЩЕНО (вердикт на другом SHA)",
           okr2 is False and any("другом SHA" in b for b in blr))
    okr3, blr3 = can_deliver([p], expected_revision="sha1")
    expect("can_deliver: вердикт без tested_revision при заданном expected -> ЗАПРЕЩЕНО",
           okr3 is False and any("не привязан к SHA" in b for b in blr3))
    # not_applicable по политике (ui_impact=none -> UI-гейт не применяется)
    r, m = decide("ux_review", {"ui_impact": "none"}, ["warn"])
    expect("ui_impact=none -> not_applicable, валиден",
           r["status"] == "not_applicable" and r["applicability"] == "not_applicable" and _valid(r))
    # адаптер v2->v1: abstain -> warn (консервативно для старых потребителей)
    r, _ = decide("ux_review", intn, ["warn"])
    v1 = gate_result_v2.to_v1(r)
    expect("to_v1(abstain) -> warn (старый потребитель fail-closed)", v1 and v1["status"] == "warn")

    assert ok, "перенесённый селфтест gate_runtime: см. строки FAIL в выводе"
