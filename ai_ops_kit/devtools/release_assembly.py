#!/usr/bin/env python3
"""release_assembly.py — ОСОЗНАННАЯ сборка релиза по вехе или расписанию, а не реактивно.

ПОВОД (исход `releases_are_assembled_by_milestone_or_schedule_not_reactively`). `release_bump.py`
поднимает версию, когда вызывающий уже РЕШИЛ выпускать, — это конец процесса. Но само решение «что
и когда собрать в релиз» до сих пор было реактивным: каждый мерж копил newsfragments, и релиз
случался, когда кто-то вспоминал бампнуть. Здесь сборка становится ОСОЗНАННОЙ: релиз собирается по
явному триггеру — вехе или расписанию, — и helper НАЗЫВАЕТ состав (что накопилось, сгруппировано по
типу), не бампая и не выпуская. Без триггера сборки нет: реактивного «каждый мерж = релиз» тут нет.

Это dev-инструмент кита (пакет `devtools/`), в дочку он НЕ едет и чужой репозиторий не трогает.

Использование:
  release_assembly.py --milestone "<веха>"    # что войдёт в релиз этой вехи
  release_assembly.py --schedule "<дата/период>"  # что накопилось к плановой дате
  release_assembly.py --pending                # только перечислить накопленное (без триггера)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
           Path(__file__).resolve().parents[2])


def pending_fragments(root: Path) -> list:
    """Накопленные newsfragments — что войдёт в следующий релиз. -> [{slug, category, name}].

    Категория — предпоследнее расширение имени (`<slug>.<feat|fix|chore|...>.md`), как у towncrier.
    README.md не в счёт (это конфиг каталога, а не запись релиза).
    """
    d = root / "newsfragments"
    out = []
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.md")):
        if p.name == "README.md":
            continue
        parts = p.name.split(".")
        cat = parts[-2] if len(parts) >= 3 else "misc"
        out.append({"slug": ".".join(parts[:-2]) or p.stem, "category": cat, "name": p.name})
    return out


def assemble(root: Path, *, milestone: str = "", schedule: str = "") -> dict:
    """Собрать релиз ОСОЗНАННО — по вехе ИЛИ расписанию. Ничего не бампает и не выпускает. -> dict.

    {"trigger", "by_category", "count", "ready": bool, "reason"}. Без явного триггера (ни вехи, ни
    расписания) сборка НЕ готова — это и есть отказ от реактивной сборки: `ready=False` с причиной.
    """
    if not milestone and not schedule:
        return {"trigger": "", "by_category": {}, "count": 0, "ready": False,
                "reason": ("сборка релиза требует явного триггера: --milestone <веха> или "
                           "--schedule <дата/период>. Реактивной сборки (каждый мерж = релиз) нет")}
    trigger = f"веха:{milestone}" if milestone else f"расписание:{schedule}"
    frags = pending_fragments(root)
    by_cat: dict = {}
    for f in frags:
        by_cat.setdefault(f["category"], []).append(f["slug"])
    if not frags:
        return {"trigger": trigger, "by_category": {}, "count": 0, "ready": False,
                "reason": f"по триггеру «{trigger}» собирать нечего — накопленных newsfragments нет"}
    return {"trigger": trigger, "by_category": by_cat, "count": len(frags), "ready": True,
            "reason": f"по триггеру «{trigger}» к сборке готово изменений: {len(frags)}"}


def main(argv) -> int:
    ap = argparse.ArgumentParser(prog="release_assembly.py")
    ap.add_argument("--milestone", default="", help="триггер сборки: веха")
    ap.add_argument("--schedule", default="", help="триггер сборки: дата/период")
    ap.add_argument("--pending", action="store_true", help="только перечислить накопленное")
    ap.add_argument("--root", default=str(PKG))
    a = ap.parse_args(argv[1:])
    root = Path(a.root)
    if a.pending:
        frags = pending_fragments(root)
        print(f"НАКОПЛЕНО newsfragments: {len(frags)}")
        for f in frags:
            print(f"  [{f['category']}] {f['slug']}")
        return 0
    if a.milestone and a.schedule:
        print("укажите ОДИН триггер: --milestone ИЛИ --schedule, не оба")
        return 1
    res = assemble(root, milestone=a.milestone, schedule=a.schedule)
    print(res["reason"])
    for cat, slugs in sorted(res["by_category"].items()):
        print(f"  {cat} ({len(slugs)}): " + ", ".join(slugs))
    if res["ready"]:
        print(f"Дальше: осознанно выпустить состав через `release_bump.py <X.Y.Z> --title …`.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
