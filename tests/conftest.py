"""Pytest configuration for AI Ops Kit Verification Foundation (v3.25.0).

This conftest provides:
1. Fixtures for common test patterns (temp repos, mock providers, etc.)
2. Selftest wrappers — allow running existing --selftest functions via pytest
3. Critical path markers for CI layer separation
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# v4.0: плоский слой `tools/` СНЯТ. Продуктовый код тесты импортируют пакетно
# (`from ai_ops_kit.<pkg> import <mod>`), поэтому `tools/` на пути больше не нужен и его тут нет.
# Валидаторы по-прежнему импортируются как модуль по плоскому имени (`from validate_x import check`)
# из `ai_ops_kit/validation/` — переписывать 70 файлов ради формы импорта в харнессе смысла нет.
# Это не пояс: доказательство того, что валидатор работает БЕЗ путей, даёт
# test_validator_runtime_contract — он запускает каждый процессом из копии репозитория с
# вычищенным PYTHONPATH.
PKG_ROOT = Path(__file__).resolve().parents[1]
VALIDATION_DIR = PKG_ROOT / "ai_ops_kit" / "validation"
TESTS_DIR = PKG_ROOT / "tests"          # общие инструменты проб (`ambient.py`) импортируются по имени
# session-ritual-validators-are-dead: session-модули в engops/ импортируют ai_ops_kit.shared,
# поэтому PKG_ROOT обязан быть на пути. Валидаторам это не нужно (они на плоском имени), но и
# не мешает — пакет уже существует.
for p in (PKG_ROOT, VALIDATION_DIR, TESTS_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


# ── Отключаем фоновую обслуживание git ВО ВСЕХ тестах ──────────────────────────────────────────
# ПОВОД: рецидивирующий флак CI. Тесты, которые git-init'ят репозиторий и потом копируют его целиком
# (`shutil.copytree` каталога с `.git` — test_update_policy_enforcement, test_command_language_wiring),
# ловили гонку: git после commit запускал фоновую обслуживание, та создавала и тут же удаляла
# `.git/objects/maintenance.lock`, а параллельный copytree видел файл в листинге и падал на его
# отсутствии при копировании. Это НЕ дефект продукта — это фоновой git против copytree под xdist.
#
# Через GIT_CONFIG_* переменные (документированный способ git инжектить конфиг) выключаем и
# `maintenance.auto`, и `gc.auto` на КАЖДЫЙ git-подпроцесс, порождаемый тестами: локов больше нет,
# копировать нечего ловить. Ни один тест не зависит от фоновой уборки — поведение продукта не
# меняется, снимается только источник гонки. Значения дозаписываются к тому, что уже есть в среде.
_gc = int(os.environ.get("GIT_CONFIG_COUNT", "0") or "0")
os.environ[f"GIT_CONFIG_KEY_{_gc}"] = "maintenance.auto"
os.environ[f"GIT_CONFIG_VALUE_{_gc}"] = "false"
os.environ[f"GIT_CONFIG_KEY_{_gc + 1}"] = "gc.auto"
os.environ[f"GIT_CONFIG_VALUE_{_gc + 1}"] = "0"
os.environ["GIT_CONFIG_COUNT"] = str(_gc + 2)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def temp_repo(tmp_path):
    """Create a minimal temporary repository structure for testing."""
    repo = tmp_path / "test-repo"
    repo.mkdir()
    (repo / ".ai").mkdir()
    (repo / ".ai" / "runtime").mkdir()
    (repo / "features").mkdir()
    return repo


@pytest.fixture
def mock_provider():
    """A simple mock provider for testing orchestrator/pipeline."""
    def _mock(prompt: str) -> str:
        return f"MOCK_RESPONSE: {prompt[:50]}"
    return _mock


@pytest.fixture
def child_root(tmp_path):
    """Alias for temp_repo — standard naming in AI Ops codebase."""
    repo = tmp_path / "child"
    repo.mkdir()
    (repo / ".ai").mkdir()
    (repo / ".ai" / "runtime").mkdir()
    (repo / ".ai" / "usage").mkdir()
    (repo / "features").mkdir()
    return repo


# ============================================================================
# Selftest Wrappers
# ============================================================================
# These wrappers allow running existing --selftest functions via pytest.
# Each wrapper imports the module and calls its selftest() function.
# This provides a unified test runner while preserving existing test logic.

# ─── МЁРТВЫЙ ГЕНЕРАТОР ОБЁРТОК СЕЛФТЕСТОВ УДАЛЁН (срез tests ратчета, 2026-08-12) ───────────────
#
# Здесь лежали два списка на 148 имён модулей, функция `_run_selftest`, фабрика
# `_make_selftest_test` и два цикла, кладущие сгенерированные `test_selftest_<модуль>` в
# `globals()`. Замер показал, что механизм был мёртв ДВАЖДЫ:
#
#   1. функции создавались в globals() САМОГО conftest.py, а pytest из conftest тесты НЕ СОБИРАЕТ:
#      сгенерировано 148, собрано 0;
#   2. даже будь они собраны, все 148 упали бы: ни один из перечисленных модулей не имеет
#      `def selftest()` — их вынесли в явные тест-файлы в v3.30, то есть предмет проверки удалён
#      двумя десятками версий назад.
#
# Поэтому механизм не «починен», а СНЯТ: включать его значило бы получить 148 красных тестов,
# требующих функцию, удалённую сознательно. Покрытие при этом не пострадало и было измерено:
# 158 явных файлов `tests/unit/test_*selftest*.py`, 190 собираемых тестов. Ссылок на снятые имена
# в репозитории нет (проверено grep по .py/.md/.sh).
#
# Честно про свой путь: сначала я улучшила сообщения `_run_selftest` — «модуль не импортируется» и
# «selftest() упал» перестали выглядеть как «selftest failed». Правка была верной по сути и
# бесполезной по адресу: полировка кода, который не исполняется. Замер (сколько тестов реально
# собирается) отменил её и заменил удалением.


# ============================================================================
# Pytest markers for CI layer separation
# ============================================================================

def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "critical_path: tests for critical execution path")
    config.addinivalue_line("markers", "unit: unit tests (fast, no external deps)")
    config.addinivalue_line("markers", "contract: contract tests (interface verification)")
    config.addinivalue_line("markers", "integration: integration tests (multi-module)")
    config.addinivalue_line("markers", "live: live tests (require external services)")
    config.addinivalue_line("markers", "regression: regression tests for known bugs")
    config.addinivalue_line("markers", "slow: tests that take >10 seconds")


def pytest_collection_modifyitems(config, items):
    """Проставить ярусный маркер по каталогу, если явного нет — пирамида читается числом.

    Ярус задаётся расположением (tests/tier_map.DIR_TIER): tests/unit -> unit, tests/contracts ->
    contract, tests/integration -> integration. Явный ярусный маркер на тесте не трогаем (тест
    вправе объявить ярус сам); ортогональные slow/live/regression/critical_path — не ярус.
    Тест в каталоге без известного яруса маркер НЕ получает: его ловит test_pyramid_is_tiered.
    """
    from tier_map import DIR_TIER, TIER_MARKERS

    tests_root = Path(__file__).resolve().parent
    for item in items:
        if TIER_MARKERS & {m.name for m in item.iter_markers()}:
            continue
        try:
            rel = Path(str(item.path)).resolve().relative_to(tests_root)
        except (ValueError, AttributeError):
            continue
        tier = DIR_TIER.get(rel.parts[0]) if rel.parts else None
        if tier:
            item.add_marker(getattr(pytest.mark, tier))
