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
import inspect
import sys

import pytest


def _run_on_live_kit(module_name: str) -> int:
    """Запустить валидатор на его ЖИВОМ артефакте (без аргументов -> DEFAULT).

    У части валидаторов сигнатура `main(argv)`, у части — `main()` с внутренним argparse по
    `sys.argv`. Поэтому: вызываем по фактической сигнатуре И на время вызова подменяем `sys.argv`
    на `[module_name]` — иначе argparse `main()`-валидатора распарсит аргументы pytest и упадёт.
    SystemExit (если main сам зовёт sys.exit) переводим в код возврата.
    """
    mod = importlib.import_module(module_name)
    takes_argv = len(inspect.signature(mod.main).parameters) >= 1
    saved_argv = sys.argv
    sys.argv = [module_name]
    try:
        return mod.main([]) if takes_argv else mod.main()
    except SystemExit as e:  # на случай, если main сам зовёт sys.exit
        return e.code if isinstance(e.code, int) else (0 if not e.code else 1)
    finally:
        sys.argv = saved_argv

# (модуль валидатора, человекочитаемое имя safety-инварианта)
SAFETY_VALIDATORS = [
    ("validate_model_qualification", "допуск модель×роль согласован с Bench-метриками"),
    ("validate_model_roles", "роли->классы, cheapest-first, судьи только qualified"),
    ("validate_security_domains", "доменный контракт security-ревью консистентен"),
    ("validate_security_posture", "каждый evidence-путь постуры безопасности резолвится"),
    ("validate_sandbox_boundary", "слово «песочница» нигде не обещает изоляции, которой нет"),
]


# Валидаторы ЖИВЫХ реестров кита (#678): у каждого есть статический артефакт в дереве кита
# (product-learning FL-*, regression-corpus RC-*, .research/, presets/*, workflows/tracks), и он
# обязан оставаться консистентным. diff-зависимые (agent_evals) и валидаторы рантайм-эмитируемых
# объектов (run_handoff/context_bundle/spec_coverage — им нужен путь к объекту прогона) сюда НЕ
# входят: их место — проводка в генератор/энфорсер, а не статический contracts-green.
LIVE_REGISTRY_VALIDATORS = [
    ("validate_feature_learning", "реестр product-learning FL-* целостен"),
    ("validate_learning_loop", "петля research->learning->architecture (ADR) цела"),
    ("validate_regression_corpus", "regression-corpus RC-* целостен"),
    ("validate_research_artifacts", "RR->EV->DP: схемы, ссылочная целостность, freshness"),
    ("validate_presets", "presets консистентны с registry/agents.yaml"),
    ("validate_workflow_gates", "каждый quality-гейт применим к своему workflow"),
    ("validate_stale_gates", "в дереве кита нет протухших *.gate.json"),
]


@pytest.mark.contract
@pytest.mark.parametrize("module_name,invariant", SAFETY_VALIDATORS,
                         ids=[m for m, _ in SAFETY_VALIDATORS])
def test_safety_validator_is_green_on_live_kit(module_name, invariant):
    """Валидатор safety-инварианта обязан быть зелёным на живом артефакте кита."""
    rc = _run_on_live_kit(module_name)
    assert rc == 0, (
        f"{module_name} не зелёный на живом ките — нарушен инвариант «{invariant}». "
        f"Это safety-регресс: артефакт разошёлся со своим контрактом."
    )


@pytest.mark.contract
@pytest.mark.parametrize("module_name,invariant", LIVE_REGISTRY_VALIDATORS,
                         ids=[m for m, _ in LIVE_REGISTRY_VALIDATORS])
def test_live_registry_validator_is_green_on_live_kit(module_name, invariant):
    """Валидатор живого реестра кита обязан быть зелёным на нём — иначе реестр молча дрейфует."""
    rc = _run_on_live_kit(module_name)
    assert rc == 0, (
        f"{module_name} не зелёный на живом ките — нарушен инвариант «{invariant}». "
        f"Реестр разошёлся со своим контрактом, а раньше это никто не ловил."
    )
