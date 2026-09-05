"""Обязательные stories выводятся из Experience Contract КОДОМ, а не переписыванием списка.

ПОВОД — ЗАМЕР (20.08.2026). У механизма было две половины, и они не встречались:

  * сторона ДОКАЗАТЕЛЬСТВА (`ui/storybook_adapter.py`) требует покрытия четырёх состояний
    (`REQUIRED_STATES`: default / loading / empty / error) и не даёт выдать «нет данных» за «чисто»;
  * сторона СОЗДАНИЯ (`ui/experience_contract.py`) выводила состояния ИЗ КОНТРАКТА — только те,
    что владелец перечислил.

Итог: контракт, в котором не описали `error`, порождал набор stories, который гейт **не может
принять никогда**, и узнавалось это на гейте, а не при создании. Две правды об одном вопросе —
тот самый класс, против которого стоит весь кит.

Отдельно: модуль не имел НИ ОДНОГО теста, а его `generate_design_options` читала контракт и не
использовала его — три одинаковых варианта на любой вход (поймано линтером, F841).

ЧТО ПРОВЕРЯЕТСЯ ЗДЕСЬ:
  * обязательные состояния попадают в stories, даже если владелец их не описал;
  * описанное владельцем НЕ затирается заглушкой — у него есть condition/visual, он знает больше;
  * заглушка ВИДНА (`derived_from`), а недостающее НАЗЫВАЕТСЯ вопросом владельцу, а не растворяется
    в сгенерированном списке (иначе «не описано» неотличимо от «описано пусто»);
  * варианты дизайна действительно про этот контракт;
  * список обязательных состояний ОДИН на обе стороны — второй список сразу же разошёлся бы.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT))

from ai_ops_kit.ui import experience_contract as ec  # noqa: E402
from ai_ops_kit.ui import storybook_adapter as sa  # noqa: E402


def _contract(**over):
    base = {
        "id": "cockpit", "title": "Экран активной работы",
        "user_goal": "понять, что идёт прямо сейчас", "context": "ежедневно, с телефона",
        "roles": [{"name": "owner", "permissions": [], "views": []}],
        "flow": [{"step": 1, "action": "открыть", "screen": "main", "state": "default"}],
        "screens": [{"id": "main", "name": "Главный", "components": ["Card"]}],
        "states": [{"name": "default", "condition": "работа идёт", "visual": "карточка"}],
        "microcopy": {"title": "Что идёт"}, "responsive": [{"name": "mobile", "min_width": 0}],
        "accessibility": ["AA"], "components": ["Card"], "tokens": {"color": {}},
        "analytics": [{"event": "opened", "trigger": "mount"}],
        "open_questions": [], "tradeoffs": [],
    }
    base.update(over)
    return base


@pytest.mark.unit
def test_required_states_are_one_list_for_both_halves():
    """Второй список обязательных состояний сразу же разошёлся бы с первым."""
    assert ec.REQUIRED_STATES is sa.REQUIRED_STATES, (
        "сторона создания и сторона доказательства держат РАЗНЫЕ списки обязательных состояний — "
        "две правды об одном вопросе")


@pytest.mark.unit
def test_every_required_state_gets_a_story_even_if_the_owner_forgot_it():
    """Главное свойство работы: вывод КОДОМ, а не переписывание того, что вспомнил автор."""
    stories = ec.generate_stories(_contract())          # описан только `default`
    states = {s["state"] for s in stories}
    missing = set(ec.REQUIRED_STATES) - states
    assert not missing, (
        f"состояния {sorted(missing)} не получили story — гейт доказательства такой набор "
        f"не примет НИКОГДА, и владелец узнает об этом только на гейте")


@pytest.mark.unit
def test_what_the_owner_described_wins_over_the_stub():
    """У описанного состояния есть condition/visual — владелец знает про свой продукт больше."""
    c = _contract(states=[{"name": "error", "condition": "сеть недоступна", "visual": "баннер"}])
    story = next(s for s in ec.generate_stories(c) if s["state"] == "error")
    assert story["parameters"]["state"].get("condition") == "сеть недоступна", story
    assert "derived_from" not in story["parameters"]["state"], "описанное затёрто заглушкой"


@pytest.mark.unit
def test_a_stub_state_is_visible_as_a_stub():
    """Заглушка обязана отличаться от решения: иначе «не описано» неотличимо от «описано пусто»."""
    story = next(s for s in ec.generate_stories(_contract()) if s["state"] == "error")
    assert story["parameters"]["state"].get("derived_from") == "REQUIRED_STATES", story


@pytest.mark.unit
def test_the_undeclared_states_are_named_as_a_question_to_the_owner():
    c = _contract()
    gaps = ec.undeclared_required_states(c)
    assert set(gaps) == {"loading", "empty", "error"}, gaps
    full = _contract(states=[{"name": s} for s in ec.REQUIRED_STATES])
    assert ec.undeclared_required_states(full) == [], "описанное всё считается неописанным"


@pytest.mark.unit
def test_design_options_are_about_this_contract():
    """`generate_design_options` читала контракт и не использовала его (F841) — три одинаковых
    варианта на любой вход. Вариант обязан быть про ЭТУ задачу пользователя."""
    opts = ec.generate_design_options(_contract())
    assert len(opts) >= 2, "вариантов меньше двух — это не выбор, а один «правильный» макет"
    blob = json.dumps(opts, ensure_ascii=False)
    assert "понять, что идёт прямо сейчас" in blob, "цель пользователя не попала ни в один вариант"
    assert all(o.get("tradeoffs", {}).get("cons") for o in opts), (
        "вариант без названной цены — это не trade-off, а реклама")


@pytest.mark.unit
def test_a_contract_without_a_goal_says_so_instead_of_inventing_one():
    """Кит не заполняет за владельца: отсутствие цели НАЗЫВАЕТСЯ, а не подменяется текстом."""
    opts = ec.generate_design_options(_contract(user_goal=""))
    blob = json.dumps(opts, ensure_ascii=False)
    assert "не названа" in blob, blob[:300]


@pytest.mark.unit
def test_every_offered_option_carries_a_named_tradeoff():
    """#416: варианты ПРЕДЛАГАЮТСЯ, и каждый несёт названный компромисс (исход
    `experience_options_offered_with_tradeoffs`). Инвариант — проверка, не проза."""
    options = ec.offer_design_options(_contract())
    assert len(options) >= 2, "меньше двух вариантов — это не выбор"
    for opt in options:
        assert ec.option_tradeoff(opt), f"вариант без названной цены: {opt.get('name')}"
    assert ec.check_design_options(options) == []


@pytest.mark.unit
def test_an_option_without_a_tradeoff_is_an_error_fail_closed(monkeypatch):
    """#416 (б): вариант без осознанного компромисса — ошибка, набор не предлагается (fail-closed)."""
    bad = [{"id": "x", "name": "Без цены", "description": "макет", "tradeoffs": {"pros": ["красиво"]}}]
    assert ec.option_tradeoff(bad[0]) is None, "пустой cons — это не компромисс"
    errors = ec.check_design_options(bad)
    assert any("осознанного компромисса" in e for e in errors), errors
    # offer_design_options — единственные ворота в контур: если генератор вернул вариант без
    # цены, ворота ОБЯЗАНЫ закрыться (raise), а не отдать псевдовыбор наружу.
    monkeypatch.setattr(ec, "generate_design_options", lambda _c: bad)
    with pytest.raises(ValueError, match="осознанного компромисса"):
        ec.offer_design_options(_contract())


@pytest.mark.unit
def test_empty_option_set_is_rejected():
    """Пустой набор — тоже «предлагать нечего»: инвариант краснеет, а не пропускает молча."""
    assert ec.check_design_options([]), "пустой набор вариантов должен быть ошибкой"


@pytest.mark.unit
def test_the_schema_matches_the_fields_the_code_requires():
    """Схема и код требуют ОДНО. Разойдутся — контракт будет валиден для одного и нет для другого."""
    schema = json.loads((PKG_ROOT / "schemas" / "experience-contract.schema.json")
                        .read_text(encoding="utf-8"))
    assert set(schema["required"]) == set(ec.CONTRACT_SCHEMA), (
        f"схема и CONTRACT_SCHEMA разошлись: "
        f"{set(schema['required']) ^ set(ec.CONTRACT_SCHEMA)}")


@pytest.mark.unit
def test_a_valid_contract_passes_and_a_broken_one_is_named():
    assert ec.validate_contract(_contract()) == []
    broken = _contract()
    del broken["screens"]
    errs = ec.validate_contract(broken)
    assert any("screens" in e for e in errs), errs
