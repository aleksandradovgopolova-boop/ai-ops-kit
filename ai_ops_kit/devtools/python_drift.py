#!/usr/bin/env python3
"""python_drift.py — предупредить о расхождении версии Python local↔CI ДО пуша.

ЗАЧЕМ. Локальный цикл идёт на том интерпретаторе, которым реально работает человек (на машине
владельца — Python 3.14), а блокирующий CI считает пол `requires-python` (3.12). Локальный
зелёный на 3.14 НЕ гарантирует зелёный CI на 3.12: поведение, доступное только в 3.13+/3.14,
проходит локально и краснеет в CI — это лишний круг local-green → CI-red (issue #1378, правило
памяти проекта «разница версий не должна рождать повторы»). Узнать о расхождении надо ДО пуша,
рядом с остальными предупреждениями честности окружения (`warn-path-belt.sh`), а не раундом CI.

ПОЧЕМУ ТОЛЬКО ПРЕДУПРЕЖДЕНИЕ, А НЕ ОТКАЗ. Правило владельца первого класса: разница версий НЕ
должна МЕШАТЬ разработке. Запускать локально на 3.12 — рекомендация, а не условие: человек вправе
вести цикл на своём интерпретаторе. Поэтому проверка аддитивна и неблокирующая — `main` всегда
возвращает 0, а вызывающий скрипт зовёт её через `|| true`. Понижать пол или ломать окружения
проверка не вправе (границы issue #1378).

ПОЛ — ОДИН ИСТОЧНИК. Значение пола не зашивается здесь второй раз, а читается из
`requires-python` в `pyproject.toml` через `validate_python_compat.declared_floor` — тот же
разбор, что использует compat-гейт. Меняется декларация — меняется и это предупреждение, без
правок в двух местах.

ГРАНИЦА. Проверка сравнивает ТОЛЬКО minor-версию (major у кита один — 3). Расхождение в minor —
это и есть класс «3.14-only синтаксис/stdlib зелёный локально, красный на 3.12». Patch-версии
(3.12.1 vs 3.12.7) к этому классу не относятся и не предупреждаются.

CLI:  python_drift.py [--json]      печатает отчёт; код возврата ВСЕГДА 0 (advisory).
"""
from __future__ import annotations

import json
import sys

from ai_ops_kit.validation.validate_python_compat import declared_floor


def local_version(version_info=None) -> tuple[int, int]:
    """(major, minor) локального интерпретатора. Параметр — шов для теста: он подаёт версию явно,
    чтобы проверка не зависела от того, каким Python запущен сам тест."""
    vi = version_info if version_info is not None else sys.version_info
    return (int(vi[0]), int(vi[1]))


def assess(local=None, floor=None, pkg=None) -> dict:
    """Read-only снимок: расходится ли minor локального интерпретатора с полом CI.

    `local` и `floor` можно передать явно ((major, minor)-кортежи) — так тест проверяет РАЗБОР
    расхождения, а не версию хоста, на котором запущен. По умолчанию local берётся из текущего
    интерпретатора, floor — из pyproject (`declared_floor`)."""
    loc = local_version(local)
    if floor is not None:
        flr = floor
    # pkg=None означает «не задан» -> пусть declared_floor применит свой корень (PKG); передавать
    # None внутрь нельзя, он собирает путь pkg / "pyproject.toml".
    elif pkg is not None:
        flr = declared_floor(pkg)
    else:
        flr = declared_floor()
    drift = loc[1] != flr[1]
    return {
        "kind": "PythonDrift",
        "status": "drift" if drift else "aligned",
        "local": list(loc),
        "ci_floor": list(flr),
        "newer": loc[1] > flr[1],
    }


def warning_line(report: dict) -> str:
    """Строка для локального цикла. Пол назван явно, и сказано, что делать (прогнать на полу),
    а не только что не так. Пустая строка, если расхождения нет."""
    if report["status"] != "drift":
        return ""
    loc = f"{report['local'][0]}.{report['local'][1]}"
    flr = f"{report['ci_floor'][0]}.{report['ci_floor'][1]}"
    direction = ("новее" if report["newer"] else "старше")
    return (
        f"ВНИМАНИЕ, версия Python: локальный цикл идёт на {loc}, а блокирующий CI считает пол "
        f"{flr} ({loc} {direction} пола).\n"
        f"  Зелёное на {loc} НЕ гарантирует зелёное на {flr}: поведение, доступное только в {loc}, "
        f"пройдёт здесь и покраснеет в CI — лишний круг local-green → CI-red.\n"
        f"  Перед пушем прогоните контур на полу CI, например: "
        f"PYTHON=$(command -v python{flr} || echo python{flr}) scripts/check-full.sh\n"
        f"  Это предупреждение, НЕ отказ: разница версий не блокирует локальную работу."
    )


def main(argv) -> int:
    rep = assess()
    if "--json" in argv:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        line = warning_line(rep)
        if line:
            # В stderr и с пустой строкой вокруг — ровно как warn-path-belt.sh: предупреждение
            # должно быть видно среди вывода цикла, но не притворяться результатом прогона.
            sys.stderr.write("\n" + line + "\n\n")
    # ВСЕГДА 0: проверка advisory, она не вправе ронять локальный цикл (правило владельца).
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
