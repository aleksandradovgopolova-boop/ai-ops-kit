#!/usr/bin/env python3
"""Направления зависимостей между пакетами ai_ops_kit/* против packages/layering.yaml (v3.32.0).

Переезд в пакеты (3.31.0) дал модулям имена, но не дал границам силы: `gates` мог импортировать
`engops`, и никто бы не заметил. Здесь граф импортов СЧИТАЕТСЯ по коду и сверяется с объявленным.

Ратчет, а не строгий DAG: в коде 9 взаимных зависимостей и 31 цикл длиннее двух. Правило,
краснеющее на всём сразу, выключают — поэтому запрещены нарушения ПОПЕРЁК слоёв, а известные
исключения перечислены поимённо и вправе только сокращаться. Исчезнувшее исключение обязано быть
удалено из реестра: список, который разрешает несуществующее, перестаёт что-либо значить.

С v3.34 замер сам стал потолком (`ratchet_errors`): взаимные связи внутри `capabilities` слоями
разрешены, и без потолка это значило «расти можно». Ратчет ходит только вниз.

Импорты считаются по ПЛОСКОМУ имени (`import tool_broker`) и по пакетному
(`from ai_ops_kit.engine.tool_broker import ...`) — переход на пакетные имена идёт отдельно, и
проверка не должна ослепнуть на полпути.

Использование:
  validate_layering.py                # проверить
  validate_layering.py --graph        # напечатать рёбра (для разбора циклов)
  validate_layering.py --counts       # напечатать замер: взаимные пары, циклы длиннее двух
Возврат 0 — чисто, 1 — есть нарушения.
"""
from __future__ import annotations

import ast
import sys
from collections import defaultdict
from pathlib import Path

import yaml

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
           Path(__file__).resolve().parents[1])
SURFACE = PKG / "ai_ops_kit"
SPEC = PKG / "packages" / "layering.yaml"


def load_spec(path=SPEC):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def module_owners(surface=SURFACE):
    """{плоское имя модуля: пакет} — по фактическому дереву, а не по списку в конфиге."""
    owners = {}
    for d in sorted(surface.iterdir()):
        if not d.is_dir() or d.name == "__pycache__":
            continue
        for f in sorted(d.glob("*.py")):
            if f.name != "__init__.py":
                owners[f.stem] = d.name
    return owners


def _imported_names(src, filename=None):
    """Имена верхнего уровня из import/from — через AST, а не регуляркой по строкам."""
    try:
    # Имя файла — часть сообщения интерпретатора (F-022): без него предупреждение
    # подписывается `<unknown>`, и владелец не может понять, чей файл его вызвал.
        tree = ast.parse(src, filename=filename or "<unknown>")
    except SyntaxError:
        return []
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.append(node.module)
    return names


def build_graph(surface=SURFACE):
    """{(из пакета, в пакет): {'модуль->модуль', ...}} по реальным импортам."""
    owners = module_owners(surface)
    edges = defaultdict(set)
    for d in sorted(surface.iterdir()):
        if not d.is_dir() or d.name == "__pycache__":
            continue
        for f in sorted(d.glob("*.py")):
            if f.name == "__init__.py":
                continue
            for name in _imported_names(f.read_text(encoding="utf-8"), filename=str(f)):
                parts = name.split(".")
                # Обе пакетные формы: `from ai_ops_kit.<пакет> import <модуль>` даёт module из ДВУХ
                # частей, `from ai_ops_kit.<пакет>.<модуль> import <имя>` — из трёх. Требование
                # len>=3 стоило проверке зрения: после перевода импортов она видела 4 ребра из 49.
                if parts[0] == "ai_ops_kit" and len(parts) >= 2:
                    target = parts[1]
                elif parts[0] in owners:
                    target = owners[parts[0]]              # плоское имя (пока остались)
                else:
                    continue
                if target != d.name:
                    edges[(d.name, target)].add(f"{f.stem} -> {parts[-1]}")
    return dict(edges)


