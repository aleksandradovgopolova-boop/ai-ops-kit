"""Общие хелперы для разрезанного набора тестов брокера (`test_tool_broker*.py`).

Модуль с префиксом `_` — pytest его НЕ собирает. Держит один разделяемый помощник `_git_p0`,
который нужен и P0-shell-набору (`test_tool_broker_shell.py`), и self-host-набору
(`test_tool_broker.py`) для поднятия одноразовых git-репозиториев в фикстурах. Тела тестов при
разрезе не менялись — это чистый вынос дублирующегося кода фикстур.
"""
from __future__ import annotations

import subprocess


def _git_p0(root, *args):
    """`git -C <root> <args>` без вывода — для сборки одноразовых репозиториев в фикстурах."""
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=30)
