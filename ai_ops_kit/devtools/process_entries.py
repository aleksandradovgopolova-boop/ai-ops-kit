"""Процессные входы модулей кита: кто РЕАЛЬНО запускает модуль, у которого нет импортёров (#1526).

ЗАЧЕМ. Сторож «построено ≠ проведено» (tests/contracts/test_dormant_inventory.py) считал легит-входом
ЛЮБОЙ модуль из `validation/` и `devtools/` — «их зовут процессом». Проверки, что их кто-то зовёт, не
было: модуль, который никто не запускает, проходил молча, если лежал в одной из этих папок.

ЧТО СЧИТАЕТСЯ ВХОДОМ. Ссылка на модуль из места, которое его запускает:
  * машинные файлы вне пакета и тестов — полное имя `ai_ops_kit.x.y` или путь `ai_ops_kit/x/y.py`;
    в реестрах, quality, CI, скриптах и шаблонах (BY_LEAF_DIRS) — и голое имя модуля, как реестр
    зовёт валидатор;
  * код ДРУГОГО модуля пакета — строкой с полным именем или голым именем (динамический запуск);
  * документация и квалификационные материалы — только КОМАНДА запуска (`-m ai_ops_kit.x.y` или
    `python3 …/ai_ops_kit/x/y.py`): упоминание в описи файлов или в истории запуском не является;
  * тесты, которые гоняют валидатор на САМОМ ките (живые списки в LIVE_RUN_FILES): так CI держит
    проверку репозитория;
  * ночные замеры (`pytest.mark.nightly`, их гоняет nightly-quality): так держится, например,
    bench_lite — замер решений движка, где ложных «зелёных» обязано быть ноль.
История (history/, CHANGELOG, newsfragments), наблюдения дочек (findings/) и сгенерированная витрина возможностей входом не
считаются: в них модуль упомянут, а не запущен.
"""
from __future__ import annotations

import ast
import re
from fnmatch import fnmatch
from pathlib import Path

PKG_NAME = "ai_ops_kit"
MACHINE_SUFFIXES = frozenset({".py", ".sh", ".yaml", ".yml", ".json", ".toml", ".cfg", ".ini", ""})
PROSE_SUFFIXES = frozenset({".md", ".txt", ".rst"})
NOT_ENTRY_DIRS = frozenset({"tests", PKG_NAME, "history", "newsfragments", "findings"})
# Где кит зовёт модуль ГОЛЫМ именем (реестр валидаторов, гейты, скрипты, CI). В прочих машинных
# файлах голое имя — просто слово («garden» в наблюдении дочки), а не запуск.
BY_LEAF_DIRS = frozenset({"registry", "quality", "manifest", ".github", "scripts", "packages",
                          "templates", "hooks", "presets", "workflows", "config"})
NOT_ENTRY_FILES = frozenset({"CHANGELOG.md", "FILE_INDEX.md", "docs/capability-map.md"})
# Описи и потолки ратчетов перечисляют модули, а не запускают их: журнал подъёмов поставки, базы
# размеров функций и модулей, карта слоёв.
NOT_ENTRY_GLOBS = ("packages/*baseline*.yaml", "quality/*baseline*.yaml", "packages/layering.yaml",
                   "quality/delivery-budget.yaml", "quality/*-ceilings.yaml")
LIVE_RUN_FILES = (
    "tests/unit/test_validator_runtime_contract.py",
    "tests/unit/test_validator_contract.py",
    "tests/contracts/test_safety_validators_green_on_live_kit.py",
)


def _rel(p: Path, root: Path) -> str:
    return p.relative_to(root).as_posix()


def _outside_files(root: Path, skip_dirs: frozenset[str]):
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        parts = p.relative_to(root).parts
        rel = _rel(p, root)
        if (set(parts[:-1]) & skip_dirs or parts[0] in NOT_ENTRY_DIRS or rel in NOT_ENTRY_FILES
                or any(fnmatch(rel, g) for g in NOT_ENTRY_GLOBS)):
            continue
        if p.suffix in MACHINE_SUFFIXES or p.suffix in PROSE_SUFFIXES:
            yield p


