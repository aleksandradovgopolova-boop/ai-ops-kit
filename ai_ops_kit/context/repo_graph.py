#!/usr/bin/env python3
"""repo_graph.py (v3.26.0) — Repository Graph: детерминированный граф зависимостей для impact analysis.

Реализует первую ступень цепочки ContextArchitectureDecision (v3.3.2): repository = источник истины,
детерминированный граф ПЕРЕД любым семантическим поиском. Через stdlib `ast` (Python) и regex (JS/TS):
  - symbols: топ-уровневые функции/классы по файлам (symbol_index);
  - imports: зависимости модулей -> внутренние рёбра (файл A импортирует файл B репо);
  - tests: тест-файлы и что они импортируют;
  - impact(changed): обратный обход рёбер — какие файлы (транзитивно) зависят от изменённого
    (для automatic write-scope / relevant-test-selection в v3.6);
  - affected_tests(changed_files): какие тесты затронуты изменениями (v3.26 Progressive Verification).

Поддерживаемые языки: Python (ast), JavaScript/TypeScript (regex-based import parsing).

CLI: repo_graph.py [root] [--impact tools/x.py] [--affected-tests path1 path2] [--json] | --selftest
"""
from __future__ import annotations

import ast
import json
import os
import re
import sys
from pathlib import Path

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
            Path(__file__).resolve().parents[1])
# v3.30: код движка переехал в пакеты ai_ops_kit/*. Без него граф видел только тонкие
# алиасы в tools/ и терял РЕАЛЬНЫХ импортёров — анализ влияния (--impact) молча
# недооценивал последствия правки.
DEFAULT_SUBDIRS = ("ai_ops_kit",)
JS_TS_EXTENSIONS = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")

# `.ai/` — ОБЛАСТЬ КИТА В ДОЧКЕ, А НЕ КОД ПРОДУКТА (F-022, корень).
#
# Прежде каталога здесь не было, и в дочке граф разбирал доставленную копию кита, ЕЁ БЭКАПЫ
# (`.ai/runtime/backups/<версия>/`) и копии дерева в `.ai/worktrees/<работа>/` наравне с продуктом.
# ЗАМЕР на niti (Next.js/Turborepo, собственного Python нет вовсе):
#   Python  4094 файла в графе, из них 4094 внутри `.ai/` — 100%: 1891 бэкапы, 1650 один worktree,
#           241 managed. То есть весь «граф кода продукта» состоял из кита, отражённого в себя;
#   JS/TS   2507 в графе, 1625 (64%) — копии в `.ai/worktrees`, то есть каждый реальный файл
#           продукта считался примерно трижды.
# Цена не косметическая: по этому графу считаются `impact()` и `affected_tests()` — «какие тесты
# задеты правкой». На таком входе ответ либо про чужие файлы, либо пустой.
# Видимым это стало через предупреждение из СТАРОЙ копии кита (`.ai/managed/tools/context_hybrid.py`
# версии 3.27.7, где докстринг ещё не был raw-строкой): `<unknown>:11: invalid escape sequence`.
# Свой докстринг кит починил 08.08 (8f6aac4), но у дочки лежала копия ДО этой правки — и он
# исправно разбирал её как код продукта.
PY_SKIP_DIRS = (".git", "node_modules", "venv", ".venv", "__pycache__", ".ai", ".claude", "build", "dist", "coverage")
JS_SKIP_DIRS = ("node_modules", "dist", "build", ".next", "coverage", ".ai", ".git", ".venv", "venv", ".claude")


def _source_files(root: Path, subdirs, extensions, skip_dirs, path_filter, uncertainties=None):
    """Prune generated/dependency trees BEFORE traversal; never follow directory symlinks."""
    out = []
    def uncertain(path):
        if uncertainties is not None:
            uncertainties.append(str(path.relative_to(root)))
    def walk_error(exc):
        uncertain(Path(exc.filename) if exc.filename else root)
    for base in ([root / sd for sd in subdirs] if subdirs else [root]):
        if any(part in skip_dirs for part in base.relative_to(root).parts):
            continue
        if base != root and base.is_symlink():
            uncertain(base)
            continue
        if not base.is_dir():
            continue
        for directory, dirs, names in os.walk(base, followlinks=False, onerror=walk_error):
            kept = []
            for d in sorted(dirs):
                if d in skip_dirs:
                    continue
                path = Path(directory) / d
                if path.is_symlink():
                    uncertain(path)
                else:
                    kept.append(d)
            dirs[:] = kept
            for name in names:
                path = Path(directory) / name
                if path.suffix not in extensions:
                    continue
                if path_filter is None or path_filter(str(path.relative_to(root))):
                    out.append(path)
    return sorted(set(out))


