"""Где слово судьи СТАНОВИТСЯ доказательством — граница закреплена, а не подразумевается.

Найдено при постройке корпуса gate-евалов (C1, 20.08.2026). Для гейтов типа `ai-review` разбор
ответа судьи выдаёт `provided := required_evidence` — то есть «pass» ревьюера сам засчитывает все
ключи доказательств этого гейта. Для `code_review` это осознанно и записано в коде: судья И ЕСТЬ
доказательство ревью (`reviewed_revision`, `blockers_closed` — про сам акт ревью).

Но тот же путь проходит `ai_eval`, чьи `required_evidence` называют ВЕЩИ, а не акт:
`eval_dataset`, `offline_results`, `guardrails`, `regression_checked`. Одно слово «pass» от судьи
закрывает все пять — включая существование датасета и результатов офлайн-прогона, которых судья не
видел и проверить не мог.

Здесь это НЕ чинится: правка политики доказательств — решение владельца, а не побочный эффект
замера (граница работы C1: судью и его разбор мерим, а не переписываем). Тест фиксирует поведение
таким, какое оно есть, чтобы:
  * оно не изменилось молча в любую сторону;
  * разница между «судья свидетельствует о своём ревью» и «судья свидетельствует о чужом
    артефакте» была видна в наборе проверок, а не только в голове того, кто это заметил.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.gates.gate_executor import (
    evaluate_gate,
    evidence_from_judge_output,
    load_gates,
)

GATES = load_gates()

_PROSE_PASS = "## Заключение\n\nВсё в порядке.\n\nRecommendation: pass\n"


def _verdict(gate_id, text):
    gate = GATES[gate_id]
    ev = evidence_from_judge_output(gate, text, source="probe")
    return gate, ev, evaluate_gate(gate_id, gate, {gate_id: ev} if ev else {})


@pytest.mark.unit
def test_prose_pass_closes_code_review_and_that_is_the_intended_contract():
    """`code_review`: доказательства гейта — про сам акт ревью, и судья вправе их дать."""
    gate, ev, res = _verdict("code_review", _PROSE_PASS)
    assert sorted(gate["required_evidence"]) == ["blockers_closed", "reviewed_revision"]
    assert sorted(ev["provided"]) == ["blockers_closed", "reviewed_revision"]
    assert res["status"] == "pass"


@pytest.mark.unit
def test_prose_pass_also_closes_ai_eval_whose_evidence_names_artifacts_not_the_review():
    """`ai_eval`: те же две строки прозы закрывают пять ключей, четыре из которых — про артефакты,
    которых судья не видел. Замер, а не обвинение: так это работает сегодня."""
    gate, ev, res = _verdict("ai_eval", _PROSE_PASS)
    assert sorted(gate["required_evidence"]) == [
        "eval_dataset", "guardrails", "offline_results", "regression_checked", "success_criteria"]
    assert sorted(ev["provided"]) == sorted(gate["required_evidence"])
    assert res["status"] == "pass" and res["blocking"] is True
    assert res["warnings"] == [], (
        "сегодня это проходит МОЛЧА — ни одного предупреждения о том, что пять доказательств "
        "получены со слов судьи; если однажды появится, надо будет обновить этот замер")


@pytest.mark.unit
def test_the_same_word_does_not_fabricate_evidence_for_a_machine_gate():
    """Обратная сторона границы: для гейта с валидатором слово ревьюера доказательств НЕ даёт,
    и `evaluate_gate` честно краснеет на бездоказательном pass."""
    gate, ev, res = _verdict("intake_completeness", _PROSE_PASS)
    assert ev["status"] == "pass" and not ev.get("provided")
    assert res["status"] == "fail"
    assert any("бездоказательный pass" in b for b in res["blockers"])


@pytest.mark.unit
def test_a_judge_answer_without_a_verdict_line_closes_nothing():
    """Ни JSON, ни строки вердикта — значит вердикта нет. Пустое мнение не зеленит гейт."""
    gate, ev, res = _verdict("code_review", "## Заключение\n\nПосмотрел, вроде нормально.\n")
    assert ev is None
    assert res["status"] == "fail"
    assert any("нет заключения reviewer" in b for b in res["blockers"])