def _package_strings(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except (SyntaxError, OSError):
        return set()
    return {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}


DOTTED = re.compile(r"ai_ops_kit(?:\.[A-Za-z_]\w*)+")
SLASHED = re.compile(r"ai_ops_kit(?:/[A-Za-z_]\w*)+(?=\.py)")
RUN = re.compile(r"-m\s+(ai_ops_kit(?:\.[A-Za-z_]\w*)+)|python3?\s+\S*?(ai_ops_kit(?:/[A-Za-z_]\w*)+)\.py")
WORD = re.compile(r"(?<![\w./-])([a-z_][a-z0-9_]*)(?![\w-])")
QUOTED = re.compile(r"[\"']([a-z_][a-z0-9_]*)[\"']")
IMPORT = re.compile(r"^\s*(?:from\s+(ai_ops_kit[\w.]*)\s+import\s+([^\n#]+)|import\s+(ai_ops_kit[\w.]*))", re.M)


class _Resolver:
    """Имя из текста -> модуль пакета: `ai_ops_kit.x.y.func` и `ai_ops_kit/x/y` -> `ai_ops_kit.x.y`."""

    def __init__(self, modules):
        self.modules = set(modules)
        self.by_leaf: dict[str, set[str]] = {}
        for m in modules:
            self.by_leaf.setdefault(m.rsplit(".", 1)[-1], set()).add(m)

    def dotted(self, name: str) -> str | None:
        name = name.replace("/", ".")
        while name and name not in self.modules:
            name = name.rsplit(".", 1)[0] if "." in name else ""
        return name or None

    def names(self, text: str) -> set[str]:
        hits = {self.dotted(n) for n in DOTTED.findall(text)} | {self.dotted(n) for n in SLASHED.findall(text)}
        return {h for h in hits if h}

    def leaves(self, words) -> set[str]:
        return {m for w in words for m in self.by_leaf.get(w, ())}


def process_entries(root: Path, modules: dict[str, Path], skip_dirs: frozenset[str]) -> dict[str, str]:
    """Для каждого модуля с процессным входом — где этот вход (первый найденный файл).

    Один проход по каждому файлу: из текста извлекаются имена модулей, а не каждый модуль ищется в
    каждом файле (иначе сотни модулей на тысячи файлов — минуты на каждый прогон сторожа).
    """
    found: dict[str, str] = {}
    res = _Resolver(modules)

    def note(hits, where: str, owner: str | None = None) -> None:
        for m in hits:
            if m != owner:
                found.setdefault(m, where)

    for p in _outside_files(root, skip_dirs):
        text = p.read_text(encoding="utf-8", errors="ignore")
        rel = _rel(p, root)
        if p.suffix in PROSE_SUFFIXES:
            if PKG_NAME in text:
                note({res.dotted(a or b) for a, b in RUN.findall(text)} - {None}, rel)
            continue
        note(res.names(text), rel)
        if p.relative_to(root).parts[0] in BY_LEAF_DIRS and p.suffix in {".yaml", ".yml", ".json", ".sh", ".toml", ""}:
            note(res.leaves(set(WORD.findall(text))), rel)
    for owner, path in modules.items():
        strings = _package_strings(path)
        hits = res.leaves(strings)
        for s in strings:
            hits |= res.names(s)
        note(hits, _rel(path, root), owner)
    for test in sorted((root / "tests").rglob("*.py")):
        src = test.read_text(encoding="utf-8", errors="ignore")
        if "pytest.mark.nightly" not in src:
            continue
        hits = set()
        for base, names, plain in IMPORT.findall(src):
            if plain:
                hits.add(res.dotted(plain))
                continue
            hits.add(res.dotted(base))
            for n in re.findall(r"[A-Za-z_]\w*", names):
                hits.add(res.dotted(f"{base}.{n}"))
        note(hits - {None}, "ночной прогон: " + _rel(test, root))
    live = "\n".join((root / f).read_text(encoding="utf-8") for f in LIVE_RUN_FILES if (root / f).is_file())
    note(res.leaves(set(QUOTED.findall(live))), "живой прогон на ките: " + ", ".join(LIVE_RUN_FILES))
    return found
