"""Regression: поставка кита не должна читаться как «код продукта уже правится».

ИСТОЧНИК. Полевой дефект класса F-030/F-032 (проба шва на дочке, 2026-08-17). Потолок траты на
описание (`specify`/`plan`) применяется только пока код продукта не тронут; «тронут» выводится из
`git status`. Пока список путей кита в `process_spend` состоял лишь из трёх каталогов,
свежеустановленная дочка (`.gitignore`, `.gitattributes`, `.ai/`, `.ai-ops/`, `.claude/` в
`git status`) читалась как «код уже правится» — и потолок не срабатывал НИКОГДА. Ни один тест
этого не видел: все мерили сам репозиторий кита, где своей же поставки в `git status` нет.

СИМПТОМ. На свежей дочке `code_changed` возвращает True сразу после установки, процессная фаза
считается закрытой, и потолок расхода на обсуждение/план не применяется.

ЧТО КРАСНЕЕТ ПРИ РЕГРЕССЕ. `_is_kit_path` должен относить артефакты поставки кита к «путям кита»
(исключаются из детекции правки), а реальный код продукта — нет. Если из `_KIT_FILES`/`_KIT_PREFIXES`
убрать `.gitattributes`, `.ai-ops/` и т.п. — тест краснеет.

Угол НОВЫЙ относительно существующего `test_fresh_install_is_not_a_code_change`: тот ставит кит в
пустую дочку и гоняет живой `git status` (медленно, через установку). Здесь пиннится сам
классификатор путей на конкретных членах списка, которые ДОБАВЛЯЛИСЬ в ответ на поле-дефекты —
быстро и без git-установки.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.engops import process_spend


# Пути, которые появляются в `git status` СВЕЖЕЙ дочки — это поставка кита, а не правка продукта.
# Каждый добавлялся в список в ответ на конкретную пробу шва (см. докстринги _KIT_* в process_spend).
KIT_DELIVERY_PATHS = [
    ".gitignore",                       # ensure_gitignore — поставка, не код (шов 2026-08-17)
    ".gitattributes",                   # ensure_gitattributes — поставка, не код (18.08.2026)
    ".ai-ops.yaml",                     # манифест кита
    "ai-ops",                           # раннер кита
    "AI-OPS-ONBOARDING.md",
    "CLAUDE.md",
    "ROADMAP.md",
    ".ai/runtime/process-spend.yaml",   # артефакт рантайма кита
    ".ai-ops/PRODUCT_PASSPORT.md",      # _seed_product_layer (20.08.2026)
    ".claude/settings.json",
    ".github/workflows/ci.yml",
    "planning/plan.yaml",
    "history/session.md",
    "features/x.md",
]

# Пути реального кода продукта — их правку потолок ОБЯЗАН замечать.
PRODUCT_CODE_PATHS = [
    "src/calc.py",
    "app/main.py",
    "lib/util.js",
    "main.py",
]


@pytest.mark.regression
@pytest.mark.parametrize("path", KIT_DELIVERY_PATHS)
def test_kit_delivery_path_is_not_a_product_code_change(path):
    """Артефакт поставки кита относится к путям кита -> не читается как правка кода."""
    assert process_spend._is_kit_path(path) is True, (
        f"{path}: поставка кита ошибочно принята за код продукта — потолок расхода не сработает"
    )


@pytest.mark.regression
@pytest.mark.parametrize("path", PRODUCT_CODE_PATHS)
def test_real_product_code_is_not_swallowed_by_exclusions(path):
    """Реальный код продукта НЕ относится к путям кита -> его правка видна детектору."""
    assert process_spend._is_kit_path(path) is False, (
        f"{path}: правка кода продукта проглочена исключениями — детекция ослепла"
    )
