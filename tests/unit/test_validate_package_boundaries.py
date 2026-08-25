"""Гранулярные тесты validate_package_boundaries (миграция из селфтеста v3.30)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from validate_package_boundaries import (  # noqa: F401
    PKG,
    Path as _Path,
    check,
    yaml,
)


def _write_pkg(root, name, depends_on, includes):
    d = root / "packages" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "package.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "kind": "ai-ops-package",
                "name": name,
                "description": "x",
                "depends_on": depends_on,
                "includes": includes,
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture
def valid_root(tmp_path):
    """Валидный минимальный набор пакетов."""
    root = tmp_path
    (root / "core").mkdir()
    (root / "core" / "a.txt").write_text("x", encoding="utf-8")
    (root / "q").mkdir()
    (root / "q" / "b.txt").write_text("y", encoding="utf-8")
    _write_pkg(root, "ai-ops-core", [], ["core/**"])
    _write_pkg(root, "ai-ops-quality", ["ai-ops-core"], ["q/**"])
    return root


@pytest.mark.unit
def test_valid_set_no_errors(valid_root):
    """Валидный набор -> без ошибок."""
    errs, rep = check(valid_root)
    assert errs == [], errs
    assert rep["files_assigned"] == 2


@pytest.mark.unit
def test_dependency_cycle_is_error(tmp_path):
    """Цикл зависимостей -> ошибка."""
    root = tmp_path
    (root / "core").mkdir()
    (root / "core" / "a.txt").write_text("x", encoding="utf-8")
    (root / "q").mkdir()
    (root / "q" / "b.txt").write_text("y", encoding="utf-8")
    _write_pkg(root, "ai-ops-core", ["ai-ops-quality"], ["core/**"])
    _write_pkg(root, "ai-ops-quality", ["ai-ops-core"], ["q/**"])
    errs, _ = check(root)
    assert any("цикл" in e for e in errs), errs


@pytest.mark.unit
def test_dangling_include_glob_is_error(tmp_path):
    """Висячий include-glob -> ошибка."""
    root = tmp_path
    (root / "core").mkdir()
    (root / "core" / "a.txt").write_text("x", encoding="utf-8")
    _write_pkg(root, "ai-ops-core", [], ["core/**", "nonexistent/**"])
    errs, _ = check(root)
    assert any("не резолвится" in e for e in errs), errs


@pytest.mark.unit
def test_file_overlap_is_error(tmp_path):
    """Пересечение файлов -> ошибка."""
    root = tmp_path
    (root / "shared").mkdir()
    (root / "shared" / "a.txt").write_text("x", encoding="utf-8")
    _write_pkg(root, "ai-ops-core", [], ["shared/**"])
    _write_pkg(root, "ai-ops-quality", ["ai-ops-core"], ["shared/**"])
    errs, _ = check(root)
    assert any("двумя пакетами" in e for e in errs), errs


@pytest.mark.unit
def test_nonexistent_dependency_is_error(tmp_path):
    """depends_on на несуществующий пакет -> ошибка."""
    root = tmp_path
    (root / "core").mkdir()
    (root / "core" / "a.txt").write_text("x", encoding="utf-8")
    _write_pkg(root, "ai-ops-core", ["ai-ops-ghost"], ["core/**"])
    errs, _ = check(root)
    assert any("несуществующий пакет" in e for e in errs), errs


@pytest.mark.unit
def test_real_kit_boundaries_are_consistent():
    """Реальные границы кита согласованы."""
    errs, rep = check(PKG)
    assert errs == [], errs
    # покрытие посчитано
    assert rep.get("files_assigned") is not None
