"""Селфтест validate_feature_learning, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_feature_learning import (  # noqa: F401 — имена, которые использует тело
    DEFAULT_DIR,
    Path,
    SCHEMA,
    VERDICT,
    check,
    check_registry,
    json,
    yaml,
)


@pytest.mark.slow
def test_validate_feature_learning_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    ex = json.loads(SCHEMA.read_text(encoding="utf-8"))["examples"][0]
    expect("пример из схемы валиден", check(ex) == [])

    # реальный реестр product-learning целостен
    reg_errs, ids = check_registry(DEFAULT_DIR)
    expect(f"реальный product-learning реестр целостен ({len(ids)} FL)", reg_errs == [])

    expect("verdict без validation.done -> ошибка",
           any("validation.status=done" in x for x in check({**ex,
               "validation": {"method": "m", "status": "running", "result": None},
               "status": "open"})))
    expect("verdict без result -> ошибка",
           any("result" in x for x in check({**ex,
               "validation": {"method": "m", "status": "done", "result": ""}})))
    expect("refuted без learnings -> ошибка",
           any("learnings" in x for x in check({**ex,
               "outcome": {"verdict": "refuted", "expected": "e", "actual": "a"}, "learnings": []})))
    expect("status=validated при незавершённой проверке -> ошибка",
           any("validated" in x for x in check({**ex, "status": "validated",
               "validation": {"method": "m", "status": "planned", "result": None},
               "outcome": {"verdict": "pending"}})))
    expect("status=closed при pending verdict -> ошибка",
           any("closed" in x for x in check({**ex, "status": "closed",
               "outcome": {"verdict": "pending"}})))
    expect("битый id -> ошибка", any("id" in x for x in check({**ex, "id": "FL1"})))
    expect("битый decision_package -> ошибка",
           any("decision_package" in x for x in check({**ex, "decision_package": "108"})))
    expect("decision_package=null валиден", check({**ex, "decision_package": None}) == [])

    # реестр: имя файла != id
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "FL-050.yaml").write_text(yaml.safe_dump({**ex, "id": "FL-777"}), encoding="utf-8")
        e, _ = check_registry(Path(td))
        expect("реестр ловит имя файла != id", any("имя файла" in x for x in e))

    # --- v3.3.3 completion-семантика ---
    conf = {**ex, "outcome": {"verdict": "confirmed", "expected": "e", "actual": "a"}}
    expect("verdict=refuted без decision change/stop/investigate -> ошибка",
           any("refuted требует decision" in x for x in check({**ex,
               "outcome": {"verdict": "refuted", "expected": "e", "actual": "a"},
               "learnings": ["урок"], "decision": "continue"})))
    expect("decision=scale при неподтверждённом -> ошибка",
           any("verdict=confirmed" in x for x in check({**ex,
               "outcome": {"verdict": "inconclusive", "expected": "e", "actual": "a"},
               "decision": "scale"})))
    expect("decision=investigate без research_gap -> ошибка",
           any("research_gap" in x for x in check({**ex,
               "outcome": {"verdict": "pending"},
               "validation": {"method": "m", "status": "planned", "result": None},
               "decision": "investigate", "status": "open"})))
    expect("decision=investigate с research_gap -> валиден",
           check({**ex, "outcome": {"verdict": "pending"},
                  "validation": {"method": "m", "status": "planned", "result": None},
                  "decision": "investigate", "research_gap": "нет измерения", "status": "open"}) == [])
    expect("outcome_achieved=true при неподтверждённом -> ошибка",
           any("outcome_achieved" in x for x in check({**conf,
               "outcome": {"verdict": "inconclusive"}, "completion": {"outcome_achieved": True}})))
    expect("status=closed без learning_complete -> ошибка",
           any("learning_complete" in x for x in check({**conf, "status": "closed",
               "decision": "scale", "completion": {"learning_complete": False}})))
    expect("status=closed без decision -> ошибка",
           any("decision" in x for x in check({**conf, "status": "closed",
               "completion": {"learning_complete": True}})))
    expect("solution_options без ровно одного chosen -> ошибка",
           any("chosen=true" in x for x in check({**conf, "solution_options": [
               {"option": "a", "chosen": True, "reason": "r"},
               {"option": "b", "chosen": True, "reason": "r"}]})))
    expect("битый supersedes -> ошибка",
           any("supersedes" in x for x in check({**ex, "supersedes": "FL1"})))

    # drift-guard enum
    sch = json.loads(SCHEMA.read_text(encoding="utf-8"))
    expect("enum verdict == схема",
           set(sch["properties"]["outcome"]["properties"]["verdict"]["enum"]) == VERDICT)

    assert ok, "перенесённый селфтест validate_feature_learning: см. строки FAIL в выводе"
