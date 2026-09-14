"""#865: порог траты на разбор объясняется владельцу смыслом, а не сырыми токенами/«потолком».

Раньше `from_process_spend` печатала владельцу-непрограммисту «ушло N тысяч токенов … твой
потолок — M тысяч». Слова «токен» и «потолок» ничего не говорят человеку, который не читает код
кита, а точные числа ему тут не нужны — нужно понять ПОСЛЕДСТВИЕ (разбор пошёл по кругу, пора
либо продолжить объявленный шаг, либо взять описание как готовое) и получить рекомендацию.

Числа при этом никуда не пропадают — они остаются в technical (доступны по запросу/на debug).
"""
from __future__ import annotations

from ai_ops_kit.ui import presenter as PR
from ai_ops_kit.ui import presenter_report_formatters as PRF

FORBIDDEN = ("токен", "потолок")


def _spend_check(intent="plan", state="over_ceiling"):
    return {"kind": "ProcessSpendCheck", "intent": intent, "state": state,
            "blocks": state == "over_ceiling", "spent_on_process": 60000, "ceiling": 50000,
            "session_total_tokens": 60000, "process_steps": ["specify", "plan"],
            "decision_ref": "потолок владельца 2026-08-17: 50 000 токенов"}


def test_product_facing_text_has_no_token_or_ceiling_jargon():
    """headline/summary/why_it_matters/decision — то, что реально печатается владельцу на
    уровне product — не должны звучать словами «токен»/«потолок»."""
    msg = PRF.from_process_spend(_spend_check("plan"),
                                 continue_command="./ai-ops plan \"t\" --feature w --spend-ok",
                                 run_command="./ai-ops run \"t\" --feature w --execute")
    human_facing = " ".join(filter(None, [
        msg.get("headline"), msg.get("summary"), msg.get("why_it_matters"),
        (msg.get("decision") or {}).get("question"),
        (msg.get("decision") or {}).get("recommendation"),
        (msg.get("decision") or {}).get("on_approve"),
        (msg.get("decision") or {}).get("on_reject"),
        *(msg.get("next") or []),
    ])).lower()
    for word in FORBIDDEN:
        assert word not in human_facing, f"«{word}» просочилось в текст для владельца: {human_facing!r}"


def test_rendered_product_message_has_no_jargon_but_names_the_consequence():
    """Рендер на уровне product не содержит жаргона, но объясняет, что разбор пошёл по кругу и
    что делать — с рекомендацией, а не голым перечислением вариантов."""
    msg = PRF.from_process_spend(_spend_check("plan"),
                                 continue_command="cont", run_command="run")
    out = PR.render(msg, audience="product").lower()
    for word in FORBIDDEN:
        assert word not in out, f"«{word}» просочилось в рендер product: {out!r}"
    assert "по кругу" in out
    assert "рекомендую" in out


def test_exact_numbers_stay_available_in_technical_details():
    """Точные числа (потрачено/лимит) не теряются — они живут в technical, а не в summary."""
    msg = PRF.from_process_spend(_spend_check("plan"), continue_command="cont", run_command="run")
    tech = msg["technical_details"]
    assert tech["available"] is True
    payload = tech["payload"]
    assert payload["потрачено на описание"] == 60000
    assert payload["потолок"] == 50000
    # А в summary/headline самих цифр уже нет.
    assert "60000" not in (msg.get("summary") or "")
    assert "50000" not in (msg.get("summary") or "")

    out_technical = PR.render(msg, audience="technical")
    assert "60000" in out_technical or "потрачено на описание" in out_technical
