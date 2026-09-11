#!/usr/bin/env python3
"""Проверка соответствия кода репозитория Архитектурной конституции + рекомендации (#845).

ЗАЧЕМ. #820 доставил конституцию в дочку как машинный реестр, но проверки были parent-only: дочка
правила ПОЛУЧАЛА, но по ним себя не проверяла. У каждой дочки своя кодовая база и история — жёсткий
ратчет-блок чужого легаси неправилен. Поэтому здесь — **проверка соответствия → РЕКОМЕНДАЦИИ
владельцу** (advisory, не блок): «где код расходится со статьёй, что стоит рассмотреть».

УНИВЕРСАЛЬНОСТЬ. Сканируется код ЛЮБОЙ дочки (авто-корень, не хардкод `ai_ops_kit/`). Проверки —
переносимые эвристики уровня кода (длинная функция, глубокая вложенность, структурный дубль, крупный
модуль). Кит-специфичные статьи (слои→DAG, built≠wired завязаны на устройство кита) НЕ входят.

СВЯЗЬ С РЕЕСТРОМ. Находка цитирует стабильный `article_id`, а заголовок/уровень берутся из
ДОСТАВЛЕННОГО `standards/architecture/rules.yaml` (в дочке — `.ai/managed/...`). Статьи нет в
доставленной версии — находки по ней не выдаются (версия конституции дочки — источник истины).

Порог — не ратчет, а разумный дефолт для РЕКОМЕНДАЦИИ. Read-only: ничего не пишет.
"""
from __future__ import annotations

import ast
from pathlib import Path

import yaml

# Разумные дефолты для advisory-рекомендаций (НЕ per-repo ратчет — просто «стоит присмотреться»).
LONG_FUNCTION_LINES = 60
DEEP_NESTING = 5
LONG_MODULE_LINES = 500
DUP_MIN_STMTS = 10

# Каталоги, которые не считаются исходным кодом продукта.
_SKIP_DIRS = {".git", ".ai", ".ai-ops", "node_modules", "venv", ".venv", "__pycache__",
              "build", "dist", ".mypy_cache", ".pytest_cache", "tests", "test"}
_SKIP_FUNC_NAMES = {"main", "__init__", "__repr__", "__eq__", "__hash__", "__str__"}


def load_rules(rules_path: Path) -> dict:
    """{article_id: {title, level, severity}} из доставленного rules.yaml. Пусто, если файла нет."""
    p = Path(rules_path)
    if not p.is_file():
        return {}
    doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    out = {}
    for r in doc.get("rules") or []:
        out[r["id"]] = {"title": r.get("title", ""), "level": r.get("level", ""),
                        "severity": r.get("severity", "medium")}
    return out


def default_rules_path(root: Path) -> Path:
    """Где лежит доставленный реестр: в дочке `.ai/managed/...`, иначе — корневой `standards/...`."""
    managed = Path(root) / ".ai" / "managed" / "standards" / "architecture" / "rules.yaml"
    if managed.is_file():
        return managed
    return Path(root) / "standards" / "architecture" / "rules.yaml"


def iter_source_files(root: Path):
    """.py-файлы продукта дочки (без .git/.ai/venv/tests/…)."""
    root = Path(root)
    for p in sorted(root.rglob("*.py")):
        if any(part in _SKIP_DIRS for part in p.relative_to(root).parts):
            continue
        yield p


def _parse(p: Path):
    try:
        return ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
    except (SyntaxError, OSError):
        return None


def _rel(p: Path, root: Path) -> str:
    try:
        return p.relative_to(root).as_posix()
    except ValueError:
        return p.name


def _max_depth(node: ast.AST, _depth: int = 0) -> int:
    """Глубина вложенности управляющих конструкций внутри функции."""
    nesting = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try)
    best = _depth
    for child in ast.iter_child_nodes(node):
        d = _depth + 1 if isinstance(child, nesting) else _depth
        best = max(best, _max_depth(child, d))
    return best


def _dup_signature(fn: ast.AST) -> tuple:
    return tuple(type(n).__name__ for n in ast.walk(fn))


def _functions(root: Path):
    for p in iter_source_files(root):
        tree = _parse(p)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield p, node


# ── эвристики: article_id -> находки ────────────────────────────────────────────

def _long_functions(root):
    hits = []
    for p, fn in _functions(root):
        end = getattr(fn, "end_lineno", None)
        if end and (end - fn.lineno + 1) > LONG_FUNCTION_LINES:
            hits.append({"where": f"{_rel(p, root)}:{fn.lineno}:{fn.name}",
                         "detail": f"{end - fn.lineno + 1} строк"})
    return hits


