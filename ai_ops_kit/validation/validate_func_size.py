#!/usr/bin/env python3
"""Ратчет максимального размера функции в ai_ops_kit/.

AST-обход всех .py файлов в каждом объявленном каталоге, для каждой function/async function
считает end_lineno - lineno + 1. У каждого каталога (scope) свой потолок; проверка сверяет
максимум каталога с его потолком и возвращает 0, если ни один scope не превышен, 1 — если
хотя бы один превышен.

Ратчет ходит ТОЛЬКО ВНИЗ: снижение потолка обязано быть записано в baseline-файл.
Превышение — красный сигнал: новая god-функция или рефакторинг не завершён.

Scopes перечислены в packages/func-size-baseline.yaml (ключ `scopes`). Раньше ратчет стерёг
только engine/, а god-функции ВНЕ него росли свободно; теперь потолок есть у каждого
объявленного каталога (engine/cli/planning/providers/validation).

Использование:
  validate_func_size.py              # проверить все scope против baseline
  validate_func_size.py --report     # напечатать топ-10 по каждому scope без проверки
  validate_func_size.py --baseline   # обновить baseline текущим замером всех scope

Возврат 0 — все scope в пределах потолка, 1 — хотя бы один превышен.
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


def iter_scopes(baseline: dict, pkg_root: Path = PKG) -> list[dict]:
    """Список scope'ов из baseline с разрешённым каталогом.

    Каждый элемент: {'path': относительный путь, 'dir': абсолютный Path, 'spec': dict scope}.
    Порядок сохраняется как в baseline.
    """
    scopes = []
    for spec in baseline.get("scopes", []) or []:
        rel = spec.get("path", "")
        scopes.append({"path": rel, "dir": pkg_root / rel, "spec": spec})
    return scopes


def check_all(baseline: dict, pkg_root: Path = PKG) -> list[str]:
    """Сверить максимум каждого scope с его потолком. Возвращает список ошибок (пустой = ОК).

    Ошибки каждого scope префиксуются его путём. Отсутствие секции `scopes` — сама ошибка:
    без неё ратчет ничего не стережёт.
    """
    scopes = iter_scopes(baseline, pkg_root)
    if not scopes:
        return ["ратчет func-size: в baseline нет секции scopes — стеречь нечего"]
    errors = []
    for scope in scopes:
        funcs = measure_functions(scope["dir"])
        for err in check(funcs, scope["spec"]):
            errors.append(f"[{scope['path']}] {err}")
    return errors


def render_report(funcs: list[dict], n: int = 10) -> str:
    """Человекочитаемый отчёт: топ-N крупнейших функций."""
    lines = [f"Всего функций: {len(funcs)}"]
    for f in top_n(funcs, n):
        lines.append(f"  {f['size']:5d}  {f['file']}:{f['lineno']}  {f['name']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv[1:])
    baseline = load_baseline()
    scopes = iter_scopes(baseline)

    if "--report" in argv:
        for scope in scopes:
            funcs = measure_functions(scope["dir"])
            print(f"== {scope['path']} ==")
            print(render_report(funcs))
        return 0

    if "--baseline" in argv:
        new_scopes = []
        for scope in scopes:
            funcs = measure_functions(scope["dir"])
            actual_max = max((f["size"] for f in funcs), default=0)
            worst = max(funcs, key=lambda f: f["size"]) if funcs else {}
            new_scopes.append({
                "path": scope["path"],
                "max_function_lines": actual_max,
                "max_function": worst.get("name", ""),
                "max_function_file": worst.get("file", ""),
                "max_function_lineno": worst.get("lineno", 0),
            })
            print(f"  {scope['path']}: max={actual_max} "
                  f"({worst.get('file')}:{worst.get('lineno')} {worst.get('name')})")
        data = {"schema_version": 2, "kind": "func-size-ratchet", "scopes": new_scopes}
        BASELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE_FILE.write_text(
            yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
        print("Baseline обновлён.")
        return 0

    errors = check_all(baseline)
    for e in errors:
        print(f"  [FAIL] {e}")
    if errors:
        print(f"FUNC-SIZE-FAIL: {len(errors)} нарушение(ий)")
        return 1
    for scope in scopes:
        funcs = measure_functions(scope["dir"])
        actual_max = max((f["size"] for f in funcs), default=0)
        print(f"FUNC-SIZE-OK: {scope['path']} max {actual_max} строк, в пределах потолка "
              f"({scope['spec'].get('max_function_lines')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
