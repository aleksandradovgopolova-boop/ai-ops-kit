"""Docstring gates/invariants.py не ссылается на несуществующие пути и функции.

Ревизия 2026-08-25: docstring показывал `from invariants import ... selftest` (selftest не существует)
и `python3 tools/invariants.py --selftest` (файл tools/invariants.py — фантом). Тест краснеет на
фантомных ссылках, заставляя держать документацию честной.
"""
from __future__ import annotations

import re
from pathlib import Path


def test_invariants_docstring_no_phantom_selftest():
    """Docstring не импортирует selftest (функции нет в модуле)."""
    from ai_ops_kit.gates import invariants

    docstring = invariants.__doc__ or ""
    # Ищем паттерн импорта selftest: "from ... import ... selftest"
    # или "import selftest"
    phantom_patterns = [
        r"from\s+\S+\s+import\s+[^#\n]*\bselftest\b",
        r"import\s+selftest\b",
    ]
    for pattern in phantom_patterns:
        assert not re.search(pattern, docstring), (
            f"Docstring invariants.py ссылается на selftest, которого нет в модуле. "
            f"Удалите selftest из примера импорта."
        )


def test_invariants_docstring_no_phantom_tools_path():
    """Docstring не ссылается на tools/invariants.py (файла нет)."""
    from ai_ops_kit.gates import invariants

    docstring = invariants.__doc__ or ""
    # Ищем упоминание tools/invariants.py или tools/invariants
    assert "tools/invariants" not in docstring, (
        "Docstring invariants.py ссылается на tools/invariants.py, которого не существует. "
        "Реальный путь: ai_ops_kit/gates/invariants.py"
    )


def test_invariants_docstring_shows_real_import_path():
    """Docstring показывает реальный путь импорта: from ai_ops_kit.gates.invariants import ..."""
    from ai_ops_kit.gates import invariants

    docstring = invariants.__doc__ or ""
    # Должен быть пример импорта из пакета
    assert re.search(r"from\s+ai_ops_kit\.gates\.invariants\s+import", docstring), (
        "Docstring invariants.py не показывает реальный путь импорта. "
        "Добавьте пример: from ai_ops_kit.gates.invariants import check_invariant, ALL_INVARIANTS"
    )
