"""Структурные дубли функций (CODE-003): одно ядро для кита и проекта (#827, #1512).

ЗАЧЕМ ОДНО. Прежде логика жила дважды: ратчет кита в `devtools/code_duplication.py` (в поставку не
едет) и упрощённая копия в `checks/constitution_conformance.py` (едет, но без базы заморозки и без
слова «не проверяется»). Две копии одной проверки на дубли — сами по себе нарушение CODE-003.
Теперь подпись, группы, ключи и база живут здесь; кит, онбординг и проверка проекта зовут это ядро.

СИГНАТУРА. Последовательность имён типов AST-узлов функции (`ast.walk`). Идентификаторы, литералы и
имена аргументов не учитываются: две структурно одинаковые функции с разными именами — дубль.
Имена типов узлов стабильны между версиями Python, база не плывёт от смены интерпретатора.

ШУМ. Не считаются `main` и дандеры (намеренный шаблон точек входа) и функции короче MIN_STMTS
операторов — мелкие совпадения не долг.

КЛЮЧ ГРУППЫ — sha256 от отсортированных членов `путь::имя`, без номеров строк: правка соседнего кода
не превращает замороженную группу в новую.

ЯЗЫКИ. Детектор читает только Python. Проект, где исходники есть, но Python нет, слышит «не
проверяется», а не «дублей нет»: пустой результат по непрочитанному коду — не результат.
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import yaml

MIN_STMTS = 10
SKIP_NAMES = frozenset({"main", "__init__", "__repr__", "__eq__", "__hash__", "__str__"})
# Каталоги, которые не считаются исходным кодом продукта (тесты — намеренно: фикстуры похожи).
SKIP_DIRS = frozenset({".git", ".ai", ".ai-ops", "node_modules", "venv", ".venv", "__pycache__",
                       "build", "dist", ".mypy_cache", ".pytest_cache", "tests", "test"})
CHECKED_LANGUAGES = {".py": "Python"}
# Исходники, которые в проекте бывают, но детектором не читаются, — называются в отчёте.
UNCHECKED_LANGUAGES = {".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript",
                       ".cjs": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript",
                       ".go": "Go", ".java": "Java", ".kt": "Kotlin", ".rb": "Ruby",
                       ".php": "PHP", ".cs": "C#", ".rs": "Rust", ".swift": "Swift"}
CHILD_BASELINE = ".ai/project/code-duplication-baseline.yaml"


def signature(fn: ast.AST) -> tuple:
    """Версионно-стабильная структурная подпись: имена типов узлов при обходе."""
    return tuple(type(n).__name__ for n in ast.walk(fn))


def statement_count(fn: ast.AST) -> int:
    return sum(1 for n in ast.walk(fn) if isinstance(n, ast.stmt))


def is_candidate(fn: ast.AST) -> bool:
    """Функция, которую имеет смысл сравнивать: не шаблон точки входа и не мелочь."""
    return fn.name not in SKIP_NAMES and statement_count(fn) >= MIN_STMTS


def _rel(path: Path, rel_to: Path) -> str:
    try:
        return path.relative_to(rel_to).as_posix()
    except ValueError:
        return path.as_posix()


def iter_functions(paths, rel_to: Path, unread: list | None = None):
    """(относительный путь, узел функции) для кандидатов.

    Непрочитанный файл (кодировка, синтаксис, доступ) пропускается, но НЕ молча: его путь
    попадает в `unread` — по нему судить нельзя, и отчёт обязан это назвать.
    """
    for path in paths:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, ValueError, OSError, UnicodeError):
            if unread is not None:
                unread.append(_rel(path, rel_to))
            continue
        rel = _rel(path, rel_to)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and is_candidate(node):
                yield rel, node


def group_key(members) -> str:
    """Стабильный ключ группы: sha256 от отсортированных членов `путь::имя`."""
    return hashlib.sha256("\n".join(sorted(members)).encode("utf-8")).hexdigest()[:16]


def duplicate_groups(paths, rel_to: Path, unread: list | None = None) -> list[dict]:
    """Группы структурно-одинаковых функций. -> [{key, members, locations}], по ключу.

    members — `путь::имя` (ключ базы), locations — `путь:строка:имя` (адрес для человека).
    Два вхождения одного имени в одном файле (перегрузка под TYPE_CHECKING) дублем не считаются.
    """
    by_sig: dict[tuple, dict[str, int]] = {}
    for rel, node in iter_functions(paths, rel_to, unread):
        by_sig.setdefault(signature(node), {}).setdefault(f"{rel}::{node.name}", node.lineno)
    groups = []
    for found in by_sig.values():
        if len(found) > 1:
            members = sorted(found)
            groups.append({"key": group_key(members), "members": members,
                           "locations": [f"{m.partition('::')[0]}:{found[m]}:{m.partition('::')[2]}"
                                         for m in members]})
    return sorted(groups, key=lambda g: g["key"])


def _source_files(root: Path):
    for path in sorted(root.rglob("*")):
        if path.suffix and not any(part in SKIP_DIRS for part in path.relative_to(root).parts) \
                and path.is_file():
            yield path


def source_languages(root) -> tuple[dict, dict, list]:
    """Исходники продукта по языкам. -> (checked, not_checked, python_files).

    checked / not_checked — {язык: число файлов}. Пустой checked значит «не проверяется», а не
    «дублей нет».
    """
    root = Path(root)
    checked, not_checked, py_files = {}, {}, []
    for path in _source_files(root):
        if path.suffix in CHECKED_LANGUAGES:
            lang = CHECKED_LANGUAGES[path.suffix]
            checked[lang] = checked.get(lang, 0) + 1
            py_files.append(path)
        elif path.suffix in UNCHECKED_LANGUAGES:
            lang = UNCHECKED_LANGUAGES[path.suffix]
            not_checked[lang] = not_checked.get(lang, 0) + 1
    return checked, not_checked, py_files


def scan_project(root) -> dict:
    """Проект целиком. -> {groups, checked, not_checked, unread}.

    checked — только ПРОЧИТАННЫЕ файлы: непарсящийся .py проверенным не считается (иначе проект
    из таких файлов получил бы «дублей нет»); их пути — в unread.
    """
    _, not_checked, py_files = source_languages(root)
    unread: list = []
    groups = duplicate_groups(py_files, Path(root), unread)
    read = len(py_files) - len(unread)
    return {"groups": groups, "checked": {"Python": read} if read else {},
            "not_checked": not_checked, "unread": sorted(unread)}


class BaselineUnreadable(ValueError):
    """Файл базы есть, но прочитать его как базу нельзя — это не «базы нет» и не «пустая база»."""


def load_baseline(path) -> set[str] | None:
    """Ключи замороженных групп; None — базы нет. Битый файл — BaselineUnreadable."""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError, UnicodeError) as exc:
        raise BaselineUnreadable(f"{path}: {type(exc).__name__}") from exc
    groups = doc.get("groups") if isinstance(doc, dict) else None
    if not isinstance(groups, list):
        raise BaselineUnreadable(f"{path}: нет списка groups")
    return {str(g["key"]) for g in groups if isinstance(g, dict) and g.get("key")}


def compare(groups: list[dict], baseline: set[str]) -> dict:
    """Ратчет: новые группы сверх базы, число замороженных, устаревшие ключи базы (ход вниз)."""
    keys = {g["key"] for g in groups}
    return {"new": [g for g in groups if g["key"] not in baseline],
            "frozen": len(keys & baseline), "stale": sorted(baseline - keys)}


def render_baseline(groups: list[dict], scan_root: str, header: tuple[str, ...]) -> str:
    """Файл базы: заголовок-комментарий, затем группы `key` + `members`."""
    lines = [*(f"# {h}" if h else "#" for h in header),
             "schema_version: 1", "kind: code-duplication-ratchet", f"scan_root: {scan_root}",
             f"min_stmts: {MIN_STMTS}", "groups:" if groups else "groups: []"]
    for g in groups:
        lines.append(f"  - key: {g['key']}")
        lines.append("    members:")
        lines.extend(f"      - {m}" for m in g["members"])
    return "\n".join(lines) + "\n"
