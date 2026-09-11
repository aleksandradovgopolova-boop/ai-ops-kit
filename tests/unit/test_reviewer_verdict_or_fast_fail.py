"""Ревьюер code_review: либо родит вердикт, либо падает быстро — не мелет медленные витки.

ПОВОД — issue #591 (оставшаяся половина #577, живой прогон 07.09). Все прежние глушилки run_review
были завязаны на `len(reads) >= max_reads`. Но живой `claude -p` (ревьюер под
`--allowedTools Read Grep Glob`) НИКОГДА не шлёт брокерских `{"op":"read"}` — он читает файлы ВНУТРИ
своего agentic-цикла, поэтому `reads` для него структурно 0. Форс-ход и нуджи не взводились, и петля
молола все `max_reads+2` медленных спавнов, отдавая no-verdict с `reads=0` (в поле «прочитано 0»,
~84 мин). Второй пробел: прозаический вердикт живого судьи («Recommendation: pass») терялся —
`make_reviewer_proposer` принимал вердикт ТОЛЬКО как структурный JSON.

Здесь — детерминированные пробы БЕЗ вызова claude-cli: провайдер — обычная функция, возвращающая
строку, СО СЧЁТЧИКОМ вызовов (чтобы молотилка стала видимой тесту).

K (`max_unproductive`) = 2: после 2 непродуктивных витков (ни брокер-чтения, ни вердикта) — форс-ход
«дай вердикт СЕЙЧАС», и если вердикта всё ещё нет — break. Итог ~K+1 витков вместо max_reads+2.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.engine import tool_broker, tool_loop


@pytest.fixture
def review_deps(tmp_path):
    """Read-only политика + temp root с файлом для чтения (как в test_tool_loop)."""
    root = tmp_path / "review-root"
    root.mkdir()
    (root / "src").mkdir()
    (root / "f.txt").write_text("content", encoding="utf-8")
    return tool_broker.Policy(level="read-only"), root


K = 2  # max_unproductive, выбранное в run_review по умолчанию; фиксируем явно в пробах


@pytest.mark.unit
def test_live_reviewer_without_verdict_fails_fast_not_a_slow_mill(review_deps):
    """(1) БЫСТРЫЙ ВЫХОД. Живой ревьюер (через make_reviewer_proposer) возвращает прозу-без-JSON и
    без явного вердикта КАЖДЫЙ раз -> run_review отдаёт no-verdict за ≤ K+2 вызовов (не max_reads+2),
    reads==[]. Счётчик доказывает, что молотилки max_reads+2 (8) / 12 нет."""
    policy, root = review_deps
    calls = {"n": 0}

    def provider(_prompt):
        calls["n"] += 1
        return "Посмотрел дифф. Тут много всего, надо разбираться подробнее — пока без итога."

    prop = tool_loop.make_reviewer_proposer(provider, "code_review")
    rev = tool_loop.run_review(prop, root, policy, "code_review",
                               budget={"max_model_calls": 50}, max_reads=6, max_unproductive=K)
    assert rev["result"] is None, "мутная проза не должна порождать вердикт"
    assert rev["reads"] == [], "живой судья не эмитит брокер-read -> reads пуст, это норма"
    assert calls["n"] <= K + 2, f"ревьюер смолот {calls['n']} раз — молотилка (max_reads+2=8) вернулась"


@pytest.mark.unit
def test_reviewer_prose_verdict_is_counted_as_a_real_verdict(review_deps):
    """(2) РОДИЛ ВЕРДИКТ ИЗ ПРОЗЫ. Ревьюер заключает прозой явный вердикт («Recommendation: pass»)
    -> run_review отдаёт вердикт (result не None, status выставлен, prose_verdict=True) за малое число
    вызовов. Прозаический вывод живого судьи засчитан как настоящий вердикт через существующий
    _last_prose_verdict."""
    policy, root = review_deps
    calls = {"n": 0}

    def provider(_prompt):
        calls["n"] += 1
        return "Прочитал дифф, логика корректна, регресс-тест на месте.\n\nRecommendation: pass\n"

    prop = tool_loop.make_reviewer_proposer(provider, "code_review")
    rev = tool_loop.run_review(prop, root, policy, "code_review",
                               budget={"max_model_calls": 50}, max_unproductive=K)
    assert rev["result"] is not None and rev["result"]["status"] == "pass"
    assert rev["result"].get("prose_verdict") is True, "вердикт пришёл прозаическим путём"
    assert rev["stopped"] == "verdict"
    assert calls["n"] <= 2, "вердикт вынесен сразу, без лишних витков"


@pytest.mark.unit
def test_prose_needs_work_is_a_blocking_warn_not_a_pass(review_deps):
    """(2b) Прозаический needs_work -> вердикт warn (блокирует), а НЕ тихий pass и не no-verdict."""
    policy, root = review_deps
    prop = tool_loop.make_reviewer_proposer(
        lambda _p: "Есть незакрытая ветка обработки ошибки.\n\nRecommendation: needs_work\n",
        "code_review")
    rev = tool_loop.run_review(prop, root, policy, "code_review",
                               budget={"max_model_calls": 50}, max_unproductive=K)
    assert rev["result"] is not None and rev["result"]["status"] == "warn"
    assert rev["result"].get("blockers"), "warn/needs_work несёт непустой blockers"


@pytest.mark.unit
def test_ambiguous_prose_does_not_fabricate_a_verdict(review_deps):
    """(3) ★ЗАЩИТА ОТ ЛОЖНО-ЗЕЛЁНОГО★. Неоднозначная проза («не могу вынести вердикт по этому диффу»)
    -> вердикт НЕ синтезируется (тем более не pass) -> честный no-verdict. Ядро доверия кита:
    сфабрикованный pass из мутной прозы — худшая регрессия."""
    policy, root = review_deps
    calls = {"n": 0}

    def provider(_prompt):
        calls["n"] += 1
        return "Не могу однозначно вынести вердикт по этому диффу — слишком много неопределённости."

    prop = tool_loop.make_reviewer_proposer(provider, "code_review")
    rev = tool_loop.run_review(prop, root, policy, "code_review",
                               budget={"max_model_calls": 50}, max_unproductive=K)
    assert rev["result"] is None, "мутная проза НЕ должна порождать вердикт (тем более pass)"
    assert calls["n"] <= K + 2


@pytest.mark.unit
def test_the_word_pass_mid_sentence_is_not_a_verdict():
    """(3b) ★ЗАЩИТА★ прямой пробой проповедника: слово «pass» в СЕРЕДИНЕ рассуждения (не итоговой
    строкой-вердиктом) остаётся неразобранным, а НЕ становится pass. Строгость _last_prose_verdict
    (якорь на начало строки) НЕ ослаблена."""
    prop = tool_loop.make_reviewer_proposer(
        lambda _p: "Если бы всё было чисто, это был бы pass. Но я ещё не закончил анализ.", "code_review")
    action = prop("ctx")
    assert action.get("kind") != "reviewer-result", action
    assert action.get("error"), "неоднозначная проза должна остаться неразобранной, не вердиктом"


@pytest.mark.unit
def test_structural_reviewer_result_still_counts(review_deps):
    """(4-i) КОНТРОЛЬ: структурный reviewer-result JSON по-прежнему засчитывается как вердикт
    (не через прозаический путь)."""
    policy, root = review_deps
    prop = tool_loop.make_reviewer_proposer(
        lambda _p: ('{"kind":"reviewer-result","gate":"code_review","status":"pass",'
                    '"checks":[{"id":"x","status":"pass"}]}'), "code_review")
    rev = tool_loop.run_review(prop, root, policy, "code_review",
                               budget={"max_model_calls": 50}, max_unproductive=K)
    assert rev["result"] is not None and rev["result"]["status"] == "pass"
    assert rev["stopped"] == "verdict"
    assert not rev["result"].get("prose_verdict"), "это структурный путь, а не прозаический"


@pytest.mark.unit
def test_broker_reads_still_reach_force_verdict(review_deps):
    """(4-ii) КОНТРОЛЬ: мокнутый ревьюер с брокер-чтениями {"op":"read"} по-прежнему доходит до
    force-verdict по len(reads) — непродуктивный счётчик НЕ мешает продуктивным чтениям. max_reads=3
    при K=2: три реальных чтения СБРАСЫВАЮТ счётчик и доводят до форса, а не обрываются на K=2."""
    policy, root = review_deps
    calls = {"n": 0}

    def reviewer(ctx):
        calls["n"] += 1
        if "ЛИМИТ ЧТЕНИЙ ИСЧЕРПАН" in ctx:
            return {"kind": "reviewer-result", "gate": "code_review", "status": "pass",
                    "checks": [{"id": "ok", "status": "pass"}]}
        return {"op": "read", "path": "f.txt"}

    rev = tool_loop.run_review(reviewer, root, policy, "code_review",
                               budget={"max_model_calls": 50}, max_reads=3, max_unproductive=K)
    assert rev["result"] is not None and rev["result"]["status"] == "pass"
    assert rev["stopped"] == "verdict"
    assert len(rev["reads"]) == 3, "продуктивные чтения дошли до форса по len(reads), не оборвались на K"
