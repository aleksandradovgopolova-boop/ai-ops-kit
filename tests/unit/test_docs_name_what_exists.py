"""Документация не называет несуществующего — ни файла, ни команды, ни страницы.

ПОВОД — ЗАМЕР 19.08.2026:
  * `mkdocs.yml` объявлял шесть страниц, которых нет НИ ОДНОЙ (`api/orchestrator`,
    `api/execution-pipeline`, `api/preflight`, `api/tool-loop`, `api/usage-ledger`,
    `api/benchmarks`), и `quickstart.md` против файла `QUICKSTART.md` — на macOS совпадает,
    на Linux нет;
  * руководство дочки учило звать `python3 .ai/managed/tools/ai_ops_cli.py …`, хотя точка входа
    давно `./ai-ops`. Владелец, скопировавший первую строку, получал более длинный путь к тому же —
    или ошибку, если managed-слоя рядом нет;
  * `docs/api/contracts.md` учил плоскому импорту `from contracts import …` — наследию
    совместимости, объявленному уходящим.

Сборка документации не запускалась НИГДЕ, поэтому обещание шести разделов держалось ровно до
первой попытки собрать. Отсюда и класс: документация — тоже объявление, и объявление без проверки
стареет молча.

ЧТО СЧИТАЕТСЯ ЖИВОЙ ДОКУМЕНТАЦИЕЙ. `README.md` и `docs/**`, кроме записей о прошлом: журнал
версий, change-brief'ы (описание изменения на день, когда оно задумывалось) и отчёт аудита
(он ЦИТИРУЕТ найденное, в том числе неверные пути). Требовать от записи о прошлом соответствия
сегодняшнему дереву значило бы переписывать прошлое.

Три обязательных теста на capability (AGENTS.md):
  * positive     — каждая страница навигации, каждая ссылка и каждый путь существуют;
  * fail-closed  — устаревшая точка входа, плоский импорт и путь, переехавший в пакет, ловятся;
  * side-effect  — сборка документации объявлена в CI, а не только в инструкции.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

PKG = Path(__file__).resolve().parents[2]
DOCS = PKG / "docs"

# Записи о прошлом: не обещания о настоящем.
PAST_RECORDS = ("docs/changelog", "docs/change-briefs", "docs/audit-report.md")

LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
CODE_PATH = re.compile(r"`([A-Za-z0-9_][A-Za-z0-9_./-]*\.(?:py|md|ya?ml|json|sh|toml|cfg))`")
LEGACY_ENTRY = re.compile(r"python3?\s+\S*\.ai/managed/tools/ai_ops_cli\.py\s+([a-z][a-z-]*)")
FLAT_IMPORT = re.compile(r"^\s*from\s+(contracts|workitem|run_plan|orchestrator|gate_executor)\s+import\b",
                         re.M)


def _live_docs():
    files = [PKG / "README.md"]
    files += [p for p in sorted(DOCS.rglob("*.md"))
              if not any(p.relative_to(PKG).as_posix().startswith(s) for s in PAST_RECORDS)]
    return [f for f in files if f.is_file()]


LIVE = _live_docs()


def _top_level_names():
    return {p.name for p in PKG.iterdir()}


def _intents():
    tree = ast.parse((PKG / "ai_ops_kit" / "cli" / "ai_ops_cli.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) == "INTENTS":
            return set(ast.literal_eval(node.value))
    raise AssertionError("INTENTS не найдены")


# ─── positive ──────────────────────────────────────────────────────────────────────────────────

def test_the_corpus_is_not_empty():
    """Зелёный обход пустого множества — это не «чисто», это «нечего проверять»."""
    assert len(LIVE) > 15, f"живой документации найдено {len(LIVE)} файлов — обход ослеп"


def test_every_page_in_the_navigation_exists():
    """И с ТЕМ ЖЕ регистром: на macOS расхождение не видно, на Linux сборка падает."""
    cfg = yaml.safe_load((PKG / "mkdocs.yml").read_text(encoding="utf-8"))
    pages, missing = [], []

    def walk(node):
        if isinstance(node, str):
            pages.append(node)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)

    walk(cfg.get("nav") or [])
    for page in pages:
        path = DOCS / page
        if not path.is_file() or path.name not in {p.name for p in path.parent.iterdir()}:
            missing.append(page)
    assert not missing, (
        f"навигация называет страницы, которых нет: {missing}. Заглушка на их месте была бы хуже: "
        f"страница, которая существует и ничего не говорит, тратит время читателя дважды")


def test_every_markdown_link_resolves():
    broken = []
    for f in LIVE:
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            for target in LINK.findall(line):
                t = target.split("#")[0].strip()
                if not t or t.startswith(("http://", "https://", "mailto:")):
                    continue
                if not (f.parent / t).exists():
                    broken.append(f"{f.relative_to(PKG)}:{i} -> {t}")
    assert not broken, broken


def test_every_quoted_repository_path_exists():
    """Путь в обратных кавычках — утверждение о дереве. Проверяются те, чей корень существует:
    `discovery/hypotheses.md` — артефакт, который кит СОЗДАЁТ в чужом репозитории, а не файл кита."""
    roots = _top_level_names()
    missing = []
    for f in LIVE:
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            for t in CODE_PATH.findall(line):
                head = t.split("/")[0]
                if "/" not in t or head not in roots:
                    continue
                if not (PKG / t).exists() and not (f.parent / t).exists():
                    missing.append(f"{f.relative_to(PKG)}:{i} -> {t}")
    assert not missing, missing


# ─── fail-closed ───────────────────────────────────────────────────────────────────────────────

def test_no_document_teaches_the_legacy_entry_point():
    """`./ai-ops <интент>` — точка входа. Длинный путь через managed-слой ещё работает, но учить
    ему значит учить тому, что уйдёт: он ломается там, где managed-слоя рядом нет."""
    intents = _intents()
    stale = []
    for f in LIVE:
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            m = LEGACY_ENTRY.search(line)
            if m and m.group(1) in intents:
                stale.append(f"{f.relative_to(PKG)}:{i} -> ./ai-ops {m.group(1)}")
    assert not stale, (
        f"документация учит устаревшей точке входа: {stale}")


def test_no_document_teaches_a_flat_import():
    """Плоское имя модуля — уходящий слой совместимости (docs/api/public-surface.md).
    Документация, которая ему учит, производит новых пользователей уходящего."""
    flat = []
    for f in LIVE:
        for m in FLAT_IMPORT.finditer(f.read_text(encoding="utf-8")):
            flat.append(f"{f.relative_to(PKG)} -> {m.group(0).strip()}")
    assert not flat, (
        f"документация учит плоскому импорту: {flat}. Пакетное имя показывает связь; плоское её прячет")


def test_a_path_that_moved_into_the_package_is_caught():
    """Отдельный класс: путь, который ПЕРЕЕХАЛ. Его корня уже нет, поэтому проверка существования
    молчит, — а документация продолжает называть место, откуда файл ушёл."""
    roots = _top_level_names()
    moved = []
    by_name = {}
    for p in PKG.rglob("*.py"):
        if ".git" in p.parts or "__pycache__" in p.parts:
            continue
        by_name.setdefault(p.name, []).append(p.relative_to(PKG).as_posix())
    for f in LIVE:
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            for t in CODE_PATH.findall(line):
                if "/" not in t or t.split("/")[0] in roots or not t.endswith(".py"):
                    continue
                if (PKG / t).exists():
                    continue
                real = by_name.get(t.split("/")[-1])
                if real:
                    moved.append(f"{f.relative_to(PKG)}:{i} -> {t} (теперь {real[0]})")
    assert not moved, moved


# ─── side-effect proof ─────────────────────────────────────────────────────────────────────────

def test_the_documentation_build_runs_in_ci():
    """Инструкция «pip install mkdocs && mkdocs build» в шапке конфига не запускается ничем.

    Ровно поэтому шесть несуществующих страниц прожили до аудита: собрать документацию было
    некому. Проверка объявленная обязана исполняться — это главный инвариант продукта.
    """
    wf = PKG / ".github" / "workflows" / "docs.yml"
    assert wf.is_file(), "нет джобы сборки документации — конфиг снова никем не проверяется"
    text = wf.read_text(encoding="utf-8")
    assert "mkdocs build" in text, "джоба есть, а сборки в ней нет"
    assert "--strict" in text, (
        "сборка без --strict проглатывает битую ссылку предупреждением: джоба была бы зелёной "
        "ровно на том дефекте, ради которого заведена")
    data = yaml.safe_load(text)
    on = data.get("on") or data.get(True)
    assert on and ("pull_request" in on), "джоба не срабатывает на pull request"


def test_the_config_and_the_navigation_agree_on_case():
    """Регистр — не косметика: на macOS расхождение невидимо, на Linux сборка падает."""
    cfg = (PKG / "mkdocs.yml").read_text(encoding="utf-8")
    assert "quickstart.md" not in cfg, "нижний регистр вернулся — на Linux страница не найдётся"
    assert "QUICKSTART.md" in cfg
