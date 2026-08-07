"""Селфтест validate_reviewer_result, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_reviewer_result import (  # noqa: F401 — имена, которые использует тело
    _gate_ids,
    check,
)


@pytest.mark.slow
def test_validate_reviewer_result_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    gate_ids = _gate_ids()
    valid = {"schema_version": 1, "kind": "reviewer-result", "gate": "code_review",
             "reviewer": "code-reviewer", "reviewed_revision": "abc1234",
             "status": "fail",
             "checks": [{"id": "acceptance_scenario_3", "status": "fail",
                         "evidence": {"file": "src/orders/filter.ts", "lines": "74-91"}}],
             "blockers": ["Empty state for zero matching orders is missing"]}
    expect("валидный fail c blockers", check(valid, gate_ids) == [])

    expect("fail без blockers -> ошибка",
           any("blockers" in e for e in check({**valid, "blockers": []}, gate_ids)))

    # rc11: warn (блокирующий вердикт) тоже обязан нести blockers — contentless warn отвергается
    warn_no_bl = {"schema_version": 1, "kind": "reviewer-result", "gate": "code_review",
                  "status": "warn", "checks": [{"id": "c1", "status": "warn"}]}
    expect("rc11: warn без blockers -> ошибка (блок без причины)",
           any("blockers" in e for e in check(warn_no_bl, gate_ids)))
    expect("rc11: warn C blockers -> валиден",
           check({**warn_no_bl, "blockers": ["ярус 500 не покрыт тестом"]}, gate_ids) == [])

    incoherent = {**valid, "status": "pass"}
    expect("fail-check при status=pass -> ошибка",
           any("несогласованно" in e for e in check(incoherent, gate_ids)))

    expect("неизвестный gate -> ошибка",
           any("отсутствует" in e for e in check({**valid, "gate": "nope"}, gate_ids)))

    okr = {"schema_version": 1, "kind": "reviewer-result", "gate": "code_review",
           "status": "pass", "checks": [{"id": "c1", "status": "pass"}]}
    expect("валидный pass", check(okr, gate_ids) == [])

    assert ok, "перенесённый селфтест validate_reviewer_result: см. строки FAIL в выводе"
