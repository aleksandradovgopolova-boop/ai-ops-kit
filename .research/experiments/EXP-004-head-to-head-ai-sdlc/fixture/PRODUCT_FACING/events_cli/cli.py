"""events-cli: команда list-events печатает события из events.json.

СТАРТОВОЕ состояние фикстуры: флага --since ЕЩЁ НЕТ — его добавляет задача EXP-004.
Модуль намеренно простой и на stdlib. events.json ищется рядом с корнем репозитория
(на уровень выше пакета), чтобы прогон из корня работал без установки.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent.parent / "events.json"


def load_events(path: Path = DATA_PATH) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def format_event(event: dict) -> str:
    return f"{event['id']}\t{event['date']}\t{event['title']}"


def cmd_list_events(args: argparse.Namespace) -> int:
    events = load_events()
    # СТАРТ: фильтров нет — печатаем всё как есть, в исходном порядке.
    for event in events:
        print(format_event(event))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="events-cli")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list-events", help="показать события из events.json")
    p_list.set_defaults(func=cmd_list_events)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
