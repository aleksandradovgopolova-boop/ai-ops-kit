"""Селфтест validate_run_handoff, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_run_handoff import (  # noqa: F401 — имена, которые использует тело
    PKG,
    check,
    json,
    sys,
)


@pytest.mark.slow
def test_validate_run_handoff_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    good = {"kind": "RunHandoff", "workitem_id": "x", "next_action": "продолжить",
            "verification": {"passed": ["a"], "failed": []},
            "completed": [], "decisions": [{"id": "d1", "summary": "s"}],
            "changed_files": [], "open_questions": [], "known_risks": [],
            "resume_from_revision": "a" * 40}
    expect("валидный handoff -> без ошибок", check(good) == [])
    expect("не тот kind -> ошибка", any("RunHandoff" in e for e in check({"kind": "x"})))
    no_next = json.loads(json.dumps(good)); del no_next["next_action"]
    expect("нет next_action -> ошибка", any("next_action" in e for e in check(no_next)))
    bad_ver = json.loads(json.dumps(good)); bad_ver["verification"] = {"passed": []}
    expect("verification без failed -> ошибка", any("verification" in e for e in check(bad_ver)))
    bad_dec = json.loads(json.dumps(good)); bad_dec["decisions"] = [{"summary": "s"}]
    expect("decision без id -> ошибка", any("decisions[0]" in e for e in check(bad_dec)))
    null_rev = json.loads(json.dumps(good)); null_rev["resume_from_revision"] = None
    expect("resume_from_revision=null допустим", check(null_rev) == [])

    # реальный build_handoff даёт валидный артефакт
    sys.path.insert(0, str(PKG / "tools"))
    import run_handoff
    h = run_handoff.build_handoff({"workitem_id": "f", "ready_for_pr": True,
                                   "commit": {"sha": "c" * 40, "branch": "ai-ops/f", "evidence_on_exact_sha": True},
                                   "loop": {"applied_writes": 1, "stopped": "done"},
                                   "gates": {"evaluated": ["requirements"], "unmet": []},
                                   "not_yet": [], "checks": {}})
    expect("реальный RunHandoff из build_handoff валиден", check(h) == [])

    assert ok, "перенесённый селфтест validate_run_handoff: см. строки FAIL в выводе"
