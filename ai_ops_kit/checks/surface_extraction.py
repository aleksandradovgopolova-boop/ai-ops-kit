"""Извлечение наблюдаемых ПОВЕРХНОСТЕЙ продукта из кода дочки (W2 feature-registry-coverage).

Кит выводит наблюдаемые точки контакта продукта (маршруты/эндпоинты, CLI-команды, экраны UI,
публичный API) прямо из ИСХОДНИКА дочки — детерминированно, без сети и без вызова модели — и
возвращает список записей `surface` строго по контракту схемы реестра фич
(`registry/feature-registry/feature-registry.schema.yaml`): `{kind, ref: "file:line|symbol",
confidence, extractor}`. Дальше судья охвата (W3) сверит эти поверхности с реестром фич, а честная
сила по `confidence` (W4) решит, блокировать прогон или только предупреждать.

ПОЧЕМУ ЗДЕСЬ, В `checks`. Извлечение — ЧИСТОЕ, read-only чтение исходника дочки на stdlib (`ast`) без
импорта чего-либо из ai_ops_kit выше foundation. Ровно контракт пакета `checks` (слой primitives):
проверяющую/аналитическую логику держим НИЖЕ entrypoints, чтобы её звали ВНИЗ по слоям, а не тянули
`validation` вверх. Судья охвата (W3) импортирует `extract_surfaces` отсюда как библиотеку в свой
слой; CLI-обёртка живёт в `devtools` (точка входа), она и проводит модуль в контур.

ЧЕСТНОСТЬ СИЛЫ = ЧЕСТНОСТЬ `confidence` (FEAT-003/004). Поверхность, доказанная точным разбором AST
(декоратор-литерал в исходнике), помечается `confidence: verified` — её потом вправе блокировать.
Всё, что выведено эвристикой/предположением, обязано быть `inferred` (только предупреждает). Поднимать
уверенность ради усиления блокировки запрещено стандартом FEAT.

РАСШИРЯЕМОСТЬ БЕЗ ФОРКА ЯДРА. Каждый стек покрывает отдельный ЭКСТРАКТОР-адаптер (`Extractor`),
объявляющий, к каким файлам применим и какую уверенность даёт. Ядро обхода (`extract_surfaces`)
парсит исходники и раздаёт их применимым экстракторам; добавить новый стек — значит написать функцию
и зарегистрировать её записью, а не править обход. Реализованные экстракторы честно продекларированы
в `registry/feature-registry/surface-extractors.yaml` (инвариант честных capability-деклараций).
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Sequence

# ── Декораторы HTTP-маршрутов известных питон-фреймворков (Flask 2.x, FastAPI, APIRouter). ────────
# Метод-атрибут декоратора: Flask `@app.route`, Flask 2.0+ / FastAPI `@app.get/@router.post/...`,
# `@app.api_route`, `@app.websocket`. Сам по себе этот набор поверхности не доказывает — доказывает
# связка «декоратор-Call + атрибут из набора + первый арг = строковый путь, начинающийся с '/'».
_HTTP_DECORATOR_ATTRS = frozenset({
    "route", "api_route", "websocket",
    "get", "post", "put", "delete", "patch", "head", "options", "trace",
})

# Служебные/чужие каталоги — не код продукта. Обход в них не заходит (шум и чужой исходник).
_SKIP_DIRS = frozenset({
    ".git", ".ai", ".hg", ".svn", "node_modules", "venv", ".venv", "env", ".env",
    "__pycache__", ".tox", ".nox", "build", "dist", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", "site-packages", ".eggs",
})


@dataclass(frozen=True)
class Surface:
    """Одна запись поверхности по контракту схемы реестра фич.

    Поля ровно те, что требует `surface` в схеме: kind ∈ {route,cli,screen,api};
    ref = "file:line" или "file:line|symbol"; confidence ∈ {verified,inferred}; extractor — id
    экстрактора, породившего запись (из surface-extractors.yaml).
    """
    kind: str
    ref: str
    confidence: str
    extractor: str

    def as_record(self) -> dict:
        """Плоский dict строго по схеме surface (без лишних ключей)."""
        return {"kind": self.kind, "ref": self.ref,
                "confidence": self.confidence, "extractor": self.extractor}


@dataclass(frozen=True)
class ParsedFile:
    """Разобранный исходник дочки, передаваемый экстрактору.

    Несёт и СЫРОЙ текст, и AST. AST-экстрактор (`needs_ast=True`) читает `tree` — ядро гарантирует,
    что дерево разобрано (иначе экстрактор не вызывается). Текстовый экстрактор (`needs_ast=False`,
    напр. console_scripts из TOML/INI, которые не парсятся `ast`) читает `source`. Так добавление
    не-Python стека остаётся «функция + запись», а не форком обхода.
    """
    rel_path: str            # путь относительно корня дочки, posix (идёт в ref как "file")
    source: str              # сырой текст исходника (для текстовых экстракторов)
    tree: ast.AST | None     # AST исходника (None, если файл не Python или не разобрался)


# Экстрактор = адаптер под ОДИН стек. Регистрация записью делает добавление стека вопросом
# «функция + запись», а не форком обхода — точка расширения кита.
@dataclass(frozen=True)
class Extractor:
    id: str                                   # id из surface-extractors.yaml
    suffixes: frozenset                       # расширения файлов, к которым применим ({".py"})
    surface_kinds: tuple                      # какие kind порождает (для честной декларации)
    confidence: str                           # уверenность метода (verified | inferred)
    extract: Callable[[ParsedFile], list]     # (ParsedFile) -> list[Surface]
    needs_ast: bool = True                    # True — экстрактору нужен разобранный AST (.py);
    #                                           False — работает по сырому тексту (TOML/INI и т.п.)


# ─── Верифицированный экстрактор: HTTP-маршруты Flask/FastAPI по декораторам (AST) ───────────────

def _is_path_literal(node: ast.expr) -> bool:
    """Первый аргумент декоратора — строковый ЛИТЕРАЛ пути, начинающийся с '/'.

    Это и есть граница verified: путь взят из исходника буквально, а не выведен из переменной или
    f-строки. Литерал-путь + метод-атрибут из набора однозначно опознаёт объявление маршрута и
    отсекает случайный `x.get(var)`/`obj.post(payload)`, где первый арг — не путь.
    """
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith("/")


def extract_python_web_routes(parsed: ParsedFile) -> list:
    """Извлечь HTTP-маршруты, объявленные декоратором в исходнике (Flask/FastAPI-стиль).

    Точный разбор AST, без исполнения кода → confidence: verified. Опознаётся объявление вида
    `@<router>.<method>("/path", ...)` над (async-)функцией, где <method> ∈ _HTTP_DECORATOR_ATTRS,
    а первый позиционный аргумент — строковый путь-литерал. symbol в ref — имя функции-обработчика.
    """
    out: list = []
    for node in ast.walk(parsed.tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                continue
            if dec.func.attr not in _HTTP_DECORATOR_ATTRS:
                continue
            # приёмник декоратора — имя (app/router/bp/api) или атрибут (app.router): маршрутизатор,
            # а не произвольный объект. Реальная граница точности — литерал-путь ниже.
            if not isinstance(dec.func.value, (ast.Name, ast.Attribute)):
                continue
            if not (dec.args and _is_path_literal(dec.args[0])):
                continue
            ref = f"{parsed.rel_path}:{node.lineno}|{node.name}"
            out.append(Surface(kind="route", ref=ref,
                               confidence="verified", extractor="python-web-routes"))
            break   # один маршрут на обработчик (несколько методов на одном пути = одна поверхность)
    return out


# ─── Верифицированные экстракторы: CLI-команды продукта (новый вид поверхности `cli`) ────────────
# Команда продукта, объявленная в исходнике ЛИТЕРАЛЬНО (строка-имя подкоманды/декоратора или ключ
# console_scripts), доказуема точным разбором → confidence: verified. Имя, собранное динамически
# (переменная/f-строка/prog из переменной), verified НЕ становится — оно просто пропускается, чтобы
# сила блокировки не опиралась на недоказанное (FEAT-003/004).

def _is_str_literal(node: ast.expr) -> bool:
    """Узел — строковый ЛИТЕРАЛ (не f-строка, не переменная, не конкатенация)."""
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _imports_module(tree: ast.AST, modname: str) -> bool:
    """Файл импортирует модуль modname (`import modname[.x]` или `from modname[.x] import ...`).

    Экстракторы argparse/click сужены этим условием: `.add_parser(...)`/`@x.command()` доказывают
    CLI лишь в файле, который действительно тянет соответствующий модуль. Без этого атрибут с тем же
    именем в чужом коде дал бы ложный verified — прямой запрет инварианта честной силы.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == modname or alias.name.startswith(modname + "."):
                    return True
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == modname or mod.startswith(modname + "."):
                return True
    return False