def cyclic_counts(edges):
    """Взаимные пары и элементарные циклы длиннее двух в пакетном графе.

    Цикл считается ОДИН раз, а не по разу с каждой стартовой вершины. Обход продолжается только
    в вершины строго больше стартовой, поэтому каждый элементарный цикл перечисляется ровно
    однажды — тем обходом, что начат в его минимальной вершине. Цикл и его обратный — разные
    циклы направленного графа, оба считаются: это разные связи в коде.

    v3.34: прежний замер (119) считал РОТАЦИИ — каждый цикл по разу с каждой своей вершины, то
    есть 11 троек, 14 четвёрок и 6 пятёрок давали 33+56+30. Различных циклов 31. Число, зависящее
    от способа обхода, потолком быть не может: следующий посчитает иначе и получит другой ответ.
    """
    nodes = sorted({p for e in edges for p in e})
    adj = {n: sorted({b for (a, b) in edges if a == n}) for n in nodes}
    mutual = {tuple(sorted(e)) for e in edges if (e[1], e[0]) in edges}
    found = []

    def walk(start, node, path, seen):
        for nxt in adj.get(node, ()):
            if nxt == start:
                if len(path) > 2:
                    found.append(tuple(path))
            elif nxt not in seen and nxt > start:
                walk(start, nxt, path + [nxt], seen | {nxt})

    for start in nodes:
        walk(start, start, [start], {start})
    return {"mutual_pairs": len(mutual), "cycles_longer_than_two": len(found)}


def ratchet_errors(spec, edges):
    """Замер циклов ядра как потолок: новых связей не появляется, а ушедшие обязаны быть списаны.

    Взаимные связи ВНУТРИ `capabilities` слоями разрешены сознательно (см. purpose слоя), поэтому
    `check` о них ничего не говорит. Без потолка это значит «расти можно»: замер 3.32 был записью
    в файле, которую никто не читал. Ратчет ходит только вниз — ровно как реестр known_violations.
    """
    base = spec.get("baseline") or {}
    errors = []
    for key, actual in sorted(cyclic_counts(edges).items()):
        declared = base.get(key)
        if not isinstance(declared, int) or isinstance(declared, bool):
            errors.append(f"ратчет {key}: в baseline нет числа (сейчас {actual}) — "
                          "потолка не существует, проверять не с чем")
        elif actual > declared:
            errors.append(f"ратчет {key}: стало {actual} при потолке {declared} — новая взаимная "
                          "связь или цикл внутри ядра; развязать или осознанно поднять потолок")
        elif actual < declared:
            errors.append(f"ратчет {key}: стало {actual} при потолке {declared} — связь ушла, "
                          "опустить потолок в packages/layering.yaml (ратчет ходит только вниз)")
    return errors


def _layer_index(spec):
    idx = {}
    for i, layer in enumerate(spec.get("layers") or []):
        for p in layer.get("packages") or []:
            idx[p] = i
    return idx


def check_kernel_boundary(spec, edges):
    """Правило kernel-boundary: ядро не импортирует спутники.

    Слои запрещают зависимость вверх (intelligence выше capabilities), но planning и engops
    лежат в том же слое capabilities, что и ядро. Без правила поверх слоёв ядро могло бы
    импортировать их молча. Эта проверка закрывает дыру: kernel_members не вправе тянуть
    forbidden_imports, независимо от слоёв.

    Известные нарушения (known_violations) учитываются: если ребро уже заморожено, оно не
    краснеет повторно. Это согласовано с check() — один реестр на все правила.
    """
    errors = []
    caught = set()
    known = set()
    for item in spec.get("known_violations") or []:
        known.add(tuple(str(item).split(":")[0].strip().split(" -> ")))
    for rule in spec.get("rules") or []:
        if rule.get("id") != "kernel-boundary":
            continue
        members = set(rule.get("kernel_members") or [])
        forbidden = set(rule.get("forbidden_imports") or [])
        reason = rule.get("reason", "")
        for (src, dst), why in sorted(edges.items()):
            if src in members and dst in forbidden:
                caught.add((src, dst))
                if (src, dst) not in known:
                    errors.append(
                        f"LAYERING-FAIL: kernel-boundary: {src} -> {dst} "
                        f"({reason}); импорты: {sorted(why)[:3]}")
    return errors, caught


