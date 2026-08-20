"""Корпус gate-евалов исполняется и сходится — контракт, а не благое намерение (C1, v3.37).

ПОЧЕМУ В `contracts`, А НЕ В `unit`. Это утверждение о поверхности кита: «зелёное на судейском
гейте закреплено случаями, и разбор вердикта воспроизводим». Группа `contracts` гоняется и на
Python 3.9, и на каждом PR — а корпус ровно затем и заведён, чтобы регрессия вердикта краснела
там же, где всё остальное.

ЦЕНА НАЗВАНА ЧЕСТНО. Тест требует, чтобы у каждого кейса «с судьёй» был хотя бы один записанный
ответ. Значит, новый такой кейс нельзя влить, не прогнав его живьём хотя бы раз
(`python3 -m ai_ops_kit.devtools.gate_eval_live --record --case <id>`). Это осознанно: кейс,
который никогда не исполнялся, не доказывает ничего, а в сводке выглядел бы как строка охвата.
"""
from __future__ import annotations

from ai_ops_kit.devtools import gate_evals
from ai_ops_kit.gates.gate_executor import load_gates

GATES = load_gates()


def _corpus():
    cases, errors = gate_evals.load_cases()
    return cases, errors


def test_corpus_loads_without_form_errors():
    cases, errors = _corpus()
    assert errors == [], "форма кейсов битая:\n  - " + "\n  - ".join(errors)
    assert cases, "корпус пуст — прогон был бы зелёным, ничего не проверив"


def test_every_case_points_at_a_real_gate_that_is_closed_by_opinion():
    cases, _ = _corpus()
    errs = gate_evals.corpus_registry_errors(cases, GATES)
    assert errs == [], "\n  - ".join([""] + errs)


def test_replay_of_the_whole_corpus_has_no_drift():
    """Главное утверждение: разбор судейского вердикта воспроизводим БЕЗ модели."""
    rep = gate_evals.run_corpus(cases_dir=None)
    drifted = [r for r in rep["results"] if r["outcome"] == "drift"]
    assert not drifted, gate_evals.format_report(rep)
    assert rep["clean"], gate_evals.format_report(rep)


def test_every_judge_case_has_at_least_one_recorded_answer():
    """Кейс без записанного ответа судьи ничего не измеряет — и обязан быть виден, а не влит."""
    cases, _ = _corpus()
    empty = [c["id"] for c in cases
             if c["case_kind"] == "judge_output" and not (c.get("recorded") or [])]
    assert not empty, ("устойчивость не измерена ни разу: " + ", ".join(empty) +
                       " — запишите живой прогон: python3 -m ai_ops_kit.devtools.gate_eval_live "
                       "--record --case <id>")


def test_corpus_covers_both_families_of_verdict():
    """Только fail-closed кейсы мерили бы отсутствие судьи, только judge-кейсы — только его
    ответы. Разница между двумя видами «зелёного» видна лишь когда в корпусе есть оба."""
    cases, _ = _corpus()
    kinds = {c["case_kind"] for c in cases}
    assert kinds == {"no_judge", "judge_output"}, kinds


def test_coverage_is_reported_as_a_number_not_as_a_word():
    """Охват называется дробью от ВСЕХ гейтов, чьё «зелёное» — мнение. Иначе неполный корпус
    выглядел бы полным."""
    rep = gate_evals.run_corpus(cases_dir=None)
    cov = rep["coverage"]
    judged = [g for g, v in GATES.items() if v.get("closed_by") in ("judge", "writer")]
    assert cov["judged_gates_total"] == len(judged)
    # Число выводится из реестра, а не прибито: 19 на 19.08.2026, 18 после перевода
    # `documentation_updated` в машинный (C3). Прибитое число заставило бы каждый перевод гейта
    # чинить этот тест — то есть штрафовало бы ровно за то, ради чего корпус и заведён.
    assert cov["judged_gates_total"] <= 19, (
        "гейтов, закрываемых мнением, стало БОЛЬШЕ замера 19.08.2026 — это ратчет, и он "
        "ходит вниз")
    assert 0 < cov["judged_gates_with_cases"] <= cov["judged_gates_total"]
    assert cov["gates_without_cases"], (
        "если однажды непокрытых не останется — это надо будет ЗАМЕТИТЬ и снять утверждение, "
        "а не оставить проверку, которая с тех пор ничего не значит")
    assert (f"{cov['judged_gates_with_cases']} из {cov['judged_gates_total']}"
            in gate_evals.format_report(rep))


def test_report_says_out_loud_what_replay_does_not_prove():
    """Человек, читающий вывод, обязан увидеть границу замера, а не только слово «ok»."""
    text = gate_evals.format_report(gate_evals.run_corpus(cases_dir=None))
    assert "устойчивость самого судьи меряет только live-прогон" in text
