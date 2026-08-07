"""Селфтест validate_loop_trace, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_loop_trace import (  # noqa: F401 — имена, которые использует тело
    DEMO,
    SCHEMA,
    _load,
    analyze,
    check,
    json,
)


@pytest.mark.slow
def test_validate_loop_trace_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    ex = json.loads(SCHEMA.read_text(encoding="utf-8"))["examples"][0]
    expect("пример LoopTrace валиден (converged)", check(ex) == [])
    expect("анализ примера: converged, прогресс 1->0",
           analyze(ex)["verdict"] == "converged" and analyze(ex)["no_progress"] is False)
    if DEMO.is_dir():
        expect("реальный loop-trace-demo целостен",
               all(check(_load(f)) == [] for f in sorted(DEMO.glob("LT-*.yaml"))))

    # no-progress: 1,1,1 (lower_is_better) blocked
    np = {**ex, "id": "LT-009", "stopped_reason": "no_progress", "iterations": [
        {"n": 1, "progress_value": 1, "outcome": "blocked", "signature": "a"},
        {"n": 2, "progress_value": 1, "outcome": "blocked", "signature": "b"},
        {"n": 3, "progress_value": 1, "outcome": "blocked", "signature": "c"}]}
    a = analyze(np)
    expect("no_progress детектится (1,1,1)", a["no_progress"] and a["verdict"] == "no_progress")
    expect("no-progress trace со stopped_reason=no_progress валиден", check(np) == [])
    expect("no-progress, но stopped_reason=success -> ошибка (застрял, не успех)",
           any("застрял" in x for x in check({**np, "stopped_reason": "success",
               "iterations": np["iterations"][:-1] + [{"n": 3, "progress_value": 1, "outcome": "success"}]})))

    # repeated_failure: одна signature 2x подряд
    rf = {**ex, "id": "LT-010", "stopped_reason": "repeated_failure", "iterations": [
        {"n": 1, "progress_value": 2, "outcome": "blocked", "signature": "same"},
        {"n": 2, "progress_value": 2, "outcome": "blocked", "signature": "same"}]}
    expect("repeated_failure детектится (same 2x)", analyze(rf)["repeated_failure"] is True)
    expect("repeated_failure trace валиден", check(rf) == [])

    # progressing (не финальный): 3->2->1 continue
    pr = {**ex, "id": "LT-011", "stopped_reason": "budget_exhausted", "iterations": [
        {"n": 1, "progress_value": 3, "outcome": "blocked", "signature": "x"},
        {"n": 2, "progress_value": 2, "outcome": "blocked", "signature": "y"},
        {"n": 3, "progress_value": 1, "outcome": "blocked", "signature": "z"}]}
    expect("прогрессирующий trace -> verdict progressing", analyze(pr)["verdict"] == "progressing")

    # структурные
    expect("n не по порядку -> ошибка",
           any(".n должен быть" in x for x in check({**ex, "iterations": [
               {"n": 5, "progress_value": 0, "outcome": "success"}]})))
    expect("stopped_reason=success при не-success последней -> ошибка",
           any("success" in x for x in check({**ex, "iterations": [
               {"n": 1, "progress_value": 1, "outcome": "blocked", "signature": "a"}]})))
    expect("битый id -> ошибка", any("id" in x for x in check({**ex, "id": "LT1"})))

    assert ok, "перенесённый селфтест validate_loop_trace: см. строки FAIL в выводе"
