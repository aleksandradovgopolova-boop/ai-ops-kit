"""sandbox-is-never-said-without-its-limit: слово «песочница»/«sandbox» в пользовательском тексте
обязано сопровождаться названной границей изоляции.

ГРАНИЦА НАЗВАНА РЕВЬЮ ТОЧНО: `policy enforcement != security isolation`. Брокер управляет
операцией, путём, областью записи, разрушительными командами и окружением — но shell остаётся
best-effort, а сеть, чтение чужих файлов, запись вне дерева и изоляция ресурсов не закрыты.

РАБОТА НЕ ПРО ИЗОЛЯЦИЮ, А ПРО СЛОВО. Риск в том, что человек прочитает «песочница» и решит,
что агент изолирован. Он управляем, но не изолирован.
"""
from __future__ import annotations

import re
from pathlib import Path

# Слова, которые требуют названной границы изоляции в том же абзаце/строке.
_SANDBOX_WORDS = re.compile(r"\b(sandbox|песочниц[ауеы])\b", re.IGNORECASE)
# Фразы, которые называют границу (достаточно одной в том же блоке текста).
_BOUNDARY_PHRASES = re.compile(
    r"(не.*изоляц|not.*isolat|best.effort|policy.enforcement|управляем.*но.*не"
    r"|границ[аеы].*изоляц|boundary|не.*безопасн|not.*secur|условн[аеы]|эмуляци"
    r"|симуляци|ограничен[аеы]|частичн[аеы])",
    re.IGNORECASE,
)


def check(data: dict | None) -> list[str]:
    """Проверка текста на употребление «sandbox» без границы. data = {"text": str, "source": str}."""
    if not isinstance(data, dict):
        return ["ожидается dict с ключами 'text' и 'source'"]
    text = data.get("text") or ""
    source = data.get("source") or "<unknown>"
    if not isinstance(text, str):
        return [f"'text' должен быть строкой, получен {type(text).__name__}"]

    errors = []
    # Проверяем построчно: если строка содержит "sandbox" но не содержит фразу-границу — ошибка.
    for i, line in enumerate(text.splitlines(), 1):
        if _SANDBOX_WORDS.search(line) and not _BOUNDARY_PHRASES.search(line):
            errors.append(
                f"{source}:{i}: «sandbox»/«песочница» без названной границы изоляции — "
                f"читатель может решить, что агент изолирован (он управляем, но не изолирован). "
                f"Добавьте: «policy enforcement, не security isolation» или аналог."
            )
    return errors


if __name__ == "__main__":
    import json
    import sys

    # CLI: проверить файл или stdin.
    if len(sys.argv) > 1:
        p = Path(sys.argv[1])
        text = p.read_text(encoding="utf-8")
        source = str(p)
    else:
        text = sys.stdin.read()
        source = "<stdin>"
    errs = check({"text": text, "source": source})
    if errs:
        for e in errs:
            print(e, file=sys.stderr)
        sys.exit(1)
    print("SANDBOX-BOUNDARY-OK")
