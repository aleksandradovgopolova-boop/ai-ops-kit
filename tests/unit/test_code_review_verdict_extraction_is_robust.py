"""Живой ревьюер code_review отдаёт РАЗБИРАЕМЫЙ вердикт — даже когда ответ «грязный».

ПОВОД — ПОЛЕВОЙ ЗАМЕР (cockpit на ките 4.x, фича free-tile-counter, provider claude-cli, commit
8293fe54). Гейт `code_review` упал с блокером «нет заключения reviewer (code-reviewer)», `evidence:
[]`, `reviews: null`: независимый ревьюер НЕ выдал разбираемого вердикта, и гейт не закрывался НИ НА
КАКОЙ правке — автономный green по построению недостижим. Тот же класс, что поле 2026-08-20
(«ревьюер не вынес вердикт»), но живой на 4.x.

КОРЕНЬ. Живой путь ревьюера (`tool_loop.make_reviewer_proposer` -> `parse_action`) разбирал ответ
жадным `re.search(r"\\{.*\\}", ...)` — от ПЕРВОЙ `{` до ПОСЛЕДНЕЙ `}`. Ровно та хрупкость, которую
для ОФЛАЙН-пути (артефакты стадий) уже сняли в `gate_executor.extract_reviewer_json`, но живой путь
ревьюера остался на жадном разборе. Ответ code-reviewer'а почти всегда содержит цитату кода со
скобкой или кладёт вердикт в fenced ```json — на них жадный захват ломается, `json.loads` падает, и
ВАЛИДНЫЙ вердикт молча теряется.

Здесь — детерминированные пробы БЕЗ вызова claude-cli: провайдер — обычная функция, возвращающая
строку. Первые пробы падали бы на коде ДО правки (жадный parse_action возвращал `{"error":...}`) и
проходят после (терминал разбирается тем же надёжным `extract_reviewer_json`, что и офлайн-путь).
"""
from __future__ import annotations

import pytest

from ai_ops_kit.engine import tool_broker, tool_loop
from ai_ops_kit.gates import gate_executor

# Реалистичный вердикт: цитата кода со скобкой ВЫШЕ, итог — reviewer-result НИЖЕ (как в поле).
_QUOTED_BRACE_ANSWER = (
    "# Code Review\n\n"
    'Строка `tiles.append({"type": "free"})` в счётчике не покрыта тестом.\n\n'
    '{"schema_version":1,"kind":"reviewer-result","gate":"code_review","status":"fail",'
    '"checks":[{"id":"free_tile_counter","status":"fail",'
    '"evidence":[{"file":"src/tiles.py","lines":"10-14"}]}],'
    '"blockers":["free-tile-counter не имеет теста на нулевой остаток"]}'
)

_FENCED_JSON_ANSWER = (
    "Посмотрел дифф, замечаний по существу нет.\n\n"
    "```json\n"
    '{"schema_version":1,"kind":"reviewer-result","gate":"code_review","status":"pass",'
    '"checks":[{"id":"logic","status":"pass","evidence":[{"file":"src/tiles.py","lines":"1-5"}]}]}\n'
    "```\n"
)


@pytest.fixture
def review_deps(tmp_path):
    root = tmp_path / "review-root"
    (root / "src").mkdir(parents=True)
    (root / "src" / "tiles.py").write_text("x = 1\n", encoding="utf-8")
    return tool_broker.Policy(level="read-only"), root


# --- живой путь: терминальный вердикт достаётся из «грязного» ответа -------------------------

@pytest.mark.unit
def test_reviewer_proposer_extracts_verdict_past_a_quoted_brace():
    """ПАДАЛ ДО ПРАВКИ: жадный parse_action начинал захват с цитаты кода и ронял разбор вердикта."""
    prop = tool_loop.make_reviewer_proposer(lambda _p: _QUOTED_BRACE_ANSWER, "code_review")
    action = prop("=== КОНТЕКСТ ===\nизменение")
    assert action.get("kind") == "reviewer-result", action
    assert action.get("status") == "fail"
    assert action.get("blockers"), "блокеры судьи должны доехать, а не потеряться"


@pytest.mark.unit
def test_reviewer_proposer_extracts_a_fenced_json_verdict():
    """Вердикт в fenced ```json — тоже разбираем (частый формат живого ответа)."""
    prop = tool_loop.make_reviewer_proposer(lambda _p: _FENCED_JSON_ANSWER, "code_review")
    action = prop("ctx")
    assert action.get("kind") == "reviewer-result" and action.get("status") == "pass"


@pytest.mark.unit
def test_reviewer_proposer_takes_the_last_reviewer_result_not_a_quoted_example():
    """Несколько кандидатов -> берётся ИТОГОВЫЙ (последний), а не процитированный пример из инструкции."""
    example = ('пример формата: {"kind":"reviewer-result","gate":"code_review","status":"pass",'
               '"checks":[{"id":"x","status":"pass"}]}\n\n'
               'моё заключение:\n'
               '{"kind":"reviewer-result","gate":"code_review","status":"fail",'
               '"checks":[{"id":"x","status":"fail"}],"blockers":["реальная проблема"]}')
    prop = tool_loop.make_reviewer_proposer(lambda _p: example, "code_review")
    action = prop("ctx")
    assert action.get("status") == "fail", "процитированный pass не должен побеждать итоговый fail"


