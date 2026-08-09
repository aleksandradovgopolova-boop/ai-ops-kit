"""Селфтест parallel_executor, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from parallel_executor import (  # noqa: F401 — имена, которые использует тело
    execute_parallel,
)


@pytest.mark.slow
def test_parallel_executor_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    # WG: api ‖ ui (общий контракт), wiring зависимый
    wg = {"packages": [
        {"id": "api", "write_scope": ["api/**"], "shared_contracts": ["OrderContract"]},
        {"id": "ui", "write_scope": ["ui/**"], "shared_contracts": ["OrderContract"]},
        {"id": "wiring", "write_scope": ["wiring/**"], "depends_on": ["api", "ui"]}]}
    SHAS = {"api": "aaa1110", "ui": "bbb2220", "wiring": "ccc3330"}

    def good_runner(pkg):
        s = SHAS[pkg["id"]]
        return {"status": "pass", "sha": s, "gate_report": {"all_pass": True, "tested_revision": s}}

    def good_integration(results):
        return ("1234567", {"all_pass": True, "tested_revision": "1234567"}, 0, False)

    CS = {"OrderContract": "c0ffee0"}

    # happy path: все пакеты pass -> fan-in -> aggregate green на integration-SHA -> ОДИН PR
    r = execute_parallel(wg, good_runner, good_integration, contract_shas=CS)
    expect("happy: proceed + fan-in stage", r["proceed"] and r["stage"] == "fan-in")
    expect("happy: все 3 пакета исполнены (api,ui,wiring)", set(r["package_results"]) == {"api", "ui", "wiring"})
    expect("happy: api‖ui шли параллельно (mode=parallel в trace)",
           any(t["pkg"] in ("api", "ui") and t["mode"] == "parallel" for t in r["trace"]))
    expect("happy: ОДИН DeliveryIntent + PR на integration-SHA",
           r["delivery"]["intents"] == 1 and r["delivery"]["open_pr"] and r["delivery"]["integration_sha"] == "1234567")

    # инвариант: aggregate НЕ на integration-SHA -> PR НЕ открывается
    def wrong_agg_integration(results):
        return ("1234567", {"all_pass": True, "tested_revision": "OTHER99"}, 0, False)
    r2 = execute_parallel(wg, good_runner, wrong_agg_integration, contract_shas=CS)
    expect("aggregate на другом SHA -> PR НЕ открыт (package SHA != integrated result)",
           r2["delivery"]["open_pr"] is False)

    # один пакет fail -> fan-in НЕ начинается, integration НЕ запускается, 0 PR;
    # + dependency-aware stop: wiring (depends_on api,ui) НЕ запускается после провала ui
    ran_ids = set()
    def ui_fails(pkg):
        ran_ids.add(pkg["id"])
        if pkg["id"] == "ui":
            return {"status": "fail", "sha": "bbb2220", "gate_report": {"all_pass": False, "tested_revision": "bbb2220"}}
        return good_runner(pkg)
    called = {"n": 0}
    def counting_integration(results):
        called["n"] += 1; return good_integration(results)
    r3 = execute_parallel(wg, ui_fails, counting_integration, contract_shas=CS)
    expect("один пакет fail -> pre-fan-in block, integration НЕ вызван, 0 PR",
           r3["stage"] == "pre-fan-in" and called["n"] == 0 and r3["delivery"]["intents"] == 0)
    expect("dependency-aware stop: wiring НЕ запущен (dep ui провалилась) -> blocked-dependency",
           "wiring" not in ran_ids and r3["package_results"]["wiring"]["status"] == "blocked-dependency")

    # exception/timeout package_runner -> структурный package failure, executor НЕ крэшится
    def boom(pkg):
        if pkg["id"] == "api":
            raise RuntimeError("provider timeout")
        return good_runner(pkg)
    r_boom = execute_parallel(wg, boom, good_integration, contract_shas=CS)
    expect("exception в runner -> структурный error (не крэш executor), fan-in block",
           r_boom["package_results"]["api"]["status"] == "error"
           and "provider timeout" in r_boom["package_results"]["api"].get("error", "")
           and r_boom["proceed"] is False and r_boom["delivery"]["intents"] == 0)

    # общий контракт не зафиксирован -> block ДО пакетов
    ran = {"n": 0}
    def counting_runner(pkg):
        ran["n"] += 1; return good_runner(pkg)
    r4 = execute_parallel(wg, counting_runner, good_integration, contract_shas={})
    expect("контракт не зафиксирован -> block на contract-first, пакеты НЕ запущены",
           r4["stage"] == "contract-first" and ran["n"] == 0)

    # merge conflict / base moved на fan-in -> block/revalidation, PR не открыт
    def conflict_integration(results):
        return ("1234567", {"all_pass": True, "tested_revision": "1234567"}, 1, False)
    r5 = execute_parallel(wg, good_runner, conflict_integration, contract_shas=CS)
    expect("merge conflict на fan-in -> block, PR не открыт", r5["proceed"] is False and r5["delivery"]["open_pr"] is False)

    # невалидный WG (цикл) -> block на plan
    cyc = {"packages": [{"id": "a", "write_scope": ["a/**"], "depends_on": ["b"]},
                        {"id": "b", "write_scope": ["b/**"], "depends_on": ["a"]}]}
    r6 = execute_parallel(cyc, good_runner, good_integration, contract_shas={})
    expect("цикл в WG -> block на stage=plan", r6["stage"] == "plan" and r6["proceed"] is False)

    # пакет не доказателен (нет SHA) -> pre-fan-in block
    def no_sha_runner(pkg):
        return {"status": "pass", "gate_report": {"all_pass": True}}  # нет sha
    r7 = execute_parallel({"packages": [{"id": "a", "write_scope": ["a/**"]}]},
                          no_sha_runner, good_integration, contract_shas={})
    expect("package без SHA -> pre-fan-in block (не доказателен)", r7["proceed"] is False)

    assert ok, "перенесённый селфтест parallel_executor: см. строки FAIL в выводе"
