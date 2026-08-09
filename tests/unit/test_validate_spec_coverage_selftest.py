"""Селфтест validate_spec_coverage, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_spec_coverage import (  # noqa: F401 — имена, которые использует тело
    PKG,
    check,
    json,
    sys,
)


@pytest.mark.slow
def test_validate_spec_coverage_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    good = {"kind": "SpecCoverage", "level": 1, "escalated_from": None,
            "sections": [{"id": "goal", "status": "complete", "note": None},
                         {"id": "scope", "status": "not_applicable", "note": "нет"}],
            "blocking_missing": [], "form_errors": [], "ready_to_implement": True}
    expect("валидный coverage -> без ошибок", check(good) == [])
    expect("не тот kind -> ошибка", any("SpecCoverage" in e for e in check({"kind": "x"})))
    bad_dec = json.loads(json.dumps(good))
    bad_dec["sections"].append({"id": "x", "status": "declined"})
    expect("declined без note -> ошибка", any("declined" in e for e in check(bad_dec)))
    bad_bm = json.loads(json.dumps(good))
    bad_bm["sections"].append({"id": "y", "status": "missing"})
    expect("missing не отражён в blocking_missing -> ошибка", any("blocking_missing" in e for e in check(bad_bm)))
    bad_ready = {"kind": "SpecCoverage", "level": 0,
                 "sections": [{"id": "goal", "status": "missing"}],
                 "blocking_missing": ["goal"], "ready_to_implement": True}
    expect("ready_to_implement=True при missing -> ошибка", any("ready_to_implement" in e for e in check(bad_ready)))
    bad_esc = json.loads(json.dumps(good)); bad_esc["escalated_from"] = 2
    expect("escalated_from >= level -> ошибка", any("escalated_from" in e for e in check(bad_esc)))

    # реальный spec_levels даёт валидный coverage
    sys.path.insert(0, str(PKG / "tools"))
    import spec_levels
    cov = spec_levels.assess({"task_type": "ENGINEERING"},
                             {s: {"status": "complete"} for s in spec_levels.required_sections(1)})
    expect("реальный SpecCoverage (полный ENGINEERING) валиден", check(cov) == [])
    cov2 = spec_levels.assess({"task_type": "QUICK"})  # всё missing
    expect("реальный SpecCoverage (пустой QUICK) валиден по форме", check(cov2) == [])

    assert ok, "перенесённый селфтест validate_spec_coverage: см. строки FAIL в выводе"
