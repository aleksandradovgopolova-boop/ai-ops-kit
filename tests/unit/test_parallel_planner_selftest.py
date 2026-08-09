"""Селфтест parallel_planner, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from parallel_planner import (  # noqa: F401 — имена, которые использует тело
    WG_DEMO,
    can_parallel,
    integration_decision,
    integration_gate,
    plan,
    yaml,
)


@pytest.mark.slow
def test_parallel_planner_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    # реальный demo WG-001 (api||ui + wiring)
    if WG_DEMO.exists():
        wg = yaml.safe_load(WG_DEMO.read_text(encoding="utf-8"))
        p = plan(wg)
        expect("WG-001: api,ui в одной параллельной группе (непересекающиеся)",
               any(set(g) == {"api", "ui"} for g in p["parallel_groups"]))
        expect("WG-001: mode=hybrid (parallel + зависимый wiring)", p["mode"] == "hybrid")
        expect("WG-001: contract_first содержит OrderContract (общий у api,ui)",
               "OrderContract" in p["contract_first"])
        expect("WG-001: integration_order топологичен (wiring последним)", p["integration_order"][-1] == "wiring")
        expect("WG-001: fan_in_required", p["fan_in_required"] is True)

    # сценарий: непересекающиеся независимые -> parallel
    okp, _ = can_parallel({"id": "a", "write_scope": ["src/a/**"]},
                          {"id": "b", "write_scope": ["src/b/**"]})
    expect("непересекающиеся независимые -> parallel", okp is True)
    # пересечение write_scope -> serialize
    okp, r = can_parallel({"id": "a", "write_scope": ["src/**"]},
                          {"id": "b", "write_scope": ["src/b/**"]})
    expect("пересечение write_scope -> сериализация", okp is False and "write_scope" in r)
    # depends_on -> serialize
    okp, r = can_parallel({"id": "a", "write_scope": ["x/**"]},
                          {"id": "b", "write_scope": ["y/**"], "depends_on": ["a"]})
    expect("depends_on -> сериализация", okp is False and "depends_on" in r)

    # общий контракт -> contract_first
    wg2 = {"packages": [{"id": "a", "write_scope": ["a/**"], "shared_contracts": ["C"]},
                        {"id": "b", "write_scope": ["b/**"], "shared_contracts": ["C"]}]}
    expect("общий контракт C -> contract_first", plan(wg2)["contract_first"] == ["C"])

    # integration decision — обязательные сценарии
    expect("один пакет fail -> fan-in НЕ начинается",
           integration_decision({"a": "pass", "b": "fail"})["proceed"] is False)
    d = integration_decision({"a": "pass", "b": "pass"}, conflicts=0, base_moved=False, aggregate_ok=True)
    expect("оба pass, нет конфликта, aggregate green -> integration-SHA + PR",
           d["proceed"] and d["integration_sha_required"] and d["open_pr"])
    expect("merge conflict -> block",
           integration_decision({"a": "pass", "b": "pass"}, conflicts=1)["proceed"] is False)
    dbm = integration_decision({"a": "pass", "b": "pass"}, base_moved=True)
    expect("base moved -> revalidation, PR не открыт",
           dbm.get("revalidation_required") is True and dbm["open_pr"] is False)
    dagg = integration_decision({"a": "pass", "b": "pass"}, aggregate_ok=False)
    expect("aggregate fail -> integration-SHA есть, PR НЕ открывается",
           dagg["integration_sha_required"] is True and dagg["open_pr"] is False)

    # single / sequential режимы
    expect("один пакет -> single", plan({"packages": [{"id": "a", "write_scope": ["a/**"]}]})["mode"] == "single")
    seq = plan({"packages": [{"id": "a", "write_scope": ["a/**"]},
                             {"id": "b", "write_scope": ["b/**"], "depends_on": ["a"]}]})
    expect("цепочка зависимостей -> sequential", seq["mode"] == "sequential")

    # === v3.6.7 hardening (fail-closed перед превращением planner -> executor) ===
    # (баг v3.6.5) глобальный write_scope ** ДОЛЖЕН пересекаться с любым конкретным
    okp, r = can_parallel({"id": "a", "write_scope": ["**"]},
                          {"id": "b", "write_scope": ["src/b/**"]})
    expect("глобальный ** пересекается с src/b/** -> сериализация (fix баг overlap)",
           okp is False and "write_scope" in r)
    okp, r = can_parallel({"id": "a", "write_scope": ["src/a/**"]}, {"id": "b"})
    expect("незадекларированный write_scope -> сериализация (fail-closed)",
           okp is False and "write_scope" in r)
    # WorkGraph validity: цикл -> plan.valid=False
    cyc = plan({"packages": [{"id": "a", "write_scope": ["a/**"], "depends_on": ["b"]},
                             {"id": "b", "write_scope": ["b/**"], "depends_on": ["a"]}]})
    expect("цикл зависимостей -> plan.valid=False + ошибка неполного order",
           cyc["valid"] is False and any("integration_order" in e for e in cyc["errors"]))
    # битая зависимость -> невалиден
    brk = plan({"packages": [{"id": "a", "write_scope": ["a/**"], "depends_on": ["ghost"]}]})
    expect("битый depends_on -> plan.valid=False", brk["valid"] is False)
    # валидный WG-001 -> plan.valid=True
    if WG_DEMO.exists():
        expect("валидный WG-001 -> plan.valid=True", plan(wg)["valid"] is True)

    # integration_decision: ПУСТОЙ набор -> block (раньше проходил как all-pass)
    expect("integration_decision({}) -> block (fail-closed на пустоте)",
           integration_decision({})["proceed"] is False)

    # integration_gate: доказательный happy-path (evidence привязан к SHA пакета и integration-SHA)
    INT = "1234567abc"
    CSHA = "c0ffee0abc"
    good_results = {
        "api": {"status": "pass", "sha": "aaa1110", "gate_report": {"all_pass": True, "tested_revision": "aaa1110"}},
        "ui": {"status": "pass", "sha": "bbb2220", "gate_report": {"all_pass": True, "tested_revision": "bbb2220"}}}
    g = integration_gate(["api", "ui"], good_results, shared_contracts=["OrderContract"],
                         contract_shas={"OrderContract": CSHA},
                         aggregate={"all_pass": True, "tested_revision": INT}, integration_sha=INT)
    expect("integration_gate: доказательный набор + контракт-SHA + aggregate на integration-SHA -> PR",
           g["proceed"] and g["integration_sha_required"] and g["open_pr"])
    # неполный / лишний набор -> block
    expect("integration_gate: пропущен пакет ui -> block",
           integration_gate(["api", "ui"], {"api": good_results["api"]})["proceed"] is False)
    expect("integration_gate: лишний пакет вне WG -> block",
           integration_gate(["api"], good_results)["proceed"] is False)
    # голая строка / нет SHA / gate_report не green -> block
    expect("integration_gate: голая строка 'pass' -> block",
           integration_gate(["api"], {"api": "pass"})["proceed"] is False)
    expect("integration_gate: нет package SHA -> block",
           integration_gate(["api"], {"api": {"status": "pass", "gate_report": {"all_pass": True}}})["proceed"] is False)
    expect("integration_gate: status=pass но gate_report не green -> block",
           integration_gate(["api"], {"api": {"status": "pass", "sha": "aaa1110",
                            "gate_report": {"all_pass": False, "tested_revision": "aaa1110"}}})["proceed"] is False)
    # v3.6.7d: gate_report.tested_revision != package sha -> block
    expect("integration_gate: gate_report.tested_revision != package sha -> block (evidence не на ревизии)",
           integration_gate(["api"], {"api": {"status": "pass", "sha": "aaa1110",
                            "gate_report": {"all_pass": True, "tested_revision": "WRONG99"}}})["proceed"] is False)
    # общий контракт не зафиксирован / не sha-like -> block
    expect("integration_gate: общий контракт без contract SHA -> block",
           integration_gate(["api", "ui"], good_results, shared_contracts=["OrderContract"],
                            contract_shas={})["proceed"] is False)
    expect("integration_gate: contract SHA не похож на реальный commit/blob -> block",
           integration_gate(["api", "ui"], good_results, shared_contracts=["OrderContract"],
                            contract_shas={"OrderContract": "nope"})["proceed"] is False)
    # aggregate голый bool -> proceed, PR НЕ открыт
    gbool = integration_gate(["api", "ui"], good_results, shared_contracts=["OrderContract"],
                             contract_shas={"OrderContract": CSHA}, aggregate=True)
    expect("integration_gate: aggregate голый bool -> proceed, но PR НЕ открыт",
           gbool["proceed"] is True and gbool["open_pr"] is False)
    # v3.6.7d: aggregate.tested_revision != integration_sha -> PR НЕ открыт
    gwrong = integration_gate(["api", "ui"], good_results, shared_contracts=["OrderContract"],
                              contract_shas={"OrderContract": CSHA},
                              aggregate={"all_pass": True, "tested_revision": "OTHER99"}, integration_sha=INT)
    expect("integration_gate: aggregate evidence на другом SHA -> proceed, PR НЕ открыт",
           gwrong["proceed"] is True and gwrong["open_pr"] is False)
    # merge conflict / base moved
    expect("integration_gate: merge conflict -> block",
           integration_gate(["api", "ui"], good_results, shared_contracts=["OrderContract"],
                            contract_shas={"OrderContract": CSHA}, conflicts=1)["proceed"] is False)
    gbm = integration_gate(["api", "ui"], good_results, shared_contracts=["OrderContract"],
                           contract_shas={"OrderContract": CSHA}, base_moved=True)
    expect("integration_gate: base moved -> revalidation, PR не открыт",
           gbm.get("revalidation_required") is True and gbm["open_pr"] is False)
    expect("integration_gate: пустой WorkGraph -> block",
           integration_gate([], {})["proceed"] is False)

    # v3.6.7d: duplicate package id -> plan.valid=False (раньше молча дедуплицировалось)
    dup = plan({"packages": [{"id": "a", "write_scope": ["a/**"]},
                             {"id": "a", "write_scope": ["b/**"]}]})
    expect("дубликат package id -> plan.valid=False", dup["valid"] is False
           and any("дубликат" in e for e in dup["errors"]))
    # v3.6.7d: несловарный пакет НЕ роняет planner, а даёт valid=False
    nd = plan({"packages": ["not-a-dict", {"id": "a", "write_scope": ["a/**"]}]})
    expect("несловарный пакет -> plan.valid=False (без исключения)",
           nd["valid"] is False and any("не являются объектом" in e for e in nd["errors"]))

    assert ok, "перенесённый селфтест parallel_planner: см. строки FAIL в выводе"