def _keyword_str_literal(call: ast.Call, name: str) -> str | None:
    """Значение строкового-литерала именованного аргумента `name=` вызова, иначе None."""
    for kw in call.keywords:
        if kw.arg == name and _is_str_literal(kw.value):
            return kw.value.value
    return None


def extract_python_cli_argparse(parsed: ParsedFile) -> list:
    """CLI-команды argparse из исходника (subparsers.add_parser + ArgumentParser(prog=...)).

    Точный разбор AST в файле, который импортирует `argparse` → confidence: verified. Опознаётся:
      * `<subparsers>.add_parser("<name>", ...)` — имя подкоманды из строкового литерала;
      * `ArgumentParser(prog="<name>")` — объявленное имя программы (по возможности, тоже литерал).
    Имя-НЕ-литерал (переменная/f-строка) пропускается: verified без доказательства запрещён.
    """
    tree = parsed.tree
    if tree is None or not _imports_module(tree, "argparse"):
        return []
    out: list = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "add_parser":
            if node.args and _is_str_literal(node.args[0]):
                name = node.args[0].value
                out.append(Surface(kind="cli", ref=f"{parsed.rel_path}:{node.lineno}|{name}",
                                   confidence="verified", extractor="python-cli-argparse"))
            continue
        is_parser = (isinstance(func, ast.Name) and func.id == "ArgumentParser") or \
                    (isinstance(func, ast.Attribute) and func.attr == "ArgumentParser")
        if is_parser:
            prog = _keyword_str_literal(node, "prog")
            if prog is not None:
                out.append(Surface(kind="cli", ref=f"{parsed.rel_path}:{node.lineno}|{prog}",
                                   confidence="verified", extractor="python-cli-argparse"))
    return out