def _py_files(root: Path, subdirs=None, path_filter=None, uncertainties=None):
    return _source_files(root, subdirs, (".py",), PY_SKIP_DIRS, path_filter, uncertainties)


def _js_ts_files(root: Path, subdirs=None, path_filter=None, uncertainties=None):
    return _source_files(root, subdirs, JS_TS_EXTENSIONS, JS_SKIP_DIRS, path_filter, uncertainties)


def _analyze(path: Path, *, tree=None):
    """(symbols, imported_module_stems) Python-файла через ast; все Import/ImportFrom (вкл. в функциях)."""
    try:
        # ИМЯ ФАЙЛА ОБЯЗАТЕЛЬНО (F-022). `ast.parse` без него подписывает предупреждения
        # интерпретатора как `<unknown>`, и владелец получал в вывод прогона строку
        # `<unknown>:11: invalid escape sequence`, по которой нельзя ни починить, ни осознанно
        # пропустить: непонятно даже, чей это файл — его продукта или кита.
        if tree is None:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, OSError, UnicodeError):
        return [], set()
    symbols = [n.name for n in tree.body
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                mods.add(_stem(a.name.split(".")))
                mods.update(a.name.split("."))
        elif isinstance(n, ast.ImportFrom):
            if n.module:
                parts = n.module.split(".")
                mods.update(parts)
                mods.update(a.name for a in n.names)
                # `from ai_ops_kit.<пакет> import <модуль>, ...` — модули перечислены в names,
                # а не в module. Без этой ветки все внутренние связи схлопывались бы в один узел
                # `ai_ops_kit`, и --impact терял бы РЕАЛЬНЫХ импортёров (v3.33; тот же класс,
                # что уже ловил переезд в v3.31 — тогда граф видел только алиасы).
                if parts[0] == "ai_ops_kit" and len(parts) == 2:
                    mods.update(a.name for a in n.names)
                else:
                    mods.add(_stem(parts))
            else:
                mods.update(a.name for a in n.names)
    # Загрузка по известному __file__-пути (spec_from_file_location) — реальная зависимость:
    # добавляем ребро к цели, иначе сужение потеряло бы её тесты.
    for target in _known_file_spec_targets(path, tree)[0]:
        mods.add(target.stem)
    return symbols, mods


def _stem(parts):
    """Имя модуля, под которым он известен графу: последний сегмент внутри пакета кита,
    первый — для всего остального (stdlib и сторонние узнаются по верхнему имени)."""
    return parts[-1] if parts[0] == "ai_ops_kit" and len(parts) >= 3 else parts[0]


def _analyze_js(path: Path, *, content=None):
    """v3.26.0: (symbols, imported_module_stems) JS/TS файла через regex.
    Парсит: import ... from '...', import '...', require('...'), export function/class."""
    try:
        if content is None:
            content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return [], set()

    # Symbols: export function/class/const
    symbols = re.findall(r'(?:export\s+)?(?:function|class|const|let|var)\s+(\w+)', content)
    symbols = list(dict.fromkeys(symbols))  # dedup preserving order

    # Imports: import ... from 'module', import 'module', require('module')
    mods = set()
    # Read side-effect imports separately from `from` specifiers: a multiline
    # named import must not swallow a preceding side-effect statement.
    specifiers = set(re.findall(r"\bimport\s*['\"]([^'\"]+)['\"]", content))
    specifiers.update(re.findall(r"\bfrom\s*['\"]([^'\"]+)['\"]", content))
    for m in specifiers:
        if m.startswith(".") or (not m.startswith("/") and not m.startswith("@")):
            mod_name = Path(m).stem if "/" in m else m.split("/")[0]
            mods.add(mod_name)
    # CommonJS: require('...')
    for m in re.findall(r'''require\s*\(\s*['"]([^'"]+)['"]\s*\)''', content):
        if m.startswith(".") or (not m.startswith("/") and not m.startswith("@")):
            mod_name = Path(m).stem if "/" in m else m.split("/")[0]
            mods.add(mod_name)

    return symbols, mods


_FILE_SPEC_NAME = "spec_from_file_location"


class _UnresolvablePath(Exception):
    """Путь загрузки не сводится статически к известному файлу репозитория."""


def _collect_assignments(tree):
    """name -> последнее присвоенное выражение (одиночная цель-Name). Для resolve пути-переменной."""
    assigns = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            assigns[n.targets[0].id] = n.value
    return assigns


def _eval_file_path(node, selfpath: Path, assigns, _depth=0) -> Path:
    """Статически вычислить `Path(__file__)[.resolve()]{.parent|.parents[N]}{ / "seg"}` → абсолютный
    путь. Любая другая форма (вызов, вычисляемый сегмент, неизвестное имя) — _UnresolvablePath."""
    if _depth > 24:
        raise _UnresolvablePath
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        right = node.right
        if not (isinstance(right, ast.Constant) and isinstance(right.value, str)):
            raise _UnresolvablePath
        return _eval_file_path(node.left, selfpath, assigns, _depth + 1) / right.value
    if isinstance(node, ast.Call):
        func = node.func
        if (isinstance(func, ast.Name) and func.id == "Path" and len(node.args) == 1
                and isinstance(node.args[0], ast.Name) and node.args[0].id == "__file__"):
            return selfpath
        if isinstance(func, ast.Attribute) and func.attr == "resolve":
            return _eval_file_path(func.value, selfpath, assigns, _depth + 1)
        raise _UnresolvablePath
    if isinstance(node, ast.Attribute) and node.attr == "parent":
        return _eval_file_path(node.value, selfpath, assigns, _depth + 1).parent
    if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute)
            and node.value.attr == "parents"):
        idx = node.slice
        if not (isinstance(idx, ast.Constant) and isinstance(idx.value, int)):
            raise _UnresolvablePath
        return _eval_file_path(node.value.value, selfpath, assigns, _depth + 1).parents[idx.value]
    if isinstance(node, ast.Name):
        if node.id in assigns:
            return _eval_file_path(assigns[node.id], selfpath, assigns, _depth + 1)
        raise _UnresolvablePath
    raise _UnresolvablePath


