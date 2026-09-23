"""Что в файле НЕ является кодом: проза и комментарии.

Сателлит `security_scan` (фасад импортирует отсюда `PROSE_SUFFIXES` и `blank_comments`). Появился
не из вкуса к дроблению: после того как комментарии перестали считаться кодом (#1112), сам сканер
перешагнул порог монолита в 700 строк — ратчет размера модуля сказал об этом до слияния.

Своей точки входа у сателлита нет осознанно: он обслуживает сканер, а не запускается сам.
"""
from __future__ import annotations

# Проза — не исполняемый код. `dangerouslySetInnerHTML`, упомянутый в CHANGELOG, ничего не
# исполняет; флаг на нём — не осторожность, а шум.
PROSE_SUFFIXES = (".md", ".rst", ".txt")

# КОММЕНТАРИЙ — ТОЖЕ ПРОЗА, а отличается от прозы только тем, что лежит внутри файла с кодом.
# Замер 23.09.2026 (#1112): 6 флагов `react_dangerous_html` из 8 стояли НЕ НА КОДЕ, и один — на
# комментарии, утверждавшем ОБРАТНОЕ («рендер React-элементами без dangerouslySetInnerHTML»).
# Отсечение по расширению файла этого не ловит: `.ts` с комментарием расширением не отличается от
# `.ts` с кодом.
#
# СОДЕРЖИМОЕ КОММЕНТАРИЕВ ЗАМЕНЯЕТСЯ ПРОБЕЛАМИ, а не вырезается: номера строк в находках обязаны
# остаться прежними, иначе судья пойдёт по неверному адресу.
#
# РАЗБОР ОШИБАЕТСЯ В БЕЗОПАСНУЮ СТОРОНУ. Кавычки отслеживаются, чтобы `"https://x"` не был принят за
# комментарий; на регулярке вида `/['"]/` разбор может решить, что строка открыта, и тогда он просто
# НЕ вычистит комментарий — то есть ошибётся в сторону лишнего флага, а не пропуска.
LINE_COMMENT_BY_SUFFIX = {
    ".py": ("#",), ".pyi": ("#",), ".sh": ("#",), ".bash": ("#",), ".zsh": ("#",),
    ".yaml": ("#",), ".yml": ("#",), ".toml": ("#",), ".rb": ("#",), ".pl": ("#",),
    ".js": ("//",), ".mjs": ("//",), ".cjs": ("//",), ".jsx": ("//",),
    ".ts": ("//",), ".mts": ("//",), ".cts": ("//",), ".tsx": ("//",),
    ".java": ("//",), ".go": ("//",), ".rs": ("//",), ".c": ("//",), ".cc": ("//",),
    ".cpp": ("//",), ".h": ("//",), ".hpp": ("//",), ".cs": ("//",), ".kt": ("//",),
    ".swift": ("//",), ".scala": ("//",), ".vue": ("//",), ".svelte": ("//",),
    ".php": ("//", "#"),
}
BLOCK_COMMENT_SUFFIXES = frozenset({
    ".js", ".mjs", ".cjs", ".jsx", ".ts", ".mts", ".cts", ".tsx", ".java", ".go", ".rs",
    ".c", ".cc", ".cpp", ".h", ".hpp", ".cs", ".kt", ".swift", ".scala", ".php",
    ".vue", ".svelte", ".css", ".scss", ".less",
})


def _suffix_of(path: str) -> str:
    tail = path.replace("\\", "/").rsplit("/", 1)[-1]
    return "." + tail.rsplit(".", 1)[-1].lower() if "." in tail else ""


def blank_comments(text: str, path: str) -> str:
    """Содержимое комментариев -> пробелы. Длина и переводы строк сохраняются."""
    suffix = _suffix_of(path)
    line_markers = LINE_COMMENT_BY_SUFFIX.get(suffix)
    block = suffix in BLOCK_COMMENT_SUFFIXES
    if not line_markers and not block:
        return text
    out = list(text)
    i, n, quote = 0, len(text), None
    while i < n:
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote or (ch == "\n" and quote != "`"):
                quote = None          # строка не переживает перевод строки (кроме шаблонной)
            i += 1
            continue
        if ch in "'\"`":
            quote = ch
            i += 1
            continue
        if block and text.startswith("/*", i):
            end = text.find("*/", i + 2)
            end = n if end == -1 else end + 2
            for k in range(i, end):
                if out[k] != "\n":
                    out[k] = " "
            i = end
            continue
        if line_markers and any(text.startswith(mark, i) for mark in line_markers):
            end = text.find("\n", i)
            end = n if end == -1 else end
            for k in range(i, end):
                out[k] = " "
            i = end
            continue
        i += 1
    return "".join(out)
