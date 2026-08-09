"""Селфтест validate_package_boundaries, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_package_boundaries import (  # noqa: F401 — имена, которые использует тело
    PKG,
    Path,
    check,
    yaml,
)


@pytest.mark.slow
def test_validate_package_boundaries_selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    def write_pkg(root, name, depends_on, includes):
        d = root / "packages" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "package.yaml").write_text(yaml.safe_dump({
            "schema_version": 1, "kind": "ai-ops-package", "name": name,
            "description": "x", "depends_on": depends_on, "includes": includes}),
            encoding="utf-8")

    # валидный минимальный набор
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "core").mkdir(); (root / "core" / "a.txt").write_text("x", encoding="utf-8")
        (root / "q").mkdir(); (root / "q" / "b.txt").write_text("y", encoding="utf-8")
        write_pkg(root, "ai-ops-core", [], ["core/**"])
        write_pkg(root, "ai-ops-quality", ["ai-ops-core"], ["q/**"])
        errs, rep = check(root)
        expect("валидный набор -> без ошибок", errs == [])
        expect("покрытие посчитано", rep["files_assigned"] == 2)

    # цикл
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "core").mkdir(); (root / "core" / "a.txt").write_text("x", encoding="utf-8")
        (root / "q").mkdir(); (root / "q" / "b.txt").write_text("y", encoding="utf-8")
        write_pkg(root, "ai-ops-core", ["ai-ops-quality"], ["core/**"])
        write_pkg(root, "ai-ops-quality", ["ai-ops-core"], ["q/**"])
        errs, _ = check(root)
        expect("цикл зависимостей -> ошибка", any("цикл" in e for e in errs))

    # висячий glob
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "core").mkdir(); (root / "core" / "a.txt").write_text("x", encoding="utf-8")
        write_pkg(root, "ai-ops-core", [], ["core/**", "nonexistent/**"])
        errs, _ = check(root)
        expect("висячий include-glob -> ошибка", any("не резолвится" in e for e in errs))

    # пересечение границ
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "shared").mkdir(); (root / "shared" / "a.txt").write_text("x", encoding="utf-8")
        write_pkg(root, "ai-ops-core", [], ["shared/**"])
        write_pkg(root, "ai-ops-quality", ["ai-ops-core"], ["shared/**"])
        errs, _ = check(root)
        expect("пересечение файлов -> ошибка", any("двумя пакетами" in e for e in errs))

    # несуществующая зависимость
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "core").mkdir(); (root / "core" / "a.txt").write_text("x", encoding="utf-8")
        write_pkg(root, "ai-ops-core", ["ai-ops-ghost"], ["core/**"])
        errs, _ = check(root)
        expect("depends_on на несуществующий пакет -> ошибка", any("несуществующий пакет" in e for e in errs))

    # реальный пакет кита
    errs, rep = check(PKG)
    expect("реальные границы кита согласованы", errs == [])
    print(f"  покрытие: {rep.get('files_assigned')} назначено, {rep.get('files_unassigned')} не назначено")

    assert ok, "перенесённый селфтест validate_package_boundaries: см. строки FAIL в выводе"