def _known_file_spec_targets(path: Path, tree) -> tuple[set[Path], bool]:
    """Разрешённые по `__file__`-пути цели `spec_from_file_location` — это ИЗВЕСТНЫЕ рёбра импорта,
    а не непрослеживаемая динамика (их потребитель и цель статически определены).

    -> (targets_abs, fully_resolvable). fully_resolvable=False, если загрузчик вызван с
    непрослеживаемым путём, целью вне репозитория, без location, импортирован под алиасом или
    использован мимо прямого вызова (алиас/хранение/передача) — тогда граф неполон и файл динамичен.
    """
    targets: set[Path] = set()
    if tree is None:
        return targets, True
    resolvable = True
    assigns = _collect_assignments(tree)
    selfpath = path.resolve()
    call_func_ids: set[int] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            func = n.func
            is_spec = ((isinstance(func, ast.Attribute) and func.attr == _FILE_SPEC_NAME)
                       or (isinstance(func, ast.Name) and func.id == _FILE_SPEC_NAME))
            if is_spec:
                call_func_ids.add(id(func))
                loc = n.args[1] if len(n.args) >= 2 else None
                if loc is None:
                    loc = next((kw.value for kw in n.keywords if kw.arg == "location"), None)
                if loc is None:
                    resolvable = False
                    continue
                try:
                    target = _eval_file_path(loc, selfpath, assigns)
                except _UnresolvablePath:
                    resolvable = False
                    continue
                if target.is_file():
                    targets.add(target)
                else:
                    resolvable = False
    # Имя загрузчика мимо прямого вызова (алиас/хранение/передача) оставляет граф неполным.
    for n in ast.walk(tree):
        if isinstance(n, ast.Attribute) and n.attr == _FILE_SPEC_NAME and id(n) not in call_func_ids:
            resolvable = False
        elif isinstance(n, ast.Name) and n.id == _FILE_SPEC_NAME and id(n) not in call_func_ids:
            resolvable = False
        elif isinstance(n, ast.ImportFrom):
            if any(a.name == _FILE_SPEC_NAME and a.asname and a.asname != _FILE_SPEC_NAME
                   for a in n.names):
                resolvable = False
    return targets, resolvable


