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
    """Разобранный исходник дочки, передаваемый экстрактору."""
    rel_path: str      # путь относительно корня дочки, posix (идёт в ref как "file")
    tree: ast.AST      # AST исходника (разобран один раз, шарится между экстракторами)


# Экстрактор = адаптер под ОДИН стек. Регистрация записью делает добавление стека вопросом
# «функция + запись», а не форком обхода — точка расширения кита.
@dataclass(frozen=True)
class Extractor:
    id: str                                   # id из surface-extractors.yaml
    suffixes: frozenset                       # расширения файлов, к которым применим ({".py"})
    surface_kinds: tuple                      # какие kind порождает (для честной декларации)
    confidence: str                           # уверenность метода (verified | inferred)
    extract: Callable[[ParsedFile], list]     # (ParsedFile) -> list[Surface]


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


# Реестр реализованных экстракторов. Порядок ключей — порядок применения (детерминизм). Добавление
# нового стека = ещё одна запись здесь + честная декларация в surface-extractors.yaml.
PYTHON_WEB_ROUTES = Extractor(
    id="python-web-routes",
    suffixes=frozenset({".py"}),
    surface_kinds=("route",),
    confidence="verified",
    extract=extract_python_web_routes,
)

DEFAULT_EXTRACTORS: tuple = (PYTHON_WEB_ROUTES,)


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
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        except (OSError, SyntaxError, ValueError):
            continue
        parsed = ParsedFile(rel_path=rel, tree=tree)
        for ex in active:
            if path.suffix in ex.suffixes:
                surfaces.extend(ex.extract(parsed))
    surfaces.sort(key=lambda s: (s.ref, s.kind, s.extractor))
    return [s.as_record() for s in surfaces]