def check(spec, edges, extra_seen=None):
    """Список нарушений: зависимость вверх по слоям, нарушение rules, протухшее исключение.

    extra_seen — рёбра, пойманные другими проверками (kernel-boundary). Известное нарушение,
    которое существует в коде и поймано другой проверкой, не обязано быть поймано ещё и здесь —
    иначе реестр known_violations стал бы конфликтовать сам с собой.
    """
    errors = []
    idx = _layer_index(spec)
    known = set()
    for item in spec.get("known_violations") or []:
        known.add(tuple(str(item).split(":")[0].strip().split(" -> ")))

    unknown_pkgs = sorted({p for e in edges for p in e} - set(idx))
    if unknown_pkgs:
        errors.append(f"пакеты вне слоёв (объявить в layering.yaml): {unknown_pkgs}")

    # kernel-boundary рёбра: существуют в коде, но не являются нарушением слоёв (тот же слой).
    # Без этого известное нарушение engine -> engops было бы помечено как «исчезло», потому что
    # check() его не видит (оба в capabilities), а check_kernel_boundary() не вызван.
    kb_edges = set()
    for rule in spec.get("rules") or []:
        if rule.get("id") != "kernel-boundary":
            continue
        members = set(rule.get("kernel_members") or [])
        forbidden = set(rule.get("forbidden_imports") or [])
        for (src, dst) in edges:
            if src in members and dst in forbidden:
                kb_edges.add((src, dst))

    seen = set(extra_seen or set()) | kb_edges
    for (src, dst), why in sorted(edges.items()):
        if src not in idx or dst not in idx:
            continue
        violation = None
        if idx[dst] > idx[src]:
            violation = f"зависимость ВВЕРХ по слоям: {src} -> {dst}"
        for rule in spec.get("rules") or []:
            f = rule.get("forbid") or {}
            if (f.get("to") in (None, dst) and f.get("from") in (None, src)
                    and (f.get("to") or f.get("from"))):
                violation = f"правило {rule['id']}: {src} -> {dst} ({rule['reason']})"
        if violation:
            if (src, dst) in known:
                seen.add((src, dst))
            else:
                errors.append(f"{violation}; импорты: {sorted(why)[:3]}")

    for stale in sorted(known - seen):
        errors.append(f"известное нарушение {stale[0]} -> {stale[1]} исчезло из кода — "
                      "удалить из known_violations (реестр вправе только сокращаться)")
    return errors


def main(argv):
    spec = load_spec()
    edges = build_graph()
    if "--graph" in argv:
        try:
            for (a, b), why in sorted(edges.items(), key=lambda kv: (-len(kv[1]), kv[0])):
                print(f"{len(why):4}  {a} -> {b}")
        except BrokenPipeError:      # `--graph | head` — не повод для трейсбека
            pass
        return 0
    counts = cyclic_counts(edges)
    if "--counts" in argv:
        for k, v in sorted(counts.items()):
            print(f"{k}: {v}")
        return 0
    kb_errors, kb_caught = check_kernel_boundary(spec, edges)
    errors = check(spec, edges, extra_seen=kb_caught) + kb_errors + ratchet_errors(spec, edges)
    for e in errors:
        print(f"  [FAIL] {e}")
    if errors:
        print(f"LAYERING-FAIL: нарушений {len(errors)}")
        return 1
    print(f"LAYERING-OK: {len(edges)} межпакетных рёбер, все в объявленных границах; "
          f"взаимных пар {counts['mutual_pairs']}, циклов длиннее двух "
          f"{counts['cycles_longer_than_two']} — не выше потолка.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
