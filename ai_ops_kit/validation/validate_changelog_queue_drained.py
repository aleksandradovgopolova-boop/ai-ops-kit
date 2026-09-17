#!/usr/bin/env python3
"""Гейт «на релизе очередь заявлений пуста» (аудит A2, 17.09.2026).

towncrier собирает CHANGELOG.md из newsfragments/, но релиз кита долго НЕ звал `build`, и очередь
копилась сотнями непогашенных фрагментов — «дисциплина заявлений подтекала там, где декларируется».
Дренаж впаян в релиз (`devtools/release_bump.py` сгребает очередь на бампе версии), а этот валидатор
ДОКАЗЫВАЕТ результат: на релизе (флаг `--release`) каталог newsfragments/ обязан быть пуст (только
README.md). Иначе — джоба краснеет и тег не создаётся, то есть обещание стало проверяемым, а не
пожеланием. Механизм НЕ дублирует towncrier: он ничего не собирает и не удаляет, только СВЕРЯЕТ
результат сборки — как соседние релизные валидаторы сверяют версию, а не бампают её.

Без `--release` — совет: печатает, сколько фрагментов накоплено к следующему релизу, и выходит 0.
Между релизами непустая очередь — норма (каждый PR добавляет заявление), а не нарушение; краснить
её вне релиза значило бы блокировать обычную работу.

Использование:
  validate_changelog_queue_drained.py [--release] [--root .]
    без --release: совет, всегда код 0;
    с --release:   непустая очередь -> код 1 (релиз краснеет), пустая -> код 0.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
           Path(__file__).resolve().parents[1])


def pending(root: Path) -> list:
    """Накопленные newsfragments (всё, кроме README.md) — очередь заявлений к следующему релизу."""
    d = Path(root) / "newsfragments"
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.glob("*.md") if p.name != "README.md")


def check(root, release: bool = False) -> list:
    """-> список нарушений. В release-режиме непустая очередь — нарушение; вне релиза всегда []."""
    frags = pending(Path(root))
    if release and frags:
        head = ", ".join(frags[:5]) + ("…" if len(frags) > 5 else "")
        return [f"на релизе очередь newsfragments непуста ({len(frags)}): {head}. Релиз обязан "
                f"слить очередь в CHANGELOG (towncrier build через release_bump) и очистить её"]
    return []


def main(argv) -> int:
    ap = argparse.ArgumentParser(prog="validate_changelog_queue_drained.py")
    ap.add_argument("--release", action="store_true",
                    help="режим гейта: непустая очередь -> код 1 (для release.yml)")
    ap.add_argument("--root", default=str(PKG))
    a = ap.parse_args(argv)
    root = Path(a.root)
    errs = check(root, release=a.release)
    if errs:
        print("CHANGELOG-QUEUE: " + errs[0])
        return 1
    frags = pending(root)
    if a.release:
        print("CHANGELOG-QUEUE-DRAINED-OK: очередь newsfragments пуста на релизе.")
    else:
        print(f"CHANGELOG-QUEUE: к следующему релизу накоплено фрагментов: {len(frags)} "
              f"(совет, не гейт; гасятся на ближайшем релизе).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