def _dependency_uncertainty(path: Path, *, text=None, tree=None) -> str | None:
    """Динамический потребитель известен; непрочитанное дерево ограничить нельзя."""
    if path.is_symlink():
        return "unreadable"
    try:
        if text is None:
            text = path.read_text(encoding="utf-8")
        if path.suffix == ".py":
            if tree is None:
                tree = ast.parse(text, filename=str(path))
            # pytest_plugins загружается фреймворком, без статического import-ребра.
            if any(isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)
                   and n.id == "pytest_plugins" for n in ast.walk(tree)):
                return "test-hook"
            dynamic_names = {"__import__", "eval", "exec", "import_module",
                             "run_path", "run_module"}
            # A builtin loader is also dynamic when retained/passed under another name.
            if any(isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
                   and n.id in ("__import__", "eval", "exec") for n in ast.walk(tree)):
                return "dynamic"
            # Imported loaders may be aliased or passed to another function; the
            # presence of such a binding already makes this graph incomplete.
            if any(isinstance(n, ast.Attribute) and n.attr in dynamic_names
                   for n in ast.walk(tree)):
                return "dynamic"
            if any(isinstance(n, ast.ImportFrom) and any(
                    a.name in dynamic_names for a in n.names) for n in ast.walk(tree)):
                return "dynamic"
            dynamic = any(isinstance(n, ast.Call) and (
                isinstance(n.func, ast.Name) and n.func.id in ("__import__", "eval", "exec") or
                isinstance(n.func, ast.Attribute) and n.func.attr in
                ("import_module", "run_path", "run_module")) for n in ast.walk(tree))
            if dynamic:
                return "dynamic"
            # spec_from_file_location с известным путём от `__file__` к файлу репозитория —
            # статически определённое ребро (_known_file_spec_targets), а не слепое пятно.
            # Непрослеживаемый путь, цель вне репозитория, алиас или использование мимо прямого
            # вызова оставляют файл динамическим.
            if not _known_file_spec_targets(path, tree)[1]:
                return "dynamic"
            return None
        dynamic = re.search(r"\bimport\s*\(|\brequire\s*\((?!\s*['\"])|"
                            r"\brequire\s*\(\s*['\"](?:@|/)|"
                            r"(?:from\s*|import\s*)['\"](?:@|/)|\bexport\s+.*?\bfrom\s", text)
        # JS setupFiles/globalSetup и aliases пока не имеют границы потребителей.
        return "unbounded" if dynamic else None
    except (SyntaxError, OSError, UnicodeError):
        return "unreadable"


def _uncertain_dependency(path: Path) -> bool:
    return _dependency_uncertainty(path) is not None


def build_graph(root=PKG, subdirs=DEFAULT_SUBDIRS, path_filter=None, include_js=True) -> dict:
    """Построить граф зависимостей. v3.26.0: include_js=True добавляет JS/TS файлы."""
    root = Path(root)
    uncertainties = []
    py_files = _py_files(root, subdirs, path_filter=path_filter, uncertainties=uncertainties)
    js_files = _js_ts_files(root, subdirs, path_filter=path_filter, uncertainties=uncertainties) if include_js else []
    all_files = py_files + js_files

    stem_to_rels = {}
    rels = []
    for f in all_files:
        rel = str(f.relative_to(root))
        rels.append((f, rel))
        stem_to_rels.setdefault(f.stem, set()).add(rel)
        if f.name == "__init__.py" or (f.suffix in JS_TS_EXTENSIONS and f.stem == "index"):
            stem_to_rels.setdefault(f.parent.name, set()).add(rel)

    known_rels = {rel for _, rel in rels}
    file_info, symbol_index, import_edges, tests, kinds = {}, {}, {}, {}, {}
    for f, rel in rels:
        # Один снимок содержимого на узел: imports и uncertainty используют тот же AST.
        # Ничего не кешируется между сборками графа.
        try:
            content = f.read_text(encoding="utf-8")
            tree = ast.parse(content, filename=str(f)) if f.suffix == ".py" else None
            if f.suffix in JS_TS_EXTENSIONS:
                syms, mods = _analyze_js(f, content=content)
            else:
                syms, mods = _analyze(f, tree=tree)
            kind = _dependency_uncertainty(f, text=content, tree=tree)
        except (SyntaxError, OSError, UnicodeError):
            syms, mods, kind = [], set(), "unreadable"
        if kind:
            kinds[rel] = kind
        file_info[rel] = {"symbols": syms, "imports": sorted(mods), "language": "js" if f.suffix in JS_TS_EXTENSIONS else "py"}
        for s in syms:
            symbol_index.setdefault(s, []).append(rel)
        internal = {target for m in mods for target in stem_to_rels.get(m, ()) if target != rel}
        if f.suffix == ".py":
            # Importing a descendant executes every existing package initializer,
            # including when the import uses a relative module name.
            for parent in Path(rel).parents:
                initializer = str(parent / "__init__.py")
                if initializer in known_rels:
                    if initializer != rel:
                        internal.add(initializer)
        internal = sorted(internal)
        import_edges[rel] = internal
        stem = Path(rel).stem
        if stem.startswith("test_") or stem.endswith("_test") or stem.endswith(".test") or stem.endswith(".spec"):
            tests[rel] = internal
    kinds.update({rel: "unreadable" for rel in uncertainties})
    return {"kind": "repository-graph", "root": str(root), "subdirs": list(subdirs) if subdirs else ["*"],
            "file_count": len(rels), "files": file_info, "symbol_index": symbol_index,
            "import_edges": import_edges, "tests": tests,
            "uncertainties": sorted(kinds), "uncertainty_kinds": kinds,
            "languages": {"python": len(py_files), "javascript": len(js_files)}}


