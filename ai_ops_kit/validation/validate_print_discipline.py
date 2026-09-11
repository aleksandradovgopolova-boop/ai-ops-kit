#!/usr/bin/env python3
"""Ратчет дисциплины вывода: print в библиотечных слоях заморожен вниз (F-08 внешнего аудита).

`print()` печатает в stdout. В точке входа это её работа; в библиотечном пакете — нет: такой пакет
не переиспользовать из MCP/web без перехвата stdout, и у дочки нет ручки «покажи подробнее». Здесь
число print на пакет заморожено потолком и ходит ТОЛЬКО ВНИЗ.

Аллоу-лист (где print разрешён) — пакеты слоя `entrypoints` в packages/layering.yaml: ОДИН источник,
не хардкод. Потолки библиотечных пакетов — в packages/print-discipline-baseline.yaml. Семантика
потолка по «≤», как у module-size: пакет краснеет, если число print ВЫРОСЛО сверх потолка ИЛИ пакет
печатает, но записи в baseline нет (новый источник печати обязан появиться ОСОЗНАННО). Усыхание
(перевод print -> возврат/logging) не краснит; тест просит пере-снять потолок под факт.

Использование:
  validate_print_discipline.py            # проверить
  validate_print_discipline.py --report   # напечатать print по всем пакетам
Возврат 0 — чисто, 1 — есть нарушения.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import yaml

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
           Path(__file__).resolve().parents[1])
SURFACE = PKG / "ai_ops_kit"
LAYERING = PKG / "packages" / "layering.yaml"
BASELINE_FILE = PKG / "packages" / "print-discipline-baseline.yaml"


def load_yaml(path):
    return yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {}


def entrypoint_packages(layering=LAYERING) -> set[str]:
    """Пакеты слоя `entrypoints` — им print разрешён. Источник — layering.yaml, не список здесь."""
    spec = load_yaml(layering) or {}
    for layer in spec.get("layers") or []:
        if layer.get("name") == "entrypoints":
            return set(layer.get("packages") or [])
    return set()


def _count_prints(path: Path) -> int:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, OSError):
        return 0
    return sum(1 for n in ast.walk(tree)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "print")


def prints_by_package(surface=SURFACE) -> dict:
    """{пакет: число вызовов print} по AST всех .py каждого top-level пакета ai_ops_kit."""
    out: dict[str, int] = {}
    for d in sorted(surface.iterdir()):
        if not d.is_dir() or d.name == "__pycache__":
            continue
        out[d.name] = sum(_count_prints(f) for f in d.rglob("*.py"))
    return out


def ceilings_of(baseline: dict) -> dict:
    c = baseline.get("ceilings")
    return dict(c) if isinstance(c, dict) else {}


def check(counts: dict, ceilings: dict, allowed: set[str]) -> list[str]:
    """Сверить print библиотечных пакетов с потолками. -> список ошибок (пустой = ОК)."""
    errors = []
    if not ceilings:
        # Ошибка только когда есть что стеречь: если ни один библиотечный пакет не печатает, пусто ок.
        if any(n > 0 for p, n in counts.items() if p not in allowed):
            errors.append("ратчет print-discipline: библиотечные пакеты печатают, но секции ceilings "
                          "нет — потолка не существует, проверять не с чем")
        return errors
    for pkg, n in sorted(counts.items()):
        if pkg in allowed or n == 0:
            continue
        ceiling = ceilings.get(pkg)
        if ceiling is None:
            errors.append(f"ратчет print-discipline: пакет '{pkg}' печатает ({n}), но его нет в "
                          "ceilings — новый источник печати в библиотечном слое обязан появиться "
                          "ОСОЗНАННО (запись в baseline)")
        elif n > ceiling:
            errors.append(f"ратчет print-discipline: '{pkg}' стало {n} print при потолке {ceiling} — "
                          "новый print в библиотечном слое; вернуть данные/logging или осознанно поднять")
        elif n < ceiling:
            errors.append(f"ратчет print-discipline: '{pkg}' стало {n} print при потолке {ceiling} — "
                          "потолок снизился (print переведён), опустить в baseline (ратчет ходит вниз)")
    # Потолок на пакет, который стал entrypoint или исчез — мёртвая запись.
    for pkg in sorted(set(ceilings) - set(counts)):
        errors.append(f"ратчет print-discipline: потолок на пакет '{pkg}', которого нет — удалить")
    for pkg in sorted(set(ceilings) & allowed):
        errors.append(f"ратчет print-discipline: '{pkg}' в ceilings, но он entrypoint (print разрешён) "
                      "— удалить запись")
    return errors


def main(argv):
    counts = prints_by_package()
    allowed = entrypoint_packages()
    baseline = load_yaml(BASELINE_FILE) or {}
    ceilings = ceilings_of(baseline)
    if "--report" in argv:
        for pkg, n in sorted(counts.items(), key=lambda x: -x[1]):
            tag = "entrypoint" if pkg in allowed else f"потолок {ceilings.get(pkg, '—')}"
            print(f"{n:5d}  {pkg:16} {tag}")
        return 0
    errors = check(counts, ceilings, allowed)
    for e in errors:
        print(f"  [FAIL] {e}")
    if errors:
        print(f"PRINT-DISCIPLINE-FAIL: нарушений {len(errors)}")
        return 1
    lib = sum(n for p, n in counts.items() if p not in allowed)
    print(f"PRINT-DISCIPLINE-OK: библиотечных print {lib} в {len(ceilings)} пакетах — не выше потолка; "
          f"точки входа ({', '.join(sorted(allowed))}) не ограничены.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
