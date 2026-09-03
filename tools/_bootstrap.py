#!/usr/bin/env python3
"""_bootstrap.py — shared sys.path setup for tools/ and validation/ modules."""
from __future__ import annotations
import sys
from pathlib import Path

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
            Path(__file__).resolve().parents[1])
# корень тоже в путях: из него импортируется пакетная поверхность ai_ops_kit
# R-39: в `.ai/managed` дочки байткода быть не должно (слой checksummed — свой же `.pyc` кит
# принимал за правку владельца). Свой файл записан ДО исполнения тела, поэтому убираем его явно.
if PKG.name == "managed" and PKG.parent.name == ".ai":
    sys.dont_write_bytecode = True
    _c = globals().get("__cached__")
    if _c:
        try:
            Path(_c).unlink(missing_ok=True)
            Path(_c).parent.rmdir()
        except OSError:
            pass

for _p in (str(PKG / "tools"), str(PKG / "validation"), str(PKG)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ── warn-минор перед 4.0 (deprecate-flat-tools): плоская точка входа `tools/X.py` устарела ──────
# С 4.0 плоский слой `tools/` снимается физически; запускать модули надо пакетно
# (`python3 -m ai_ops_kit...`). Предупреждаем ЗАРАНЕЕ — best-effort по sys.argv[0]: срабатывает
# ТОЛЬКО когда сам запущенный скрипт — это `tools/<name>.py` (прямой вызов), и НЕ срабатывает на
# импорт шима внутренним кодом (там argv[0] — внешняя программа). Предупреждение не блокирующее и
# не меняет код возврата: шимы в 3.x работают по-прежнему. Один раз на процесс (модуль грузится раз).
def _warn_flat_entry_point() -> None:
    argv0 = sys.argv[0] if sys.argv else ""
    if not argv0:
        return
    try:
        entry = Path(argv0).resolve()
    except (OSError, ValueError):
        return
    if entry.parent.name == "tools" and entry.suffix == ".py" and entry.stem != "_bootstrap":
        sys.stderr.write(
            f"DeprecationWarning: плоская точка входа tools/{entry.name} устарела и будет удалена "
            f"в 4.0. Запускай модуль пакетно: `python3 -m ai_ops_kit...` вместо "
            f"`python3 .../tools/{entry.name}` (соответствие имён — в MIGRATION_GUIDE_4.0.md). "
            f"Слой совместимости tools/ снимается в следующем мажоре.\n")


_warn_flat_entry_point()
