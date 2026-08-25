#!/usr/bin/env python3
"""Ратчет максимального размера функции в ai_ops_kit/engine/.

AST-обход всех .py файлов в engine/, для каждой function/async function считает
end_lineno - lineno + 1. Выводит max-функцию, топ-10, и возвращает 0 если max <= baseline,
1 если превышен.

Ратчет ходит ТОЛЬКО ВНИЗ: снижение потолка обязано быть записано в baseline-файл.
Превышение — красный сигнал: новая god-функция или рефакторинг не завершён.

Использование:
  validate_func_size.py              # проверить против baseline
  validate_func_size.py --report     # напечатать топ-10 без проверки
  validate_func_size.py --baseline   # обновить baseline текущим замером

Возврат 0 — в пределах потолка, 1 — превышен.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import yaml

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
           Path(__file__).resolve().parents[1])
ENGINE_DIR = PKG / "ai_ops_kit" / "engine"
BASELINE_FILE = PKG / "packages" / "func-size-baseline.yaml"


def measure_functions(directory: Path = ENGINE_DIR) -> list[dict]:
    """AST-обход: для каждой function/async function возвращает имя, файл, строки, размер."""
    results = []
    for f in sorted(directory.glob("*.py")):
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                size = node.end_lineno - node.lineno + 1
                results.append({
                    "name": node.name,
                    "file": f.name,
                    "lineno": node.lineno,
                    "size": size,
                })
    return results


def top_n(funcs: list[dict], n: int = 10) -> list[dict]:
    """Топ-N крупнейших функций, по убыванию размера."""
    return sorted(funcs, key=lambda f: f["size"], reverse=True)[:n]


def load_baseline(path: Path = BASELINE_FILE) -> dict:
    """Загрузить baseline из YAML. Возвращает dict с 'max_function_lines'."""
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def check(funcs: list[dict], baseline: dict) -> list[str]:
    """Сверить текущий максимум с baseline. Возвращает список ошибок (пустой = ОК)."""
    ceiling = baseline.get("max_function_lines")
    if not isinstance(ceiling, int) or isinstance(ceiling, bool):
        return ["ратчет func-size: в baseline нет числа max_function_lines — потолка не существует"]
    actual_max = max((f["size"] for f in funcs), default=0)
    if actual_max > ceiling:
        worst = max(funcs, key=lambda f: f["size"])
        return [
            f"ратчет func-size: max {actual_max} строк ({worst['file']}:{worst['lineno']} "
            f"{worst['name']}) превышает потолок {ceiling} — новая god-функция или "
            f"рефакторинг не завершён; опустить потолок после разбиения"
        ]
    if actual_max < ceiling:
        return [
            f"ратчет func-size: max {actual_max} строк при потолке {ceiling} — потолок снизился, "
            f"опустить в packages/func-size-baseline.yaml (ратчет ходит только вниз)"
        ]
    return []


def render_report(funcs: list[dict], n: int = 10) -> str:
    """Человекочитаемый отчёт: топ-N крупнейших функций."""
    lines = [f"Всего функций: {len(funcs)}"]
    for f in top_n(funcs, n):
        lines.append(f"  {f['size']:5d}  {f['file']}:{f['lineno']}  {f['name']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv[1:])
    funcs = measure_functions()

    if "--report" in argv:
        print(render_report(funcs))
        return 0

    if "--baseline" in argv:
        actual_max = max((f["size"] for f in funcs), default=0)
        worst = max(funcs, key=lambda f: f["size"]) if funcs else {}
        data = {
            "max_function_lines": actual_max,
            "max_function": worst.get("name", ""),
            "max_function_file": worst.get("file", ""),
            "max_function_lineno": worst.get("lineno", 0),
            "top_10": [{"name": f["name"], "file": f["file"],
                        "lineno": f["lineno"], "size": f["size"]}
                       for f in top_n(funcs, 10)],
        }
        BASELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE_FILE.write_text(
            yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
        print(f"Baseline обновлён: max={actual_max} ({worst.get('file')}:{worst.get('lineno')} "
              f"{worst.get('name')})")
        return 0

    baseline = load_baseline()
    errors = check(funcs, baseline)
    for e in errors:
        print(f"  [FAIL] {e}")
    if errors:
        print(f"FUNC-SIZE-FAIL: {len(errors)} нарушение(ий)")
        return 1
    actual_max = max((f["size"] for f in funcs), default=0)
    print(f"FUNC-SIZE-OK: max {actual_max} строк, в пределах потолка "
          f"({baseline.get('max_function_lines')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
