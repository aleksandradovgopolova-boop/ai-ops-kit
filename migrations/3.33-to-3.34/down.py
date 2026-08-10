#!/usr/bin/env python3
"""Откат 3.34 -> 3.33: валидаторы возвращаются в `.ai/managed/validation/`.

Обратима: перенос каталога не теряет данных, поэтому честный down существует и делает ровно
обратное up. Аргумент — корень child-репозитория.
"""
import shutil
import sys
from pathlib import Path


def main(root):
    managed = Path(root) / ".ai" / "managed"
    new, old = managed / "ai_ops_kit" / "validation", managed / "validation"
    if not new.is_dir():
        print("откат 3.34->3.33: ai_ops_kit/validation/ нет — возвращать нечего")
        return 0
    old.mkdir(parents=True, exist_ok=True)
    for src in sorted(new.rglob("*")):
        if not src.is_file():
            continue
        dst = old / src.relative_to(new)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists():
            shutil.move(str(src), str(dst))
    shutil.rmtree(new, ignore_errors=True)
    print("откат 3.34->3.33: валидаторы возвращены в .ai/managed/validation/")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