# Атрибуты-декораторы click, объявляющие команду: @click.command/@click.group, @cli.command и т.п.
_CLICK_COMMAND_ATTRS = frozenset({"command", "group"})


def _click_command_name(dec: ast.expr, func_name: str) -> str | None:
    """Имя click-команды из декоратора над функцией, либо None если это не command/group-декоратор
    ИЛИ имя задано явно, но недоказуемо.

    Явное литеральное имя (строка первым позиционным аргументом или `name="..."`) → берётся как есть.
    Явное, но НЕ литеральное имя (переменная в аргументе или `name=<переменная>`) → None: click в
    рантайме взял бы это значение, а не имя функции, поэтому доказать имя нельзя — пропускаем, как
    argparse (FEAT-003/004: verified только доказуемое). Имя из функции берётся ТОЛЬКО когда явного
    имени нет вовсе: click образует его детерминированно — хвостовой `_` срезается (click ≥8.1,
    идиома `list_`→`list`), затем `lower()` и `_`→`-`.
    """
    if isinstance(dec, ast.Call):
        target, args, keywords = dec.func, dec.args, dec.keywords
    else:
        target, args, keywords = dec, [], []
    is_cmd = (isinstance(target, ast.Attribute) and target.attr in _CLICK_COMMAND_ATTRS) or \
             (isinstance(target, ast.Name) and target.id in _CLICK_COMMAND_ATTRS)
    if not is_cmd:
        return None
    name_kw = next((kw for kw in keywords if kw.arg == "name"), None)
    explicit = bool(args) or name_kw is not None
    if args and _is_str_literal(args[0]):
        return args[0].value
    if name_kw is not None and _is_str_literal(name_kw.value):
        return name_kw.value.value
    if explicit:
        return None  # явное имя задано, но не литерал — доказать нельзя, пропускаем (симметрия с argparse)
    return func_name.rstrip("_").lower().replace("_", "-")


