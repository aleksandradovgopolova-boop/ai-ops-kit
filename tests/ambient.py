"""Запуск подпроцесса БЕЗ ambient-импорта кита — общий инструмент проб (19.08.2026).

ЗАЧЕМ. Пять проверок на машине разработки красные ВСЕГДА при зелёном CI, и три из пяти — по одной
причине: `PYTHONPATH` они чистят, а editable-установка кита (`__editable__.ai_ops_kit-*.pth` в
site-packages venv) ставит meta-path finder, который отдаёт `ai_ops_kit` и плоские модули ЛЮБОМУ
процессу этого интерпретатора. Поэтому проба, которая копирует репозиторий, ломает копию и
запускает её, читает НЕ СВОЮ копию, а рабочий клон — и «не заметила порчу», потому что портила не
то дерево. Это тот же класс, что «проба обязана дойти до дефекта».

ПОЧЕМУ `-S`, А НЕ ЧИСТКА ПЕРЕМЕННЫХ. Пояс живёт не в переменной окружения, а в `.pth`-файле
site-packages: `PYTHONPATH=`, `-E`, `-I` его не снимают, потому что все они не отменяют обработку
site. `-S` отключает `site` целиком, и finder просто не устанавливается. Плата — вместе с site
исчезают и сторонние пакеты, поэтому нужные отдаются каталогом СИМЛИНКОВ: сам site-packages
передать нельзя, он вернул бы пояс обратно.

ПОЧЕМУ НЕ СНЯТЬ EDITABLE-УСТАНОВКУ. Это машина владельца и её настройка (записано в плане,
`local-run-must-mirror-ci`). Чинить надо пробу, которая мерит не своё дерево, а не чужой venv.
"""
from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Сторонние пакеты, без которых валидаторы кита не стартуют. Список ЯВНЫЙ: молча подкладывать
# «всё, что найдём» значило бы вернуть тот же ambient другим путём.
THIRD_PARTY = ("yaml",)


def deps_dir(base: Path) -> Path:
    """Каталог с симлинками на сторонние пакеты — единственное, что видно при `-S`."""
    deps = Path(base) / "deps-no-ambient"
    deps.mkdir(parents=True, exist_ok=True)
    for mod in THIRD_PARTY:
        src = Path(importlib.import_module(mod).__file__).resolve().parent
        dst = deps / src.name
        if dst.exists():
            continue
        try:
            os.symlink(src, dst, target_is_directory=True)
        except (OSError, NotImplementedError):        # Windows без прав на симлинки
            shutil.copytree(src, dst)
    return deps


def env(base: Path, **extra) -> dict:
    """Окружение без ambient-кита: без PYTHONPATH репозитория, со своими зависимостями."""
    e = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    e["PYTHONPATH"] = str(deps_dir(base))
    e["PYTHONDONTWRITEBYTECODE"] = "1"
    e.update({k: str(v) for k, v in extra.items()})
    return e


def run(args, cwd, base: Path, timeout=300, text=True, **extra_env):
    """Запустить python-скрипт так, как его видит чужой репозиторий: без пояса и без PYTHONPATH."""
    return subprocess.run([sys.executable, "-S", *[str(a) for a in args]],
                          cwd=str(cwd), env=env(base, **extra_env),
                          capture_output=True, text=text, timeout=timeout)


def ambient_kit_is_importable() -> bool:
    """Есть ли пояс вообще. Нужен КОНТРОЛЮ: без пояса пробы зелёные и без этой правки, и тогда
    измерение ничего не доказывает — об этом надо сказать, а не считать успехом."""
    r = subprocess.run([sys.executable, "-c", "import ai_ops_kit, sys; print(ai_ops_kit.__file__)"],
                       cwd="/", env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"},
                       capture_output=True, text=True)
    return r.returncode == 0
