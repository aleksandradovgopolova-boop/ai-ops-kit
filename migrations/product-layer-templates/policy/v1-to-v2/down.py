#!/usr/bin/env python3
"""Откат policy v2 -> v1: убрать поле `enforcement` и вернуть версию шаблона к 1.

Текстовая правка (симметрично up.py). Аргумент — путь экземпляра `.ai-ops/POLICY.yaml`.
exit 0 = успех. Идемпотентна: если поля нет — просто вернёт версию.
"""
from __future__ import annotations

import re
import sys


def rollback(path: str) -> int:
    lines = open(path, encoding="utf-8").read().splitlines(keepends=True)
    out = []
    for ln in lines:
        if re.match(r"^enforcement:\s*", ln):
            continue                                   # убрать само поле
        if ln.lstrip().startswith("# enforcement (v2):"):
            continue                                   # и его пояснение
        out.append(ln)
    text = "".join(out)
    # схлопнуть возможную пустую строку, оставшуюся от вставки, не трогая остальное
    text = re.sub(r"(?m)^schema_version:(.*)\n\n(?=\S)", r"schema_version:\1\n", text, count=1)
    text = re.sub(r"(?m)^template_version:\s*\d+\s*$", "template_version: 1", text, count=1)
    open(path, "w", encoding="utf-8").write(text)
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: down.py <path-to-POLICY.yaml>", file=sys.stderr)
        sys.exit(2)
    sys.exit(rollback(sys.argv[1]))
