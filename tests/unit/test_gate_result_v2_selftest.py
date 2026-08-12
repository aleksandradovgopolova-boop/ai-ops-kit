"""Селфтест gate_result_v2, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

from pathlib import Path

import pytest

# корень пакета: в модуле путь считался от его __file__, в тесте это tests/unit
PKG_ROOT = Path(__file__).resolve().parents[2]

from gate_result_v2 import (  # noqa: F401 — имена, которые использует тело
    Path,
    STATUS_V2,
    calibrated_view,
    check,
    json,
    sys,
    to_v1,
)


@pytest.mark.slow
def test_gate_result_v2_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    valid_abstain = {"schema_version": 2, "gate": "visual_regression", "status": "abstain",
                     "blocking": True, "applicability": "applicable", "enforcement": "advisory",
                     "evidence_mode": "deterministic", "owner": "r", "review_mode": "read-only",
                     "blockers": [], "warnings": ["w"]}
    expect("валидный abstain (advisory) проходит", check(valid_abstain) == [])
    expect("abstain(blocking) БЕЗ pending_human-полей -> ошибка (нельзя выдать advisory за разрешение)",
           any("blocking-abstain" in x for x in check({**valid_abstain, "enforcement": "blocking"})))

    # v3.6.7: КОРРЕКТНЫЙ blocking-abstain (pending_human) валиден и запрещает доставку
    blocking_abstain = {"schema_version": 2, "gate": "accessibility_review", "status": "abstain",
                        "blocking": True, "applicability": "applicable", "enforcement": "blocking",
                        "evidence_mode": "hybrid", "owner": "a11y", "review_mode": "read-only",
                        "reviewer_outcome": "abstain", "resolution": "pending_human",
                        "delivery_allowed": False, "human_handoff": True,
                        "blockers": ["reviewer abstain x2 -> человек"], "warnings": []}
    expect("blocking-abstain(pending_human, delivery_allowed=false, handoff=true) валиден",
           check(blocking_abstain) == [])
    expect("blocking-abstain c delivery_allowed=true -> ошибка",
           any("blocking-abstain" in x for x in check({**blocking_abstain, "delivery_allowed": True})))
    v1ba = to_v1(blocking_abstain)
    expect("to_v1(blocking-abstain) -> v1 FAIL с blockers (не мягкий warn)",
           v1ba["status"] == "fail" and v1ba["blockers"])

    na = {"schema_version": 2, "gate": "ux_review", "status": "not_applicable", "blocking": True,
          "applicability": "not_applicable", "enforcement": "advisory", "owner": "r",
          "review_mode": "read-only"}
    expect("валидный not_applicable проходит", check(na) == [])
    expect("not_applicable при applicability=applicable -> ошибка",
           any("not_applicable" in x for x in check({**na, "applicability": "applicable"})))

    fail_v2 = {"schema_version": 2, "gate": "ux_review", "status": "fail", "blocking": True,
               "applicability": "applicable", "enforcement": "blocking", "owner": "r",
               "review_mode": "read-only", "blockers": ["нет состояний экрана"]}
    expect("валидный fail c blockers проходит", check(fail_v2) == [])
    expect("fail без blockers -> ошибка",
           any("blockers" in x for x in check({**fail_v2, "blockers": []})))
    expect("лишний ключ -> ошибка", any("лишний" in x for x in check({**fail_v2, "junk": 1})))

    # адаптер v2 -> v1
    expect("to_v1(not_applicable) -> None (гейт опущен)", to_v1(na) is None)
    v1a = to_v1(valid_abstain)
    expect("to_v1(abstain) -> v1 warn (консервативно, старый потребитель fail-closed)",
           v1a["status"] == "warn" and v1a["schema_version"] == 1)
    v1f = to_v1(fail_v2)
    expect("to_v1(fail) -> v1 fail с blockers", v1f["status"] == "fail" and v1f["blockers"])

    # calibrated_view из решения политики
    sys.path.insert(0, str(PKG_ROOT / "tools"))
    import gate_policy  # noqa: E402
    dec_adv = {d["gate"]: d for d in gate_policy.candidate_policy(
        {"ui_changed": True, "ui_impact": "internal"})}["ux_review"]
    view_adv = calibrated_view("ux_review", True, dec_adv, "warn", "advisory",
                               "internal low-risk -> advisory")
    expect("calibrated_view(advisory) -> abstain + валиден",
           view_adv["status"] == "abstain" and check(view_adv) == [])
    dec_block = {d["gate"]: d for d in gate_policy.candidate_policy(
        {"ui_changed": True, "ui_impact": "user_facing"})}["ux_review"]
    view_block = calibrated_view("ux_review", True, dec_block, "warn", "block",
                                 "fail-closed", blockers=["no evidence"])
    expect("calibrated_view(block) -> fail + валиден + blockers",
           view_block["status"] == "fail" and check(view_block) == [] and view_block["blockers"])

    # drift-guard против схемы
    try:
        sch = json.loads((PKG_ROOT / "schemas"
                          / "gate-result-v2.schema.json").read_text(encoding="utf-8"))
        enum = set(sch["properties"]["status"]["enum"])
        expect("enum status совпадает со схемой (нет дрейфа)", enum == STATUS_V2)
    # Причина ЗАПИСАНА (срез tests ратчета 2026-08-12): это ПРАВИЛЬНЫЙ образец — отказ не
    # гасится, а становится ИМЕНОВАННЫМ FAIL с текстом исключения, то есть попадает в вывод и валит
    # тест. Тип широк намеренно: нечитаемая схема, битый JSON и изменившаяся структура обязаны дать
    # один и тот же честный ответ «схема не читается», а не разные исключения наружу.
    except Exception as ex:  # noqa: BLE001 — отказ становится именованным FAIL, а не тишиной
        expect(f"схема читается ({ex})", False)

    assert ok, "перенесённый селфтест gate_result_v2: см. строки FAIL в выводе"
