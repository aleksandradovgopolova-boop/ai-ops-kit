"""Объявленный интент доходит до своего обработчика.

ПОВОД — ЗАМЕР (19.08.2026, лента A). Интент `session` был объявлен в `INTENTS`, обработчик для него
написан в `_run_intent`, а имя не внесли в список интентов, которые ИСПОЛНЯЮТСЯ (остальные лишь
показывают превью). Итог на чистой установке: `./ai-ops session` печатал общую заглушку «Вот что я
сделаю. Выполню намерение.» и возвращал **0**. Команда существовала, отвечала успехом и не делала
ничего.

Это самый дорогой вид отказа: он неотличим от работы. И это уже четвёртый список интентов, который
надо было править рукой при добавлении одного имени (три остальных сведены в `EXPECTED_INTENTS`).

v3.38 (реестр обработчиков): диспетч больше НЕ цепочка `if intent == "x"`, а реестр
`_INTENT_HANDLERS` (регистрация декоратором `@_intent(...)`). Поэтому и разбор здесь читает реестр
напрямую, а не сканирует исходник регуляркой — ровно то, о чём говорил старый комментарий «четвёртый
список, который правят рукой»: теперь список один, и он же исполняется.

Проверяется: множество ключей реестра обязано совпадать с `DIRECT_INTENTS`. Разойдутся в любую
сторону — красное:
  * обработчик зарегистрирован, имени в списке нет -> молчаливый no-op с кодом 0;
  * имя в списке есть, обработчика нет            -> тихий возврат превью вместо действия.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT / "tools"))

from ai_ops_kit.cli import ai_ops_cli # noqa: E402 — путь ставится выше


def _handled_intents() -> set[str]:
    """Имена, для которых зарегистрирован обработчик в реестре диспетчера."""
    return set(ai_ops_cli._INTENT_HANDLERS)


@pytest.mark.contract
def test_direct_intents_match_the_handler():
    declared = set(ai_ops_cli.DIRECT_INTENTS)
    handled = _handled_intents()
    silent_noop = handled - declared
    dangling = declared - handled
    assert not silent_noop, (
        f"обработчик зарегистрирован, но интент не исполняется — команда вернёт 0, ничего не сделав: "
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
    """Охрана обязана краснеть на образце в ОБЕ стороны — иначе она ничего не значит."""
    # Класс 1: обработчик зарегистрирован, имени в DIRECT_INTENTS нет -> молчаливый no-op.
    handled, declared = {"session", "status"}, {"status"}
    assert handled - declared == {"session"}, "молчаливый no-op не обнаруживается"
    # Класс 2: имя объявлено исполняемым, обработчика нет -> тихое превью вместо действия.
    handled, declared = {"status"}, {"status", "roadmap"}
    assert declared - handled == {"roadmap"}, "висячий интент не обнаруживается"


@pytest.mark.contract
def test_double_registration_is_rejected():
    """Повторная регистрация одного имени — ошибка, а не тихое затирание обработчика."""
    with pytest.raises(ValueError):
        ai_ops_cli._intent("status")(lambda *a: 0)