def _deep_nesting(root):
    hits = []
    for p, fn in _functions(root):
        d = _max_depth(fn)
        if d >= DEEP_NESTING:
            hits.append({"where": f"{_rel(p, root)}:{fn.lineno}:{fn.name}",
                         "detail": f"вложенность {d}"})
    return hits


def _long_modules(root):
    hits = []
    for p in iter_source_files(root):
        try:
            n = len(p.read_text(encoding="utf-8").splitlines())
        except OSError:
            continue
        if n > LONG_MODULE_LINES:
            hits.append({"where": _rel(p, root), "detail": f"{n} строк"})
    return hits


def _duplicates(root):
    by_sig: dict[tuple, list[str]] = {}
    for p, fn in _functions(root):
        if fn.name in _SKIP_FUNC_NAMES:
            continue
        if sum(1 for n in ast.walk(fn) if isinstance(n, ast.stmt)) < DUP_MIN_STMTS:
            continue
        by_sig.setdefault(_dup_signature(fn), []).append(f"{_rel(p, root)}:{fn.lineno}:{fn.name}")
    hits = []
    for members in by_sig.values():
        uniq = sorted(set(members))
        if len(uniq) > 1:
            hits.append({"where": uniq[0], "detail": "дубль: " + ", ".join(uniq[1:])})
    return hits


# article_id -> (эвристика, шаблон рекомендации владельцу)
_HEURISTICS = {
    "CODE-001": (_long_functions,
                 "Длинные функции трудно читать и тестировать. Рассмотрите разбиение на меньшие "
                 "односмысловые функции."),
    "CODE-002": (_deep_nesting,
                 "Глубокая вложенность прячет ветки и краевые случаи. Уплощите ранними возвратами "
                 "и guard-clause, вынесите ветки в именованные хелперы."),
    "CODE-003": (_duplicates,
                 "Скопированная логика расходится при правках. Выделите общую функцию вместо копипасты."),
    "ARCH-006": (_long_modules,
                 "Крупный модуль обычно владеет слишком многим (нарушен SRP). Рассмотрите разрез по "
                 "ответственности на меньшие связные модули."),
}


def conform(root: Path, rules_path: Path | None = None) -> list[dict]:
    """Проверить соответствие кода дочки конституции. -> список находок с рекомендациями.

    Находка: {article_id, title, level, severity, count, locations, recommendation}. Только по
    статьям, присутствующим в ДОСТАВЛЕННОМ реестре (версия конституции дочки — источник истины).
    """
    root = Path(root)
    rules = load_rules(rules_path or default_rules_path(root))
    findings = []
    for article_id, (fn, advice) in _HEURISTICS.items():
        meta = rules.get(article_id)
        if meta is None:
            continue                                    # статьи нет в доставленной версии — молчим честно
        hits = fn(root)
        if not hits:
            continue
        findings.append({
            "article_id": article_id,
            "title": meta["title"],
            "level": meta["level"],
            "severity": meta["severity"],
            "count": len(hits),
            "locations": [h["where"] for h in hits],
            "details": hits,
            "recommendation": advice,
        })
    # серьёзные статьи выше
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    findings.sort(key=lambda f: (order.get(f["severity"], 9), f["article_id"]))
    return findings


def summary(findings: list[dict]) -> str:
    """Одна строка-итог для владельца."""
    if not findings:
        return "Код соответствует автоматизируемым статьям конституции — расхождений не найдено."
    n = sum(f["count"] for f in findings)
    return (f"Нашлось {n} расхождений с конституцией по {len(findings)} статьям — "
            f"это рекомендации к рассмотрению, не блок.")


_MAX_LOCATIONS = 10


def render_report(findings: list[dict], scope: str = "весь код репозитория") -> str:
    """Owner-facing отчёт соответствия (Markdown, продуктовым языком). Рекомендации, не приговор."""
    lines = [
        "# Соответствие Архитектурной конституции",
        "",
        f"> {summary(findings)}",
        "",
        f"Проверено: {scope}. Это **рекомендации** — что стоит рассмотреть, а не блок на мерже. "
        "У каждого пункта — статья конституции, к которой он относится.",
        "",
    ]
    if not findings:
        lines.append("Расхождений по автоматизируемым статьям не найдено. 👍")
        return "\n".join(lines) + "\n"
    for f in findings:
        lines.append(f"## {f['article_id']} · {f['title']} ({f['count']})")
        lines.append("")
        lines.append(f"**Рекомендация.** {f['recommendation']}")
        lines.append("")
        lines.append("Где посмотреть:")
        for loc in f["locations"][:_MAX_LOCATIONS]:
            lines.append(f"- `{loc}`")
        if f["count"] > _MAX_LOCATIONS:
            lines.append(f"- …ещё {f['count'] - _MAX_LOCATIONS}")
        lines.append("")
    return "\n".join(lines) + "\n"
