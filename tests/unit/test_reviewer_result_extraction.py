"""Структурное заключение судьи достаётся из ответа, даже когда ревью цитирует фигурную скобку.

ПОВОД — ЗАМЕР (первый живой прогон корпуса gate-евалов, 20.08.2026). Разбор стоял на
`re.search(r"\\{.*\\}", text, re.S)`: жадный захват от первой `{` до последней `}`. Живой
code-reviewer процитировал проверяемый код строкой `issues.append({"type": "undefined_flag"})` —
захват начался с неё, `json.loads` упал, и вердикт судьи вместе с девятью конкретными блокерами
был МОЛЧА отброшен. Гейт получил безымянное «reviewer verdict FAIL @ …» из фолбэка по прозе.

Почему это не мелочь: статус в том прогоне случайно совпал (fail и там, и там), поэтому дефект был
невидим по вердикту — терялось СОДЕРЖАНИЕ. А в обратную сторону класс опаснее: проза, где судья
пишет «Вердикт: pass» в цитате или в условной формулировке, разбирается регэкспом и может дать
статус, которого в структурном заключении нет.

Первый тест здесь падает на коде ДО правки и проходит после — это и есть доказательство починки.
"""
from __future__ import annotations

import pytest
import yaml

from ai_ops_kit.devtools.gate_evals import load_cases
from ai_ops_kit.gates.gate_executor import extract_reviewer_json

_TAIL = ('{"schema_version":1,"kind":"reviewer-result","gate":"code_review","status":"fail",'
         '"checks":[{"id":"fake_selftest","status":"fail"}],'
         '"blockers":["ветка --selftest печатает PASSED, не вызвав ни одной функции"]}')


@pytest.mark.unit
def test_prose_quoting_a_brace_no_longer_swallows_the_verdict():
    """ПАДАЛ ДО ПРАВКИ: жадный `{.*}` начинал захват с цитаты кода и ронял разбор."""
    text = ('# Code Review\n\n'
            'Ветка `issues.append({"type": "undefined_flag"})` недостижима.\n\n'
            f'```json\n{_TAIL}\n```\n')
    obj = extract_reviewer_json(text)
    assert obj is not None, "структурное заключение судьи отброшено из-за скобки в прозе"
    assert obj["status"] == "fail"
    assert obj["blockers"] and "selftest" in obj["blockers"][0]


@pytest.mark.unit
def test_the_recorded_live_answer_yields_the_judges_own_blockers():
    """На ЗАПИСАННОМ живом ответе: гейт получает блокеры судьи, а не «reviewer verdict FAIL»."""
    cases, errors = load_cases()
    assert errors == []
    case = next(c for c in cases if c["id"] == "code-review-catches-a-selftest-that-checks-nothing")
    obj = extract_reviewer_json(case["recorded"][0]["text"])
    assert obj is not None and obj["status"] == "fail"
    assert len(obj["blockers"]) >= 2
    assert any("selftest" in b.lower() for b in obj["blockers"])


@pytest.mark.unit
def test_the_last_valid_block_wins():
    """Промпт роли требует структурный блок В КОНЦЕ; всё раньше — цитата или пример."""
    early = _TAIL.replace('"status":"fail"', '"status":"pass"')
    obj = extract_reviewer_json(f"пример из инструкции:\n{early}\n\nмоё заключение:\n{_TAIL}")
    assert obj["status"] == "fail"


@pytest.mark.unit
@pytest.mark.parametrize("text", [
    "",
    None,
    "Заключение прозой, без единого JSON.",
    'Просто объект: {"a": 1}',
    '{"kind":"something-else","status":"pass"}',
    '{"kind":"reviewer-result","status":"зелёное"}',
    '{"kind":"reviewer-result","status":',
])
def test_nothing_valid_means_no_verdict_not_a_guess(text):
    """Fail-closed: разбор не додумывает вердикт из похожего объекта."""
    assert extract_reviewer_json(text) is None


@pytest.mark.unit
def test_orchestrator_writes_the_reviewer_file_for_such_an_answer(tmp_path):
    """Побочный эффект боевого пути: структурный файл появляется, а не теряется."""
    from ai_ops_kit.providers import orchestrator
    text = f'Ревью: `cfg = {{"a": 1}}` подозрителен.\n\n{_TAIL}'
    assert orchestrator._write_reviewer_json(tmp_path, "review", text) is True
    written = yaml.safe_load((tmp_path / "stage-review.reviewer.json").read_text("utf-8"))
    assert written["status"] == "fail" and written["blockers"]
