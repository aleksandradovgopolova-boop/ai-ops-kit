#!/usr/bin/env python3
"""CLI-обёртка маршрутизатора (точка входа, слой `entrypoints`).

Библиотечный route() живёт в ai_ops_kit/shared/ai_route.py (foundation). Эта обёртка печатает
решение человеку.

Использование:
  python -m ai_ops_kit.devtools.ai_route_cli '<json-инпуты>'   — вывести решение (JSON)
  python -m ai_ops_kit.devtools.ai_route_cli                   — показать справку модуля
"""
from __future__ import annotations

import json
import sys

from ai_ops_kit.shared import ai_route


def main(argv):
    if len(argv) > 1:
        inp = json.loads(argv[1])
        print(json.dumps(ai_route.route(inp), ensure_ascii=False, indent=2))
        return 0
    print(ai_route.__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
