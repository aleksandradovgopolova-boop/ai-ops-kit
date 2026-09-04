#!/usr/bin/env python3
"""Инвариант: ночной обзор НИКОГДА не пишет в main напрямую (роадмап `nightly-product-review`).

ПОВОД. В `intelligence/nightly_review.py` этот запрет был ПРИНЦИПОМ в комментарии (класс A:
«можно автоматически, но НИКОГДА в main»), а не ПРОВЕРКОЙ. Принцип не краснеет: добавь кто-нибудь
`_git(root, "push", "origin", "main")` в путь автофикса — ни один тест бы не заметил, потому что
существующие тесты гоняют только текущий счастливый/gated путь, а не запрещают новый.

ЧТО ПРОВЕРЯЕМ (статически, AST-обходом РЕАЛЬНОГО исходника ночного пути — не тавтология):

  Путь ночного обзора с записью в git — три файла:
    · intelligence/nightly_review.py  — ОРКЕСТРАТОР. Все git-записи делегирует двум швам ниже;
                                        сам не мутирует git. Любой мутирующий git-глагол прямо в
                                        нём (commit/push/merge/…) — нарушение.
    · engine/worktree.py              — ШОВ A: применяет фиксеры в ИЗОЛИРОВАННОМ worktree на
                                        НЕ-main ветке. `add()` обязан отказывать main/master —
                                        это и делает делегирование безопасным.
    · delivery/pr_open.py             — ШОВ B: только ЧЕРНОВОЙ PR (`draft: True`), НИКОГДА не
                                        мержит. Пуш идёт в переданную рабочую ветку, не в main.

  Правила (каждое краснеет на своём реальном дефекте):
    R1  оркестратор не содержит прямой мутирующей git-операции (чистота делегирования);
    R2  ни один из трёх файлов не зовёт мутирующий git с ЛИТЕРАЛОМ main/master как аргументом
        (ловит `push origin main`, `merge main`, `reset --hard origin/main`, `checkout main`…);
    R3a worktree.add сохраняет отказ main/master;
    R3b pr_open сохраняет `draft: True` в payload и не содержит merge-вызова REST.

ЧЕСТНАЯ ОГОВОРКА. Проверка СТАТИЧЕСКАЯ и распознаёт ИЗВЕСТНЫЕ формы git-мутации: argv
`subprocess`-списка, вызовы `_git(...)`/`gitio.git(...)` с литеральным глаголом, литералы веток.
Запись в main, «отмытую» через вычисляемую переменную (глагол или ветку собрали в рантайме) или
через не-git инструмент, R2 напрямую не увидит — но такой обход ограничен R1 (оркестратор задаёт
ветку f-строкой `ai-ops/nightly-autofix/…`, не main) и R3a (worktree отказывает main). Это
граница механизма, названная явно, а не замолчанная.

R3a проверяет ПРИСУТСТВИЕ сравнения ветки с `main`/`master` в `worktree.add`, а не то, что ветка
из этого сравнения ведёт к отказу (`return`/`raise`): дефект, сохранивший условие, но выпотрошивший
его тело, R3a пропустит. Это тоже названная граница — сам факт отказа на main дополнительно
покрыт поведенческим тестом `worktree.add` в его собственном тест-файле.

Использование:  validate_nightly_no_direct_main_write.py [--json] | --selftest
Возврат 0 — прямых записей в main в ночном пути нет, 1 — есть нарушение (или файл пути не найден).
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
           Path(__file__).resolve().parents[1])

# git-подкоманды, которые МЕНЯЮТ репозиторий (могут закоммитить/сдвинуть/запушить/смёржить в main)
MUTATING_GIT = frozenset({
    "commit", "push", "merge", "rebase", "reset", "checkout", "switch", "branch",
    "tag", "cherry-pick", "revert", "apply", "am", "pull", "clean", "stash",
    "rm", "mv", "gc", "fetch", "update-ref", "fast-import",
})
# ветки, прямая запись в которые ночному пути запрещена (в разных написаниях refspec)
MAIN_REFS = frozenset({"main", "master", "origin/main", "origin/master",
                       "refs/heads/main", "refs/heads/master"})

# Файлы ночного пути ОТНОСИТЕЛЬНО каталога пакета ai_ops_kit.
NIGHTLY_REL = "intelligence/nightly_review.py"   # оркестратор — прямых git-записей быть не должно
WORKTREE_REL = "engine/worktree.py"              # шов A: add отказывает main/master
PR_OPEN_REL = "delivery/pr_open.py"              # шов B: только draft PR, без merge


def nightly_source_base(pkg_root: Path) -> Path:
    """Каталог `ai_ops_kit` с исходником ночного пути. В самом ките — свой; в дочке — из поставки."""
    for cand in (Path(pkg_root) / "ai_ops_kit",
                 Path(pkg_root) / ".ai" / "managed" / "ai_ops_kit"):
        if (cand / NIGHTLY_REL).is_file():
            return cand
    return Path(pkg_root) / "ai_ops_kit"   # дефолт: даст честное «файл не найден», а не пустой зелёный


def _is_main_ref(s: str) -> bool:
    """Литерал ссылается на main/master? Учитываем refspec `HEAD:main`, `origin/main`, `refs/heads/…`."""
    s = s.strip()
    if s in MAIN_REFS:
        return True
    dst = s.rsplit(":", 1)[-1]                 # `src:dst` refspec — целится dst
    if dst in ("main", "master", "refs/heads/main", "refs/heads/master"):
        return True
    if dst in MAIN_REFS:
        return True
    return False


def _string_consts(nodes) -> list[str]:
    """Строковые литералы из списка AST-узлов (Starred/переменные пропускаем — они не литералы)."""
    return [n.value for n in nodes if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def _classify_git_call(node: ast.Call):
    """Если Call — исполнение git, вернуть (verb|None, [строковые литералы аргументов]). Иначе None.

    Распознаёт три формы: `_git(root, "verb", …)`, `gitio.git(root, "verb", …)` и
    `subprocess.run(["git", "verb", …], …)` (и родню Popen/call/check_*)."""
    func = node.func
    # _git(root, "verb", …) / gitio.git(root, "verb", …): глагол — первый аргумент ПОСЛЕ root
    is_git_helper = (
        (isinstance(func, ast.Name) and func.id == "_git")
        or (isinstance(func, ast.Attribute) and func.attr == "git"
            and isinstance(func.value, ast.Name) and func.value.id == "gitio")
    )
    if is_git_helper:
        git_args = node.args[1:]               # выкидываем root
        consts = _string_consts(git_args)
        return (consts[0] if consts else None), consts
    # subprocess.run(["git", "verb", …], …)
    is_subprocess = (
        isinstance(func, ast.Attribute)
        and func.attr in ("run", "Popen", "call", "check_call", "check_output")
        and isinstance(func.value, ast.Name) and func.value.id == "subprocess"
    )
    if is_subprocess and node.args and isinstance(node.args[0], ast.List):
        consts = _string_consts(node.args[0].elts)
        if consts and consts[0] == "git":
            rest = consts[1:]                  # без самого "git"
            return (rest[0] if rest else None), rest
    return None


def _read_ast(path: Path):
    """(tree, None) | (None, сообщение). Файл пути обязан быть — иначе проверять нечего (fail-closed)."""
    if not path.is_file():
        return None, f"файл ночного пути не найден: {path} — проверить нечем"
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path)), None
    except (OSError, SyntaxError) as e:
        return None, f"{path}: не разобран ({type(e).__name__}: {e})"


def _check_orchestrator(base: Path) -> list[dict]:
    """R1 + R2 для intelligence/nightly_review.py: ни прямой мутации, ни литерала main."""
    path = base / NIGHTLY_REL
    tree, err = _read_ast(path)
    if err:
        return [{"rule": "R1", "file": NIGHTLY_REL, "detail": err}]
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        info = _classify_git_call(node)
        if info is None:
            continue
        verb, literals = info
        if verb in MUTATING_GIT:
            out.append({"rule": "R1", "file": NIGHTLY_REL, "line": node.lineno,
                        "detail": f"прямая git-мутация `{verb}` в оркестраторе — все записи "
                                  f"обязаны идти через worktree/pr_open, не напрямую"})
        if verb in MUTATING_GIT and any(_is_main_ref(a) for a in literals):
            tgt = next(a for a in literals if _is_main_ref(a))
            out.append({"rule": "R2", "file": NIGHTLY_REL, "line": node.lineno,
                        "detail": f"git `{verb}` целится в '{tgt}' — прямая запись в main"})
    return out


def _check_main_target(base: Path, rel: str) -> list[dict]:
    """R2 для шва (worktree/pr_open): ни один мутирующий git-вызов не целится литералом в main."""
    path = base / rel
    tree, err = _read_ast(path)
    if err:
        return [{"rule": "R2", "file": rel, "detail": err}]
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        info = _classify_git_call(node)
        if info is None:
            continue
        verb, literals = info
        if verb in MUTATING_GIT and any(_is_main_ref(a) for a in literals):
            tgt = next(a for a in literals if _is_main_ref(a))
            out.append({"rule": "R2", "file": rel, "line": node.lineno,
                        "detail": f"git `{verb}` целится в '{tgt}' — прямая запись в main"})
    return out


def _check_worktree_guard(base: Path) -> list[dict]:
    """R3a: worktree.add сохраняет отказ main/master (иначе делегирование перестаёт быть безопасным)."""
    path = base / WORKTREE_REL
    tree, err = _read_ast(path)
    if err:
        return [{"rule": "R3a", "file": WORKTREE_REL, "detail": err}]
    add_fn = next((n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == "add"), None)
    if add_fn is None:
        return [{"rule": "R3a", "file": WORKTREE_REL,
                 "detail": "функция add() не найдена — не могу подтвердить отказ main/master"}]
    for cmp_node in ast.walk(add_fn):
        # ищем `<branch> in ("main", "master")` (или список) — членство ветки в защищённом наборе
        if isinstance(cmp_node, ast.Compare) and any(isinstance(op, ast.In) for op in cmp_node.ops):
            for comp in cmp_node.comparators:
                if isinstance(comp, (ast.Tuple, ast.List)):
                    lits = _string_consts(comp.elts)
                    if "main" in lits and "master" in lits:
                        return []
    return [{"rule": "R3a", "file": WORKTREE_REL,
             "detail": "worktree.add потерял отказ main/master — ночной автофикс мог бы взять "
                       "worktree на main"}]


def _check_pr_open_draft(base: Path) -> list[dict]:
    """R3b: pr_open держит `draft: True` в payload и не содержит merge-вызова REST."""
    path = base / PR_OPEN_REL
    tree, err = _read_ast(path)
    if err:
        return [{"rule": "R3b", "file": PR_OPEN_REL, "detail": err}]
    draft_forced = False
    merge_signal = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if (isinstance(k, ast.Constant) and k.value == "draft"
                        and isinstance(v, ast.Constant) and v.value is True):
                    draft_forced = True
        # merge PR через GitHub REST — это `PUT /pulls/{n}/merge`. Два ТОЧНЫХ признака, чтобы не
        # ловить слово «merged» в прозе: (1) keyword method="PUT"; (2) литерал-эндпоинт, ЗАВЕРША-
        # ющийся на `/merge` (у f-строки это последний Constant-кусок). pr_open сейчас знает только
        # GET/POST и не мержит — оба признака отсутствуют.
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if (kw.arg == "method" and isinstance(kw.value, ast.Constant)
                        and kw.value.value == "PUT"):
                    merge_signal = 'method="PUT"'
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and node.value.rstrip("/").endswith("/merge"):
            merge_signal = node.value
    out = []
    if not draft_forced:
        out.append({"rule": "R3b", "file": PR_OPEN_REL,
                    "detail": "payload PR больше не форсит `draft: True` — ночной путь мог бы "
                              "открыть НЕ черновой PR"})
    if merge_signal:
        out.append({"rule": "R3b", "file": PR_OPEN_REL,
                    "detail": f"обнаружен merge-вызов REST ({merge_signal}) — ночной путь "
                              f"не должен мержить"})
    return out


def find_violations(pkg_root: Path = PKG) -> list[dict]:
    """Все нарушения инварианта «ночной обзор не пишет в main напрямую». Пусто -> путь чист."""
    base = nightly_source_base(pkg_root)
    findings: list[dict] = []
    findings += _check_orchestrator(base)
    findings += _check_main_target(base, WORKTREE_REL)
    findings += _check_main_target(base, PR_OPEN_REL)
    findings += _check_worktree_guard(base)
    findings += _check_pr_open_draft(base)
    return findings


def run(pkg_root: Path = PKG, as_json: bool = False) -> int:
    findings = find_violations(pkg_root)
    if as_json:
        print(json.dumps({"schema_version": 1, "kind": "nightly-no-direct-main-write",
                          "findings": findings}, ensure_ascii=False, indent=2))
    elif findings:
        print(f"NIGHTLY-MAIN-WRITE: {len(findings)} нарушений инварианта "
              f"«ночной обзор не пишет в main напрямую»:")
        for f in findings:
            loc = f"{f['file']}:{f.get('line', '?')}"
            print(f"  [{f['rule']}] {loc} — {f['detail']}")
    else:
        print("NIGHTLY-MAIN-WRITE-OK: ночной путь (оркестратор + worktree + pr_open) не содержит "
              "прямой записи в main; швы (отказ main, draft-only) на месте.")
    return 1 if findings else 0


def main(argv) -> int:
    if "--selftest" in argv:
        print(__doc__)
        print("Проверки модуля — в tests/unit/test_validate_nightly_no_direct_main_write.py "
              "(AGENTS.md: selftest не живёт в продакшн-модуле).")
        return 0
    return run(PKG, as_json="--json" in argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