def extract_python_cli_click(parsed: ParsedFile) -> list:
    """CLI-команды click из исходника (@click.command()/@click.group() и @<group>.command()).

    Точный разбор AST в файле, который импортирует `click` → confidence: verified. Имя команды —
    из декоратора (литерал/`name=`) или из имени функции по правилу именования click. symbol в ref —
    имя команды. Файлы без импорта click не трогаются (иначе чужой `.command` дал бы ложный verified).
    """
    tree = parsed.tree
    if tree is None or not _imports_module(tree, "click"):
        return []
    out: list = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            name = _click_command_name(dec, node.name)
            if name is not None:
                out.append(Surface(kind="cli", ref=f"{parsed.rel_path}:{node.lineno}|{name}",
                                   confidence="verified", extractor="python-cli-click"))
                break   # одна команда на функцию (несколько click-декораторов = одна поверхность)
    return out


# ─── Верифицированный экстрактор: console_scripts (объявленные точки входа) ───────────────────────
# Имя команды в [project.scripts]/[project.gui-scripts]/[tool.poetry.scripts] (pyproject.toml) или
# в console_scripts/gui_scripts секции [options.entry_points] (setup.cfg) — ОБЪЯВЛЕННАЯ точка входа
# дистрибутива, доказуемо verified. Текстовый разбор, БЕЗ `tomllib` (он 3.11+, а пол кита — 3.9;
# собственный validate_python_compat этот импорт отклоняет): один построчный сканер, один ответ на
# всех версиях. Битый файл — пропуск (см. изоляцию в extract_surfaces).

_SECTION_RE = re.compile(r"^\s*\[\s*([^\]]+?)\s*\]\s*$")
_TOML_SCRIPT_SECTIONS = frozenset({"project.scripts", "project.gui-scripts", "tool.poetry.scripts"})
_CFG_ENTRY_KEYS = frozenset({"console_scripts", "gui_scripts"})


def _console_scripts_pyproject(parsed: ParsedFile) -> list:
    """Ключи-имена команд из script-таблиц pyproject.toml (по одному ключу на строку `name = ...`)."""
    out: list = []
    section = ""
    for i, raw in enumerate(parsed.source.splitlines(), start=1):
        line = "" if raw.lstrip().startswith("#") else raw.split("#", 1)[0]
        m = _SECTION_RE.match(line)
        if m:
            section = m.group(1).strip().strip("\"'")
            continue
        if section not in _TOML_SCRIPT_SECTIONS or "=" not in line:
            continue
        name = line.split("=", 1)[0].strip().strip("\"'")
        if name:
            out.append(Surface(kind="cli", ref=f"{parsed.rel_path}:{i}|{name}",
                               confidence="verified", extractor="python-console-scripts"))
    return out


