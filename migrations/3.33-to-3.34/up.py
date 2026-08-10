#!/usr/bin/env python3
"""Миграция 3.33 -> 3.34: `.ai/managed/validation/` переезжает в `.ai/managed/ai_ops_kit/validation/`.

Валидаторы стали пакетом (`ai_ops_kit.validation`), чтобы кит перестал занимать родовое имя
`validation` в site-packages. Раскладка child зеркалит раскладку кита — один источник правды, —
поэтому каталог переезжает и здесь.

Почему миграцией, а не обёртками на старом пути: обёртка означала бы, что `validation/` остаётся
в поставке child навсегда, и следующий читатель увидит два места, где живут валидаторы. Перенос
однократен и проверяем.

Идемпотентна: повторный запуск на уже перенесённом состоянии ничего не делает. Аргумент —
корень child-репозитория.
"""
import shutil
import sys
from pathlib import Path


def main(root):
    managed = Path(root) / ".ai" / "managed"
    old, new = managed / "validation", managed / "ai_ops_kit" / "validation"
    if not old.is_dir():
        print("миграция 3.33->3.34: .ai/managed/validation/ нет — переносить нечего")
        return 0
    new.parent.mkdir(parents=True, exist_ok=True)
    new.mkdir(exist_ok=True)
    moved = 0
    for src in sorted(old.rglob("*")):
        if not src.is_file():
            continue
        dst = new / src.relative_to(old)
        dst.parent.mkdir(parents=True, exist_ok=True)
        # Файл на новом месте уже положил apply managed-слоя — старый просто удаляем.
        if not dst.exists():
            shutil.move(str(src), str(dst))
        moved += 1
    shutil.rmtree(old, ignore_errors=True)
    # Пустой каталог, оставшийся от старой раскладки, — «добавленный» файл для detect_drift
    # на следующем update. Убираем сразу, чтобы дрейф не появился из ничего.
    print(f"миграция 3.33->3.34: перенесено файлов {moved}, .ai/managed/validation/ удалён")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
