"""Safety-критичные валидаторы гоняются на ЖИВЫХ артефактах кита — их вердикт потребляется.

ЗАЧЕМ. Эти валидаторы были построены, форму каждого держал контракт-тест, но их ВЕРДИКТ не
потреблял никто: ни гейт, ни doctor, ни CI (Тир-2 аудита лишнего, `ep-2026-09-09-cut-unwired-surface`).
«Построено ≠ проведено»: валидатор, который никто не зовёт на реальном файле, не защищает ничего.

Здесь вердикт ПРОВОДИТСЯ в parent-CI: `contracts.sh` гоняет весь `tests/contracts`, поэтому дрейф
любого из этих safety-артефактов (допуск моделей, роли-классы, домены и постура безопасности,
честность слова «песочница») теперь КРАСИТ сборку, а не молчит.

Проверяется живой файл кита (main без аргументов -> DEFAULT-артефакт), а не фикстура: цель — поймать
рассинхрон реального реестра, а не форму примера. main() валидаторов возвращает int (0 = ok) и
sys.exit зовёт только под __main__, поэтому вызов в процессе безопасен.
"""
from __future__ import annotations

import importlib

import pytest

# (модуль валидатора, человекочитаемое имя safety-инварианта)
SAFETY_VALIDATORS = [
    ("validate_model_qualification", "допуск модель×роль согласован с Bench-метриками"),
    ("validate_model_roles", "роли->классы, cheapest-first, судьи только qualified"),
    ("validate_security_domains", "доменный контракт security-ревью консистентен"),
    ("validate_security_posture", "каждый evidence-путь постуры безопасности резолвится"),
    ("validate_sandbox_boundary", "слово «песочница» нигде не обещает изоляции, которой нет"),
]


@pytest.mark.contract
@pytest.mark.parametrize("module_name,invariant", SAFETY_VALIDATORS,
                         ids=[m for m, _ in SAFETY_VALIDATORS])
def test_safety_validator_is_green_on_live_kit(module_name, invariant):
    """Валидатор safety-инварианта обязан быть зелёным на живом артефакте кита."""
    mod = importlib.import_module(module_name)
    rc = mod.main([])
    assert rc == 0, (
        f"{module_name} не зелёный на живом ките — нарушен инвариант «{invariant}». "
        f"Это safety-регресс: артефакт разошёлся со своим контрактом."
    )
