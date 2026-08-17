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

# Add tools/ to path for imports.
# v3.34: валидаторы переехали в ai_ops_kit/validation/. Плоское имя оставлено ЗДЕСЬ намеренно —
# тесты импортируют валидатор как модуль (`from validate_x import check`), и переписывать 70
# файлов ради формы импорта в харнессе смысла нет. Это не пояс: доказательство того, что
# валидатор работает БЕЗ путей, даёт test_validator_runtime_contract — он запускает каждый
# процессом из копии репозитория с вычищенным PYTHONPATH.
PKG_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = PKG_ROOT / "tools"
VALIDATION_DIR = PKG_ROOT / "ai_ops_kit" / "validation"
for p in (TOOLS_DIR, VALIDATION_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


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
