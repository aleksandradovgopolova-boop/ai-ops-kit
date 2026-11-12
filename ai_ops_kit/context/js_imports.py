"""Импорты JS/TS по синтаксическому дереву (tree-sitter) — опционально, с fallback (#1408).

ЗАЧЕМ. Прежний разбор импортов дочки — регулярное выражение по ОДНОЙ строке. Замер на типовом
коде: многострочный `import {\\n a,\\n} from '../db/client'` (так форматирует prettier) он не
видит вовсе, а `// import x from '../db/legacy'` и строку `"require('../db/fake')"` считает
рёбрами. Пропущенный импорт — пропущенное нарушение слоёв; импорт из комментария — ложная тревога.

ЧТО ВИДИТ. Статические `import … from`, `import '…'`, `import type`, ре-экспорты `export … from`,
TS `import x = require('…')`, вызовы `require('…')` и `import('…')` с литералом (в том числе
шаблонная строка без подстановок). Комментарии и строки кодом не считаются. Строка ребра — строка
НАЧАЛА инструкции: по адресу видно, где импорт начинается.

ЧЕГО НЕ ДЕЛАЕТ. Не вычисляет выражения (`import(name)` — не ребро), не разрешает пути, алиасы и
`exports` пакетов: это остаётся потребителю. `.vue`/`.svelte` грамматикой не покрыты.

ОПЦИОНАЛЬНО. Tree-sitter — не зависимость кита: модуль импортирует его лениво, только когда
потребитель явно выбрал разбор деревом. Нет пакета, нет грамматики для расширения или дерево с
синтаксической ошибкой — `AstUnavailable` с причиной; потребитель разбирает файл прежним способом
и показывает причину, а не молчит.
"""
from __future__ import annotations

from dataclasses import dataclass

PARSERS = ("regex", "tree-sitter")
INSTALL_HINT = "pip install tree-sitter tree-sitter-javascript tree-sitter-typescript"
# Расширение -> грамматика. JSX входит в грамматику javascript; .tsx — отдельная грамматика TS.
GRAMMARS = {".ts": "typescript", ".mts": "typescript", ".cts": "typescript", ".tsx": "tsx",
            ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript"}

# Причины, по которым файл разобран прежним способом (стабильные коды для отчёта).
UNSUPPORTED = "unsupported-extension"
NOT_INSTALLED = "parser-unavailable"
SYNTAX_ERROR = "syntax-error"
ESCAPED_SPECIFIER = "escaped-specifier"


class AstUnavailable(Exception):
    """Файл нельзя разобрать деревом; `reason` — один из кодов выше."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


@dataclass(frozen=True)
class JsImport:
    specifier: str
    line: int


def _load_language(grammar: str):
    from tree_sitter import Language
    if grammar == "javascript":
        import tree_sitter_javascript
        return Language(tree_sitter_javascript.language())
    import tree_sitter_typescript
    return Language(tree_sitter_typescript.language_tsx() if grammar == "tsx"
                    else tree_sitter_typescript.language_typescript())


def _literal(node, source: bytes) -> str | None:
    """Значение строкового литерала; None — не литерал (выражение, подстановка).

    Escape-последовательность в литерале не декодируется: файл целиком уходит в fallback с
    причиной, а не теряет импорт молча.
    """
    if node is None or node.type not in ("string", "template_string"):
        return None
    if any(c.type == "template_substitution" for c in node.named_children):
        return None
    if any(c.type == "escape_sequence" for c in node.named_children):
        raise AstUnavailable(ESCAPED_SPECIFIER)
    value = "".join(source[c.start_byte:c.end_byte].decode("utf-8")
                    for c in node.named_children if c.type == "string_fragment")
    return value or None


def _call_argument(node):
    args = node.child_by_field_name("arguments")
    values = [n for n in (args.named_children if args else []) if n.type != "comment"]
    return values[0] if values else None


def _specifier_node(node, source: bytes):
    """Узел-литерал источника импорта для инструкции/вызова; None — узел не импорт."""
    if node.type in ("import_statement", "export_statement"):
        src = node.child_by_field_name("source")
        if src is not None:
            return src
        clause = next((c for c in node.named_children if c.type == "import_require_clause"), None)
        return next((c for c in clause.named_children if c.type == "string"), None) if clause else None
    if node.type == "call_expression":
        fn = node.child_by_field_name("function")
        if fn is not None and (fn.type == "import" or fn.type == "identifier"
                               and source[fn.start_byte:fn.end_byte] == b"require"):
            return _call_argument(node)
    return None


def extract(tree_root, source: bytes) -> list[JsImport]:
    """Импорты из готового дерева: (specifier, строка начала инструкции), в порядке исходника."""
    found, stack = [], [tree_root]
    while stack:
        node = stack.pop()
        stack.extend(reversed(node.named_children))
        if node.type == "comment":
            continue
        spec_node = _specifier_node(node, source)
        spec = _literal(spec_node, source)
        if spec:
            found.append(JsImport(spec, node.start_point[0] + 1))
    return found


class AstImportReader:
    """Разбор деревом на время одного прохода: грамматики грузятся лениво и один раз."""

    def __init__(self):
        self._parsers: dict = {}

    def _parser(self, grammar: str):
        if grammar not in self._parsers:
            try:
                language = _load_language(grammar)   # первым: он же проверяет наличие пакета
                from tree_sitter import Parser
                self._parsers[grammar] = (Parser(language), None)
            except (ImportError, OSError, AttributeError, TypeError, ValueError) as exc:
                self._parsers[grammar] = (None, f"{type(exc).__name__}: {exc}")
        return self._parsers[grammar]

    def read(self, suffix: str, content: str) -> list[JsImport]:
        grammar = GRAMMARS.get(suffix)
        if grammar is None:
            raise AstUnavailable(UNSUPPORTED, suffix)
        parser, problem = self._parser(grammar)
        if parser is None:
            raise AstUnavailable(NOT_INSTALLED, problem)
        source = content.encode("utf-8")
        root = parser.parse(source).root_node
        if root.has_error:
            # Восстановленное дерево не доказывает полноты: часть кода могла выпасть.
            raise AstUnavailable(SYNTAX_ERROR)
        return extract(root, source)