@pytest.mark.unit
def test_reviewer_proposer_still_parses_a_read_action():
    """Не-терминальные действия (read-op) по-прежнему проходят через parse_action."""
    prop = tool_loop.make_reviewer_proposer(lambda _p: '{"op":"read","path":"src/tiles.py"}', "code_review")
    action = prop("ctx")
    assert action.get("op") == "read" and action.get("path") == "src/tiles.py"


@pytest.mark.unit
def test_run_review_closes_the_gate_on_a_dirty_but_valid_answer(review_deps):
    """СКВОЗНАЯ проба живого шва (без claude-cli): «грязный» валидный ответ -> гейт получает вердикт,
    а не no-verdict. Это и есть автономный green, который в поле был недостижим."""
    policy, root = review_deps
    prop = tool_loop.make_reviewer_proposer(lambda _p: _QUOTED_BRACE_ANSWER, "code_review")
    rev = tool_loop.run_review(prop, root, policy, "code_review", budget={"max_model_calls": 5})
    assert rev["result"] is not None, "валидный вердикт не должен теряться -> иначе гейт не закрыть"
    assert rev["result"]["status"] == "fail"
    assert rev["stopped"] == "verdict"


# --- обязывающий промпт ----------------------------------------------------------------------

@pytest.mark.unit
def test_reviewer_prompt_obliges_a_machine_readable_final_verdict():
    """Промпт ОБЯЗЫВАЕТ завершить машиночитаемым reviewer-result и называет «последний блок = вердикт»."""
    cap = {}

    def provider(prompt):
        cap["p"] = prompt
        return '{"kind":"reviewer-result","gate":"code_review","status":"pass","checks":[]}'

    tool_loop.make_reviewer_proposer(provider, "code_review")("ctx")
    p = cap["p"]
    assert "reviewer-result" in p
    assert "ПОСЛЕДНИЙ" in p, "промпт обязан называть, что вердикт — ПОСЛЕДНИЙ блок"
    assert "машиночитаем" in p or "ИТОГ обязателен" in p


# --- фолбэк по прозе: needs_work и «последний вердикт» ---------------------------------------

_CODE_REVIEW_GATE = gate_executor.load_gates()["code_review"]


@pytest.mark.unit
def test_prose_needs_work_is_a_warn_not_a_pass_and_not_none():
    """`Recommendation: needs_work` — это warn (не тихий pass и не «вердикта нет»)."""
    ev = gate_executor.evidence_from_markdown(
        _CODE_REVIEW_GATE, "## Итог\nЕсть замечания.\n\nRecommendation: needs_work\n", "probe")
    assert ev is not None and ev["status"] == "warn"
    assert not ev.get("provided"), "needs_work не фабрикует доказательства гейта"


@pytest.mark.unit
def test_prose_verdict_is_decided_by_the_last_line_not_the_first():
    """Цитата «Вердикт: pass» выше, СВОЙ итог «Recommendation: fail» ниже -> fail (берём последний)."""
    text = ("Пример из инструкции: `Вердикт: pass`.\n\n"
            "После чтения диффа:\n\nRecommendation: fail\n")
    ev = gate_executor.evidence_from_markdown(_CODE_REVIEW_GATE, text, "probe")
    assert ev["status"] == "fail"


@pytest.mark.unit
def test_prose_pass_after_a_quoted_fail_is_a_pass():
    """Обратная сторона: процитированный «fail» выше не должен топить итоговый pass ниже."""
    text = ("Опасный паттерн выглядел бы как `status: fail`.\n\n"
            "Но в этом диффе его нет.\n\nRecommendation: pass\n")
    ev = gate_executor.evidence_from_markdown(_CODE_REVIEW_GATE, text, "probe")
    assert ev["status"] == "pass"


@pytest.mark.unit
def test_prose_without_a_verdict_line_still_closes_nothing():
    """Защита не ослаблена: нет ни JSON, ни строки вердикта -> None (рубер-штамп не проходит)."""
    assert gate_executor.evidence_from_markdown(
        _CODE_REVIEW_GATE, "## Заключение\n\nПосмотрел, вроде нормально.\n", "probe") is None


# --- пустой ответ отличается от непарсибельного ----------------------------------------------

@pytest.mark.unit
def test_empty_provider_answer_is_a_named_refusal_not_a_guess():
    """Пустой ответ провайдера -> причина «вернула пустой ответ», НЕ pass и НЕ общее «нет заключения»."""
    from ai_ops_kit.providers.response_contract import ProviderRefusal
    refusal = ProviderRefusal("empty_answer", "claude -p вернул пустой result (rc=0)",
                              "claude-cli", "claude-code-local").as_dict()
    ev = gate_executor.evidence_from_no_verdict(
        _CODE_REVIEW_GATE, gate_id="code_review", refusal=refusal)
    assert ev["status"] == "fail"                       # блокирующий гейт: не закрыт
    reason = " ".join(ev.get("blockers", []))
    assert "пустой" in reason, reason
    assert "reviewer verdict" in " ".join(ev.get("evidence", [])), "должен взводить reviewer-blocked"


@pytest.mark.unit
def test_nonparseable_nonempty_answer_names_a_different_reason():
    """Непустой, но непарсибельный ответ -> ДРУГАЯ причина (не «пусто»), и тоже не pass."""
    ev = gate_executor.evidence_from_no_verdict(
        _CODE_REVIEW_GATE, gate_id="code_review", stopped="no-verdict", reads=[])
    assert ev["status"] == "fail"
    reason = " ".join(ev.get("blockers", []))
    assert "не вернул разбираемого reviewer-result" in reason, reason
    assert "пустой" not in reason, "непарсибельное не должно выдаваться за пустой ответ"
