"""Объявленный интент доходит до своего обработчика.

ПОВОД — ЗАМЕР (19.08.2026, лента A). Интент `session` был объявлен в `INTENTS`, обработчик для него
написан в `_run_intent`, а имя не внесли в список интентов, которые ИСПОЛНЯЮТСЯ (остальные лишь
показывают превью). Итог на чистой установке: `./ai-ops session` печатал общую заглушку «Вот что я
сделаю. Выполню намерение.» и возвращал **0**. Команда существовала, отвечала успехом и не делала
ничего.

Это самый дорогой вид отказа: он неотличим от работы. И это уже четвёртый список интентов, который
надо было править рукой при добавлении одного имени (три остальных сведены в `EXPECTED_INTENTS`).

Проверяется структурно: множество имён, которые `_run_intent` реально разбирает, обязано совпадать
с `DIRECT_INTENTS`. Разойдутся в любую сторону — красное:
  * обработчик есть, имени в списке нет  -> молчаливый no-op с кодом 0;
  * имя в списке есть, обработчика нет   -> падение в `_run_intent` или тихий возврат превью.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT / "tools"))

import ai_ops_cli  # noqa: E402 — путь ставится выше

SOURCE = (PKG_ROOT / "ai_ops_kit" / "cli" / "ai_ops_cli.py").read_text(encoding="utf-8")


def _handled_intents() -> set[str]:
    """Имена, которые `_run_intent` разбирает: `intent == "x"` и `intent in ("x", "y")`."""
    tree = ast.parse(SOURCE)
    fn = next((n for n in tree.body
               if isinstance(n, ast.FunctionDef) and n.name == "_run_intent"), None)
    assert fn is not None, "функция _run_intent исчезла — проверка потеряла предмет"
    seg = ast.get_source_segment(SOURCE, fn) or ""
    names = set(re.findall(r'intent\s*==\s*"([a-z-]+)"', seg))
    for grp in re.findall(r"intent\s+in\s*\(([^)]*)\)", seg):
        names |= set(re.findall(r'"([a-z-]+)"', grp))
    return names


@pytest.mark.contract
def test_direct_intents_match_the_handler():
    declared = set(ai_ops_cli.DIRECT_INTENTS)
    handled = _handled_intents()
    silent_noop = handled - declared
    dangling = declared - handled
    assert not silent_noop, (
        f"обработчик написан, но интент не исполняется — команда вернёт 0, ничего не сделав: "
        f"{sorted(silent_noop)}. Добавьте имя в DIRECT_INTENTS.")
    assert not dangling, (
        f"интент объявлен исполняемым, а обработчика нет: {sorted(dangling)}")


@pytest.mark.contract
def test_every_direct_intent_is_a_declared_intent():
    """Исполняемый интент обязан существовать в объявленной поверхности."""
    unknown = set(ai_ops_cli.DIRECT_INTENTS) - set(ai_ops_cli.INTENTS)
    assert not unknown, f"DIRECT_INTENTS называет то, чего нет в INTENTS: {sorted(unknown)}"


@pytest.mark.contract
def test_the_guard_catches_the_defect_it_was_written_for():
    """Охрана обязана краснеть на образце: обработчик есть, имени в списке нет."""
    fake = '''
def _run_intent(intent, task, child_root, signals, a):
    if intent == "session":
        return 0
    if intent == "status":
        return 0
'''
    tree = ast.parse(fake)
    fn = tree.body[0]
    seg = ast.get_source_segment(fake, fn)
    names = set(re.findall(r'intent\s*==\s*"([a-z-]+)"', seg))
    assert names == {"session", "status"}, f"разбор обработчика ослеп: {names}"
    assert names - {"status"}, "разница с неполным списком не обнаруживается"
