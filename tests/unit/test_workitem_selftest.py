"""Селфтест workitem, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from workitem import (  # noqa: F401 — имена, которые использует тело
    Path,
    derive_status,
    gate_executor,
    start,
    wi_path,
)


@pytest.mark.slow
def test_workitem_selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    gates = gate_executor.load_gates()

    # 1. start создаёт WorkItem с routed workflow и связями
    with tempfile.TemporaryDirectory() as td:
        wi = start(td, "demo-x", "починить опечатку в футере", task_type="bug")
        expect("start: WorkItem создан с workflow", bool(wi.get("workflow")))
        expect("start: связи blueprint+run_state+workitem заданы",
               set(wi["paths"]) == {"blueprint", "run_state", "workitem"})
        expect("start: файл workitem.yaml записан", wi_path(td, "demo-x").exists())

    # 2. QUICK без evidence -> needs_more_evidence (гейты не закрыты, доказательств нет)
    with tempfile.TemporaryDirectory() as td:
        r = derive_status("QUICK", Path(td), {})
        expect("QUICK без evidence -> needs_more_evidence", r["status"] == "needs_more_evidence")

    # 3. QUICK с полным evidence -> done
    good = {
        "intake_completeness": {"status": "pass", "provided": ["classified_type", "size", "risk"]},
        "implementation_verification": {"status": "pass",
            "provided": ["build_passed", "lint_passed", "typecheck_passed", "tests_passed", "tested_revision"]},
    }
    with tempfile.TemporaryDirectory() as td:
        r = derive_status("QUICK", Path(td), good)
        expect("QUICK с полным evidence -> done", r["status"] == "done")

    # 4. реальный провал гейта (evidence подан, fail) -> blocked
    with tempfile.TemporaryDirectory() as td:
        bad = dict(good)
        bad["implementation_verification"] = {"status": "fail", "blockers": ["tests failed"]}
        r = derive_status("QUICK", Path(td), bad)
        expect("реальный fail гейта -> blocked", r["status"] == "blocked")

    # 5. незакрытый human-approval гейт -> needs_human_decision
    hum_case = None
    for wid, w in gate_executor.load_workflows().items():
        gs = w.get("quality_gates", []) or []
        hum = [g for g in gs if gate_executor.classify(gates[g]) == "human-approval"]
        if hum:
            ev = {g: {"status": "pass", "provided": list(gates[g].get("required_evidence", []) or [])}
                  for g in gs if g not in hum}
            hum_case = derive_status(wid, Path("/nonexistent"), ev)
            break
    if hum_case is not None:
        expect("незакрытый human-approval -> needs_human_decision",
               hum_case["status"] == "needs_human_decision")
    else:
        print("SKIP: нет workflow с human-approval гейтом")

    # 6. приоритет: реальный fail важнее human-approval -> blocked
    with tempfile.TemporaryDirectory() as td:
        bad2 = dict(good)
        bad2["implementation_verification"] = {"status": "fail", "blockers": ["build failed"]}
        r = derive_status("QUICK", Path(td), bad2)
        expect("приоритет: реальный fail -> blocked (не evidence/human)", r["status"] == "blocked")

    assert ok, "перенесённый селфтест workitem: см. строки FAIL в выводе"
