#!/usr/bin/env python3
from __future__ import annotations
"""Validate package boundaries (v2.46, 3.0-срез 0 — подготовка сплита БЕЗ переноса файлов).

Дизайн 3.0 (docs/3.0-design.md) делит кит на 5 пакетов. Этот валидатор стережёт границы
ДЕКЛАРАТИВНО, пока файлы физически не разнесены: он читает packages/<name>/package.yaml и
проверяет, что структура пригодна для будущего сплита:

  1. форма package.yaml валидна (name/kind/description/depends_on/includes);
  2. depends_on ссылается только на существующие пакеты, без self-dep;
  3. граф зависимостей ацикличен (DAG) — иначе сплит невозможен;
  4. каждый include-glob резолвится хотя бы в один реальный путь (нет висячих деклараций);
  5. ни один файл не заявлен двумя пакетами (границы не пересекаются);
  6. отчёт покрытия: сколько файлов назначено и что пока не назначено (информационно —
     полное покрытие достигается в срезе 3, здесь важна непротиворечивость).

Инвариант честности: валидатор проверяет ДЕКЛАРАЦИЮ, не трогает файлы; пока это подготовка,
не сам сплит. Возврат 0 — границы согласованы; 1 — ошибка.

Использование:  validate_package_boundaries.py [--selftest]
"""

import sys
from pathlib import Path

import yaml

PKG = Path(__file__).resolve().parents[1]
REQUIRED = {"schema_version", "kind", "name", "description", "depends_on", "includes"}


def load_packages(pkg_root):
    """Прочитать все packages/<name>/package.yaml -> {name: decl}."""
    out = {}
    root = Path(pkg_root)
    for pf in sorted(root.glob("packages/*/package.yaml")):
        data = yaml.safe_load(pf.read_text(encoding="utf-8")) or {}
        out[pf.parent.name] = data
    return out


def _expand(root, patterns):
    """glob-паттерны -> множество относительных путей к ФАЙЛАМ (каталоги раскрываются).
    Паттерн вида 'dir/**' нормализуется в 'dir/**/*' (pathlib: '**' сам по себе матчит только
    каталоги; чтобы получить файлы рекурсивно — нужен хвост '/*')."""
    files = set()
    for pat in patterns:
        eff = pat + "/*" if pat.endswith("/**") else pat
        for p in root.glob(eff):
            if p.is_file():
                files.add(p.relative_to(root).as_posix())
    return files


def _has_cycle(graph):
    """DFS-детект цикла в ориентированном графе {node: [deps]}. Возвращает путь цикла или None."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in graph}
    stack = []

    def dfs(n):
        color[n] = GRAY
        stack.append(n)
        for m in graph.get(n, []):
            if m not in color:
                continue
            if color[m] == GRAY:
                return stack[stack.index(m):] + [m]
            if color[m] == WHITE:
                r = dfs(m)
                if r:
                    return r
        color[n] = BLACK
        stack.pop()
        return None

    for n in graph:
        if color[n] == WHITE:
            r = dfs(n)
            if r:
                return r
    return None


def check(pkg_root):
    """Список ошибок (пустой = границы согласованы) + отчёт покрытия во втором элементе."""
    root = Path(pkg_root)
    pkgs = load_packages(root)
    errs, report = [], {}
    if not pkgs:
        return ["не найдено ни одного packages/*/package.yaml"], report

    # 1. форма
    for name, d in pkgs.items():
        missing = REQUIRED - set(d)
        if missing:
            errs.append(f"{name}: нет обязательных полей {sorted(missing)}")
            continue
        if d.get("name") != name:
            errs.append(f"{name}: поле name='{d.get('name')}' не совпадает с каталогом")
        if d.get("kind") != "ai-ops-package":
            errs.append(f"{name}: kind должен быть 'ai-ops-package'")
        if not isinstance(d.get("includes"), list) or not d["includes"]:
            errs.append(f"{name}: includes должен быть непустым списком")
        if not isinstance(d.get("depends_on"), list):
            errs.append(f"{name}: depends_on должен быть списком")

    if errs:
        return errs, report

    # 2. depends_on: существование + без self
    for name, d in pkgs.items():
        for dep in d["depends_on"]:
            if dep == name:
                errs.append(f"{name}: self-зависимость запрещена")
            elif dep not in pkgs:
                errs.append(f"{name}: depends_on ссылается на несуществующий пакет '{dep}'")

    # 3. DAG
    graph = {name: list(d["depends_on"]) for name, d in pkgs.items()}
    cyc = _has_cycle(graph)
    if cyc:
        errs.append(f"цикл зависимостей пакетов: {' -> '.join(cyc)}")

    # 4. резолв include + 5. пересечения
    owned = {}          # relpath -> package
    for name, d in pkgs.items():
        for pat in d["includes"]:
            matched = _expand(root, [pat])
            if not matched:
                errs.append(f"{name}: include-glob '{pat}' не резолвится ни в один файл (висячая декларация)")
            for f in matched:
                if f in owned and owned[f] != name:
                    errs.append(f"файл '{f}' заявлен двумя пакетами: {owned[f]} и {name} (границы пересекаются)")
                else:
                    owned[f] = name

    # 6. покрытие (информационно)
    all_files = {p.relative_to(root).as_posix() for p in root.rglob("*")
                 if p.is_file() and ".git/" not in p.relative_to(root).as_posix()}
    assigned = set(owned)
    unassigned = sorted(all_files - assigned)
    report = {"packages": len(pkgs), "files_assigned": len(assigned),
              "files_unassigned": len(unassigned),
              "unassigned_sample": unassigned[:15]}
    return errs, report


def main(argv):
    errs, rep = check(PKG)
    if errs:
        print("PACKAGE-BOUNDARIES: НАРУШЕНИЯ:")
        for e in errs:
            print(f"  - {e}")
        return 1
    print(f"PACKAGE-BOUNDARIES-OK: {rep['packages']} пакетов, границы не пересекаются, граф ацикличен. "
          f"Назначено {rep['files_assigned']} файлов, не назначено {rep['files_unassigned']} "
          f"(назначаются в 3.0-срезе 3).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
