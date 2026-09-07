"""Консольный вход `ai-ops` для pip/pipx — тонкий диспетчер рантайм-интентов движка.

Точка входа объявлена в `pyproject.toml -> [project.scripts]` и запускается ПРОЦЕССОМ
(console_scripts), а не импортом, поэтому у модуля легитимно ноль импортеров
(`tests/contracts/test_dormant_inventory.py -> ALLOWLIST_MODULES`, с причиной).

ЧТО ДЕЛАЕТ. Воспроизводит обёртку `./ai-ops` для интентов движка
(next/status/inbox/explain/do/run/plan/review/model/health/…), подставляя РАБОЧИЙ
каталог как каталог репозитория, — команда работает в текущем репозитории, а не в
корне установленного пакета. Контракт CLI: каталог репозитория распознаётся и
последним позиционным аргументом (см. `ai_ops_cli.main()`, «КАТАЛОГ РЕПОЗИТОРИЯ …
И В КОНЦЕ»).

ЧЕГО НЕ ДЕЛАЕТ. Жизненный цикл самого кита (init/update/doctor) сюда не входит: он
живёт в `installer/ai_ops.py`, а установщик в pip-поставку намеренно не едет
(`docs/api/public-surface.md`). Его точка входа — установщик из источника кита
(`$CLAUDE_PLUGIN_ROOT/installer/ai_ops.py` или клон-источник). Для репозитория с
уже установленным китом входом остаётся его собственная обёртка `./ai-ops`,
маршрутизирующая в пиннутую копию `.ai/managed`.
"""
from __future__ import annotations

import os
import sys


def main() -> None:
    """Entry point для `ai-ops` (см. `pyproject.toml -> [project.scripts]`)."""
    from ai_ops_kit.cli import ai_ops_cli

    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help", "help"):
        sys.exit(ai_ops_cli._main_guarded([]))

    intent, rest = argv[0], argv[1:]
    sys.exit(ai_ops_cli._main_guarded([intent, *rest, os.getcwd()]))


if __name__ == "__main__":
    main()
