"""Селфтест validate_context_bundle, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_context_bundle import (  # noqa: F401 — имена, которые использует тело
    PKG,
    Path,
    REQUIRED_INCLUDED,
    check,
    json,
    sys,
)


@pytest.mark.slow
def test_validate_context_bundle_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    good = {
        "schema_version": 1, "kind": "ContextBundle", "workitem_id": "wi-x",
        "included": {k: [] for k in REQUIRED_INCLUDED},
        "excluded": [{"source": "agent:foo", "reason": "не в RunPlan"}],
        "estimated_tokens": 100, "context_budget": 1000, "overflow": False,
        "open_questions": [],
    }
    good["included"]["agents"] = ["a"]
    expect("валидный bundle -> без ошибок", check(good) == [])
    expect("не тот kind -> ошибка", any("ContextBundle" in e for e in check({"kind": "x"})))
    bad_exc = json.loads(json.dumps(good)); bad_exc["excluded"] = [{"source": "agent:foo"}]
    expect("excluded без reason -> ошибка", any("reason" in e for e in check(bad_exc)))
    bad_of = json.loads(json.dumps(good)); bad_of["overflow"] = True; bad_of["open_questions"] = []
    expect("overflow без open_question -> ошибка (не молча)", any("молча" in e for e in check(bad_of)))
    bad_ov = json.loads(json.dumps(good)); bad_ov["excluded"] = [{"source": "agent:a", "reason": "x"}]
    expect("агент included и excluded -> ошибка", any("included и excluded" in e for e in check(bad_ov)))
    no_tok = json.loads(json.dumps(good)); no_tok["estimated_tokens"] = -1
    expect("отрицательные токены -> ошибка", any("estimated_tokens" in e for e in check(no_tok)))

    # реальный компилятор даёт валидный bundle
    sys.path.insert(0, str(PKG / "tools"))
    import tempfile
    import context_compiler
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "package.json").write_text('{"dependencies":{"react":"^18"}}', encoding="utf-8")
        b = context_compiler.compile_bundle(
            {"task_type": "ENGINEERING", "risk": "medium", "affected_areas": ["core"], "task_text": "t"}, Path(td))
        expect("реальный ContextBundle из компилятора валиден", check(b) == [])

    assert ok, "перенесённый селфтест validate_context_bundle: см. строки FAIL в выводе"
