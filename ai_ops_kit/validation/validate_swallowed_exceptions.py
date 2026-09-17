#!/usr/bin/env python3
"""Ратчет молчаливых глушителей исключений в ai_ops_kit/ — заморозить их число вниз (B3).

`except ...: pass` глушит ошибку молча: код «не смог», но ведёт себя так, будто всё хорошо. Это
прямо против философии кита «не смог ≠ всё хорошо». Прежде число таких глушителей ревьюили РАЗОВО
(#721, `checks-that-run.swallowed_exceptions_reviewed`), но стоячего сторожа не было — новый
молчаливый глушитель мог просочиться незамеченным. Здесь их число заморожено ПОТОЛКОМ на текущем
значении и ходит ТОЛЬКО ВНИЗ.

Что считается глушителем: обработчик `except ...:` (в т.ч. голый `except:`), чьё тело — РОВНО один
оператор `pass`. Детект — AST (модуль `ast`), а не регэксп: комментарии и строки, где встречается
слово pass, не считаются, а многострочный `except`, реально гасящий ошибку, — считается.

Семантика потолка — по «≤», как у module-size:
  * число глушителей ВЫРОСЛО сверх baseline  -> FAIL: новый молчаливый глушитель обязан появиться
    ОСОЗНАННО (либо обработать ошибку, либо осознанно поднять baseline);
  * число РАВНО baseline                      -> OK;
  * число МЕНЬШЕ baseline                      -> OK, но подсказка «опусти baseline» (ратчет ходит
    только вниз: снятый глушитель обязан опустить линию, чтобы место не отросло обратно).

Идея — «новые глушители называют себя», а не «переписать все прямо сейчас»: потолок держит рост, но
не заставляет чинить существующее в этот момент. Сопутствующий тест `tests/unit/
test_swallowed_exceptions.py` сверяет, что baseline == фактическому числу, и просит пере-снять
baseline, если оно снизилось.

Использование:
  validate_swallowed_exceptions.py            # проверить фактическое число против baseline
  validate_swallowed_exceptions.py --report   # напечатать все глушители по файлам без проверки
  validate_swallowed_exceptions.py --baseline  # пере-снять baseline текущим замером

Возврат 0 — число не выросло, 1 — выросло сверх baseline.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import yaml

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
           Path(__file__).resolve().parents[1])
SOURCE_ROOT = "ai_ops_kit"
BASELINE_FILE = PKG / "packages" / "swallowed-exceptions-baseline.yaml"


def _is_swallower(handler: ast.ExceptHandler) -> bool:
    """Обработчик, чьё тело — РОВНО один `pass` (молчаливый глушитель)."""
    body = handler.body
    return len(body) == 1 and isinstance(body[0], ast.Pass)


def _count_in_file(path: Path) -> int:
    """Число `except ...: pass`-глушителей в одном файле (AST, не регэксп)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, OSError):
        return 0
    return sum(1 for n in ast.walk(tree)
               if isinstance(n, ast.ExceptHandler) and _is_swallower(n))


def measure_swallowers(pkg_root: Path = PKG) -> list[dict]:
    """Все живые `ai_ops_kit/**/*.py` с числом глушителей. -> список {'path', 'count'} (count>0).

    Тесты (tests/ вне пакета, а также любой path с /tests/ или файл test_*.py) исключены:
    сторож про ЖИВОЙ код, а не про пробы, которые нарочно гасят ошибку в фикстуре.
    """
    results = []
    root = pkg_root / SOURCE_ROOT
    for f in sorted(root.rglob("*.py")):
        rel = f.as_posix()
        if "/tests/" in rel or f.name.startswith("test_"):
            continue
        count = _count_in_file(f)
        if count:
            results.append({"path": f.relative_to(pkg_root).as_posix(), "count": count})
    return results


def total_of(swallowers: list[dict]) -> int:
    """Суммарное число глушителей по всем файлам."""
    return sum(m["count"] for m in swallowers)


def load_baseline(path: Path = BASELINE_FILE) -> dict:
    """Загрузить baseline из YAML. -> dict (пустой, если файла нет)."""
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def baseline_count(baseline: dict) -> int | None:
    """Замороженное число из baseline (ключ `baseline`). -> int или None, если его нет/не число."""
    value = baseline.get("baseline")
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def check(total: int, baseline: dict) -> list[str]:
    """Сверить фактическое число глушителей с baseline. -> список ошибок (пустой = ОК).

    Красит ТОЛЬКО рост. Снижение не ошибка (усыхать можно свободно) — лишь подсказка опустить
    линию, чтобы освобождённое место не отросло обратно; она печатается main'ом, а не здесь.
    """
    frozen = baseline_count(baseline)
    if frozen is None:
        return ["ратчет swallowed-exceptions: в baseline нет числа `baseline` — линия не "
                "зафиксирована, стеречь не с чем; пере-снять packages/swallowed-exceptions-baseline.yaml"]
    if total > frozen:
        return [f"ратчет swallowed-exceptions: молчаливых глушителей стало {total} при потолке "
                f"{frozen} — новый `except ...: pass` глушит ошибку молча; обработать ошибку "
                f"(логировать/вернуть), а не гасить, либо осознанно поднять baseline"]
    return []


def render_report(swallowers: list[dict]) -> str:
    """Человекочитаемый отчёт: все файлы с глушителями, по убыванию числа."""
    ordered = sorted(swallowers, key=lambda m: (-m["count"], m["path"]))
    lines = [f"Молчаливых глушителей всего: {total_of(swallowers)} в {len(ordered)} файле(ах)"]
    for m in ordered:
        lines.append(f"  {m['count']:3d}  {m['path']}")
    return "\n".join(lines)


def write_baseline(total: int, path: Path = BASELINE_FILE) -> None:
    """Пере-снять baseline текущим замером."""
    prev = load_baseline(path)
    data = {
        "schema_version": 1,
        "kind": "swallowed-exceptions-ratchet",
        "baseline": total,
    }
    note = prev.get("note")
    if note:
        data["note"] = note
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv[1:])
    swallowers = measure_swallowers()
    total = total_of(swallowers)

    if "--report" in argv:
        print(render_report(swallowers))
        return 0

    if "--baseline" in argv:
        write_baseline(total)
        print(f"Baseline обновлён: {total} молчаливых глушителей зафиксировано.")
        return 0

    baseline = load_baseline()
    errors = check(total, baseline)
    for e in errors:
        print(f"  [FAIL] {e}")
    if errors:
        print(f"SWALLOWED-EXCEPTIONS-FAIL: нарушений {len(errors)}")
        return 1

    frozen = baseline_count(baseline)
    if total < frozen:
        print(f"SWALLOWED-EXCEPTIONS-OK: молчаливых глушителей {total} — ниже потолка {frozen}; "
              f"опусти baseline до {total} (ратчет ходит только вниз): "
              f"validate_swallowed_exceptions.py --baseline")
    else:
        print(f"SWALLOWED-EXCEPTIONS-OK: молчаливых глушителей {total} — не выше потолка {frozen}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
