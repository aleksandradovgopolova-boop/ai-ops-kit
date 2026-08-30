#!/usr/bin/env python3
"""Миграция policy v1 -> v2: вынести режим `enforcement` в POLICY.yaml дочки.

Текстовая правка (НЕ yaml round-trip: он потерял бы комментарии владельца). Аргумент — путь
экземпляра `.ai-ops/POLICY.yaml`. exit 0 = успех. Идемпотентна: повторный запуск не дублирует поле.
"""
from __future__ import annotations

import re
import sys

_COMMENT = ("# enforcement (v2): observe — считать и записывать решение политики, но не блокировать "
            "доставку; block — require_approval без одобрения реально блокирует. Значения: observe | block.\n")
_FIELD = "enforcement: observe\n"


def migrate(path: str) -> int:
    text = open(path, encoding="utf-8").read()
    # 1) поднять версию шаблона до 2 (ровно одно верхнеуровневое поле)
    text = re.sub(r"(?m)^template_version:\s*\d+\s*$", "template_version: 2", text, count=1)
    # 2) добавить enforcement, если его ещё нет (идемпотентность)
    if not re.search(r"(?m)^enforcement:\s*", text):
        lines = text.splitlines(keepends=True)
        out, inserted = [], False
        for ln in lines:
            out.append(ln)
            if not inserted and re.match(r"^schema_version:", ln):
                out.append("\n")
                out.append(_COMMENT)
                out.append(_FIELD)
                inserted = True
        if not inserted:                       # нет schema_version — кладём в начало, не теряем поле
            out = [_COMMENT, _FIELD] + out
        text = "".join(out)
    open(path, "w", encoding="utf-8").write(text)
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: up.py <path-to-POLICY.yaml>", file=sys.stderr)
        sys.exit(2)
    sys.exit(migrate(sys.argv[1]))