def affected_tests(graph: dict, changed_files: list) -> list:
    """v3.26.0 Progressive Verification: какие тесты затронуты изменениями.
    changed_files — список относительных путей изменённых файлов.
    Возвращает список тест-файлов, которые импортируют изменённые файлы (транзитивно)."""
    if not changed_files:
        return []
    # Собираем все затронутые файлы (прямые + транзитивные через impact)
    all_affected = set(changed_files) | _impact_many(graph, changed_files)
    # Находим тесты, которые импортируют затронутые файлы
    tests = graph.get("tests", {})
    result = []
    for test_file, test_imports in tests.items():
        # Тест затронут, если любой из его импортов в all_affected
        if any(imp in all_affected for imp in test_imports):
            result.append(test_file)
        # Или если сам тест-файл в changed_files
        elif test_file in changed_files:
            result.append(test_file)
    return sorted(set(result))


def impact(graph: dict, changed_rel: str) -> list:
    """Файлы, которые (транзитивно) импортируют changed_rel — обратный обход рёбер импорта."""
    return sorted(_impact_many(graph, [changed_rel]))


def _impact_many(graph: dict, changed_files) -> set:
    """Один обратный граф и обход для всей группы, а не повтор на каждый загрузчик."""
    edges = graph.get("import_edges", {})
    reverse = {}
    for src, dsts in edges.items():
        for d in dsts:
            reverse.setdefault(d, set()).add(src)
    seen, stack = set(), list(changed_files)
    while stack:
        cur = stack.pop()
        for dep in reverse.get(cur, ()):
            if dep not in seen:
                seen.add(dep)
                stack.append(dep)
    return seen


def main(argv):
    # позиционные аргументы, ИСКЛЮЧАЯ флаги и значение --impact/--affected-tests
    skip = set()
    for flag in ("--impact", "--affected-tests"):
        if flag in argv:
            skip.add(argv.index(flag) + 1)
    args = [a for i, a in enumerate(argv) if not a.startswith("--") and i not in skip]
    root = Path(args[0]) if args else PKG
    g = build_graph(root)
    if "--impact" in argv:
        changed = argv[argv.index("--impact") + 1]
        imp = impact(g, changed)
        if "--json" in argv:
            print(json.dumps({"changed": changed, "impact": imp}, ensure_ascii=False, indent=2))
        else:
            print(f"IMPACT {changed} -> {len(imp)} файлов: {imp}")
        return 0
    if "--affected-tests" in argv:
        idx = argv.index("--affected-tests")
        # Собираем все пути после --affected-tests до следующего флага или конца
        changed_files = []
        for i in range(idx + 1, len(argv)):
            if argv[i].startswith("--"):
                break
            changed_files.append(argv[i])
        at = affected_tests(g, changed_files)
        if "--json" in argv:
            print(json.dumps({"changed_files": changed_files, "affected_tests": at}, ensure_ascii=False, indent=2))
        else:
            print(f"AFFECTED-TESTS: {len(changed_files)} changed -> {len(at)} tests: {at}")
        return 0
    if "--json" in argv:
        print(json.dumps({k: v for k, v in g.items() if k != "files"}, ensure_ascii=False, indent=2))
    else:
        langs = g.get("languages", {})
        print(f"REPO-GRAPH: {g['file_count']} файлов (py={langs.get('python', 0)}, js={langs.get('javascript', 0)}); "
              f"символов={len(g['symbol_index'])}; тестов={len(g['tests'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