def _console_scripts_setupcfg(parsed: ParsedFile) -> list:
    """Имена команд из console_scripts/gui_scripts в [options.entry_points] setup.cfg (INI).

    Значение ключа — многострочный блок с отступом: каждая вложенная строка `name = target`.
    Собираем `name` вложенных строк, пока идёт отступной блок нужного ключа.
    """
    out: list = []
    section = ""
    collecting = False   # внутри блока console_scripts/gui_scripts (собираем вложенные строки)
    for i, raw in enumerate(parsed.source.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith(";"):
            continue
        m = _SECTION_RE.match(raw)
        if m:
            section = m.group(1).strip()
            collecting = False
            continue
        if section != "options.entry_points":
            collecting = False
            continue
        if not raw[:1].isspace():   # ключ секции на нулевой колонке
            key = raw.split("=", 1)[0].split(":", 1)[0].strip()
            collecting = key in _CFG_ENTRY_KEYS
            continue
        if collecting and "=" in raw:   # вложенная строка блока: name = target
            name = raw.split("=", 1)[0].strip()
            if name:
                out.append(Surface(kind="cli", ref=f"{parsed.rel_path}:{i}|{name}",
                                   confidence="verified", extractor="python-console-scripts"))
    return out


def extract_console_scripts(parsed: ParsedFile) -> list:
    """console_scripts / gui_scripts из pyproject.toml или setup.cfg дочки (объявленные точки входа)."""
    basename = parsed.rel_path.rsplit("/", 1)[-1]
    if basename == "pyproject.toml":
        return _console_scripts_pyproject(parsed)
    if basename == "setup.cfg":
        return _console_scripts_setupcfg(parsed)
    return []


# Реестр реализованных экстракторов. Порядок ключей — порядок применения (детерминизм). Добавление
# нового стека = ещё одна запись здесь + честная декларация в surface-extractors.yaml.
PYTHON_WEB_ROUTES = Extractor(
    id="python-web-routes",
    suffixes=frozenset({".py"}),
    surface_kinds=("route",),
    confidence="verified",
    extract=extract_python_web_routes,
)

PYTHON_CLI_ARGPARSE = Extractor(
    id="python-cli-argparse",
    suffixes=frozenset({".py"}),
    surface_kinds=("cli",),
    confidence="verified",
    extract=extract_python_cli_argparse,
)

PYTHON_CLI_CLICK = Extractor(
    id="python-cli-click",
    suffixes=frozenset({".py"}),
    surface_kinds=("cli",),
    confidence="verified",
    extract=extract_python_cli_click,
)

PYTHON_CONSOLE_SCRIPTS = Extractor(
    id="python-console-scripts",
    suffixes=frozenset({".toml", ".cfg"}),
    surface_kinds=("cli",),
    confidence="verified",
    extract=extract_console_scripts,
    needs_ast=False,
)

DEFAULT_EXTRACTORS: tuple = (
    PYTHON_WEB_ROUTES,
    PYTHON_CLI_ARGPARSE,
    PYTHON_CLI_CLICK,
    PYTHON_CONSOLE_SCRIPTS,
)


# ─── Ядро обхода ─────────────────────────────────────────────────────────────────────────────────

def _iter_source_files(root: Path, suffixes: frozenset) -> Iterator[Path]:
    """Детерминированный обход исходников дочки с нужными расширениями, минуя служебные каталоги."""
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in suffixes:
            continue
        if any(part in _SKIP_DIRS for part in path.relative_to(root).parts[:-1]):
            continue
        yield path


def extract_surfaces(child_root, extractors: Sequence[Extractor] | None = None) -> list:
    """Извлечь поверхности продукта из кода дочки. -> список dict строго по схеме surface.

    Детерминированно, только stdlib (`ast`), без сети и без вызова модели. Читает исходники под
    `child_root`, парсит один раз на файл и раздаёт AST применимым экстракторам (по расширению).
    Возврат отсортирован (ref, kind, extractor) — один и тот же вход даёт один и тот же выход.

    extractors — набор экстракторов; по умолчанию DEFAULT_EXTRACTORS (реализованные и честно
    задекларированные). Файл, который не парсится (SyntaxError чужого/битого исходника), молча
    пропускается: извлечение — не линтер, оно не обязано разбирать некорректный код.
    """
    root = Path(child_root)
    active = tuple(DEFAULT_EXTRACTORS if extractors is None else extractors)
    wanted: frozenset = frozenset().union(*(e.suffixes for e in active)) if active else frozenset()
    surfaces: list = []
    for path in _iter_source_files(root, wanted):
        rel = path.relative_to(root).as_posix()
        applicable = [ex for ex in active if path.suffix in ex.suffixes]
        if not applicable:
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            continue
        tree = None
        if any(ex.needs_ast for ex in applicable):
            try:
                tree = ast.parse(source, filename=rel)
            except (SyntaxError, ValueError):
                tree = None   # не Python/битый .py — AST-экстракторы просто не позовутся
        parsed = ParsedFile(rel_path=rel, source=source, tree=tree)
        for ex in applicable:
            if ex.needs_ast and parsed.tree is None:
                continue   # AST-экстрактору нечего дать: файл не разобрался
            surfaces.extend(ex.extract(parsed))
    surfaces.sort(key=lambda s: (s.ref, s.kind, s.extractor))
    return [s.as_record() for s in surfaces]
