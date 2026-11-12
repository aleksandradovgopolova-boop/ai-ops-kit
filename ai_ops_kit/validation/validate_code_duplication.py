#!/usr/bin/env python3
"""Структурные дубли функций в ПРОЕКТЕ: CODE-003 исполняется у дочки, а не только у кита (#1512).

ЗАЧЕМ. Статья «без дублирования» едет в проект с конституцией, а проверял её только CI кита: в
проекте статья была, проверить её было нечем. Сценарий, ради которого это сделано, — «одна функция
в четырёх версиях»: агент генерирует быстрее, чем команда замечает повтор.

КАК У КИТА. Существующие группы замораживаются базой `.ai/project/code-duplication-baseline.yaml`
(её принимает владелец — коммитом), НОВАЯ группа сверх базы — находка с адресами. Убранный дубль
сокращает базу (ратчет вниз). Ядро то же, что у ратчета кита: `ai_ops_kit.checks.code_duplication`.

ЧЕСТНОСТЬ.
  * Нет Python-файлов — «НЕ ПРОВЕРЯЕТСЯ» и код 2, а не «дублей нет».
  * Нет базы — не «всё хорошо»: найденные группы перечислены, код 1 и команда заморозки.
  * Перезаморозка не происходит сама: существующую базу `--write-baseline` перезаписывает только
    с `--force` — иначе рост можно было бы «отмыть» пересборкой, и это видно в диффе файла.
В child-CI проверка advisory (`templates/ci/ai-ops-duplicates.yml`): проект не краснеет в день
обновления.

  validate_code_duplication.py [--child-root .] [--baseline PATH] [--write-baseline [--force]] [--json]
Возврат: 0 — новых групп нет; 1 — новые группы или база не принята; 2 — не проверяется/не исполнено.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:                                          # двурежимный, как соседние валидаторы
    from ai_ops_kit.validation import _bootstrap   # noqa: F401 — импорт пакетом (после pip install)
except ImportError:                                # запуск скриптом: корня на пути ещё нет,
    import _bootstrap                              # noqa: F401 — и положить его может только он сам

from ai_ops_kit.checks import code_duplication as core  # noqa: E402

SHOWN = 20
BASELINE_HEADER = (
    "code-duplication-baseline.yaml — замороженные структурные дубли функций проекта (CODE-003).",
    "",
    "Перечисленные группы — известный долг; НОВАЯ группа сверх списка — находка проверки дублей кита.",
    "Убрали дубль — пересоберите базу (`--write-baseline --force`), список вправе только сокращаться.",
    "Создаётся: python3 .ai/managed/ai_ops_kit/validation/validate_code_duplication.py --write-baseline",
)


def _command(root: Path) -> str:
    return f"python3 .ai/managed/ai_ops_kit/validation/validate_code_duplication.py --child-root {root} --write-baseline"


def _coverage_note(scan: dict) -> str:
    checked = ", ".join(f"{k} — {v} файлов" for k, v in sorted(scan["checked"].items()))
    skipped = ", ".join(f"{k} — {v}" for k, v in sorted(scan["not_checked"].items()))
    note = f"проверено: {checked}" if checked else "проверено: ничего"
    if scan.get("unread"):
        shown = ", ".join(scan["unread"][:5]) + (" …" if len(scan["unread"]) > 5 else "")
        note += f"; НЕ прочитано (кодировка/синтаксис) Python — {len(scan['unread'])}: {shown}"
    return note + (f"; НЕ проверяется (детектор читает только Python): {skipped}" if skipped else "")


def evaluate(root, baseline_path) -> dict:
    """Вердикт без печати и записи. -> {code, status, coverage, groups, new, frozen, stale}."""
    root = Path(root)
    scan = core.scan_project(root)
    result = {"coverage": _coverage_note(scan), "groups": scan["groups"], "new": [], "frozen": 0,
              "stale": []}
    if not scan["checked"]:
        return {**result, "code": 2, "status": "not_checked"}
    try:
        baseline = core.load_baseline(baseline_path)
    except core.BaselineUnreadable as exc:
        return {**result, "code": 2, "status": "bad_baseline", "problem": str(exc)}
    if baseline is None:
        return {**result, "code": 1 if scan["groups"] else 0, "new": scan["groups"],
                "status": "no_baseline" if scan["groups"] else "clean"}
    verdict = core.compare(scan["groups"], baseline)
    return {**result, **verdict, "code": 1 if verdict["new"] else 0,
            "status": "new_groups" if verdict["new"] else "ok"}


def _lines(result: dict, root: Path, baseline_rel: str) -> list[str]:
    status = result["status"]
    if status == "bad_baseline":
        return [f"CODE-DUPLICATION: база не читается ({result['problem']}) — сравнить не с чем; "
                f"почините файл или пересоберите: {_command(root)} --force", f"  {result['coverage']}"]
    if status == "not_checked":
        return ["CODE-DUPLICATION: НЕ ПРОВЕРЯЕТСЯ — ни одного прочитанного Python-файла; это не «дублей нет».",
                f"  {result['coverage']}"]
    head = {
        "no_baseline": f"CODE-DUPLICATION: база не принята — найдено групп дублей: {len(result['new'])}. "
                       f"Заморозить существующие: {_command(root)} и закоммитить {baseline_rel}.",
        "new_groups": f"CODE-DUPLICATION: новых групп дублей сверх базы: {len(result['new'])} "
                      f"(заморожено {result['frozen']}). Вынесите общую функцию вместо копии.",
        "clean": "CODE-DUPLICATION-OK: структурных дублей функций нет.",
        "ok": f"CODE-DUPLICATION-OK: новых групп нет (заморожено {result['frozen']}).",
    }[status]
    lines = [head, f"  {result['coverage']}"]
    lines += [f"  - {', '.join(g['locations'])}" for g in result["new"][:SHOWN]]
    if len(result["new"]) > SHOWN:
        lines.append(f"  … и ещё {len(result['new']) - SHOWN}")
    if result["stale"]:
        lines.append(f"  убрано групп из базы: {len(result['stale'])} — сократите базу: "
                     f"{_command(root)} --force")
    return lines


def write_baseline(root: Path, baseline: Path, force: bool) -> tuple[int, str]:
    if baseline.is_file() and not force:
        return 1, (f"база {baseline} уже есть — перезаморозка только осознанно: добавьте --force "
                   "(изменение будет видно в диффе)")
    scan = core.scan_project(root)
    if not scan["checked"]:
        return 2, "НЕ ПРОВЕРЯЕТСЯ: ни одного прочитанного Python-файла — замораживать нечего"
    baseline.parent.mkdir(parents=True, exist_ok=True)
    baseline.write_text(core.render_baseline(scan["groups"], ".", BASELINE_HEADER), encoding="utf-8")
    return 0, f"OK: база записана ({len(scan['groups'])} групп) — {baseline}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="validate_code_duplication.py", description=__doc__.splitlines()[0])
    ap.add_argument("--child-root", default=".")
    ap.add_argument("--baseline", default=None, help=f"по умолчанию {core.CHILD_BASELINE}")
    ap.add_argument("--write-baseline", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--json", action="store_true")
    ns = ap.parse_args(argv)
    root = Path(ns.child_root)
    baseline_rel = ns.baseline or core.CHILD_BASELINE
    baseline = Path(baseline_rel) if Path(baseline_rel).is_absolute() else root / baseline_rel
    if ns.write_baseline:
        code, message = write_baseline(root, baseline, ns.force)
        print(message)
        return code
    result = evaluate(root, baseline)
    if ns.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("\n".join(_lines(result, root, baseline_rel)))
    return result["code"]


if __name__ == "__main__":
    sys.exit(main())
