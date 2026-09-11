# -*- coding: utf-8 -*-
"""Контракт: ни одного НЕОГРАНИЧЕННОГО git-субпроцесса в `ai_ops_kit/`.

Работа `p1-gitio-timeout-consolidation` (P1 из аудита 10 ролей).

НАХОДКА. `shared/gitio.py` появился как ЕДИНЫЙ вход к git с таймаутом по умолчанию: зависший
git-субпроцесс (сеть/lock/hook) вешает весь прогон навсегда, и `gitio.git`/`gitio.run` заменяют
блокировку на rc=124. Но консолидация не была доведена — десятки модулей звали
`subprocess.run(["git", …])` НАПРЯМУЮ, и МНОГИЕ без `timeout=`. Этот тест держит инвариант, чтобы
регрессия ловилась в тот же день, а не годом позже висящим CI.

ИНВАРИАНТ (структурный, по AST). Прямой вызов `subprocess.run/Popen/call/check_call/check_output`,
у которого ПЕРВЫЙ позиционный аргумент — литерал-список с первым элементом-строкой `"git"`, ОБЯЗАН
задавать `timeout=` (тогда зависание превращается в ошибку, а не в вечную блокировку). Иначе — красный.

ПОЧЕМУ НЕ ЧЕРЕЗ `validate_*`. Это чистая структурная проверка исходников; registered-валидатор в
`ai_ops_kit/validation/` тянет реестровый каскад (package-surface, standalone-контракт, счётчики) —
здесь он не нужен. Место такой проверки — `tests/contracts/`, рядом с прочими структурными
контрактами (`test_no_monolith_funnel`, `test_suite_asserts`).

ALLOWLIST (обоснование — здесь, а не «магический список»):
  * `ai_ops_kit/shared/gitio.py` — САМ единый хелпер; здесь `["git", …]` и живёт (с timeout=).
  * каталог `ai_ops_kit/validation/` — двурежимные валидаторы под `import _bootstrap` (отдельная
    зона запуска процессом; многие поднимают одноразовые репозитории `git init/commit` в tmp).
Остаточные RAW-места (`git show` — дословный вывод; `git status --porcelain` — значимая ведущая
колонка; broker с `env=scrub_env`) в allowlist НЕ входят: они проходят ПОТОМУ, что задают `timeout=`.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract]

KIT = Path(__file__).resolve().parents[2]
PKG = KIT / "ai_ops_kit"

# Пути, где `["git", …]` без timeout= допустим по обоснованию (см. докстринг). Относительно PKG.
ALLOWLIST = (
    "shared/gitio.py",     # сам единый хелпер — источник вызова git
    "validation/",         # двурежимные валидаторы (import _bootstrap), одноразовые tmp-репозитории
)

_SUBPROCESS_METHODS = {"run", "Popen", "call", "check_call", "check_output"}


def _is_allowlisted(rel: str) -> bool:
    return any(rel == a or rel.startswith(a) for a in ALLOWLIST)


def _is_git_subprocess_call(node: ast.Call) -> bool:
    """Call — это `subprocess.<run|Popen|…>([<литерал "git">, …], …)`?"""
    func = node.func
    is_subprocess = (
        isinstance(func, ast.Attribute)
        and func.attr in _SUBPROCESS_METHODS
        and isinstance(func.value, ast.Name)
        and func.value.id == "subprocess"
    )
    if not (is_subprocess and node.args and isinstance(node.args[0], ast.List)):
        return False
    elts = node.args[0].elts
    return bool(elts) and isinstance(elts[0], ast.Constant) and elts[0].value == "git"


def _has_timeout(node: ast.Call) -> bool:
    return any(kw.arg == "timeout" for kw in node.keywords)


def _unbounded_git_calls(tree: ast.AST) -> list[int]:
    """Номера строк git-субпроцессов без timeout= в дереве."""
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_git_subprocess_call(node) and not _has_timeout(node):
            bad.append(node.lineno)
    return bad


def _iter_sources():
    for p in sorted(PKG.rglob("*.py")):
        yield p, str(p.relative_to(PKG)).replace("\\", "/")


def test_no_unbounded_git_subprocess_in_package():
    """Каждый прямой git-субпроцесс в ai_ops_kit/ (вне allowlist) задаёт timeout=."""
    offenders = {}
    for path, rel in _iter_sources():
        if _is_allowlisted(rel):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        lines = _unbounded_git_calls(tree)
        if lines:
            offenders[rel] = lines
    assert not offenders, (
        "Неограниченный git-субпроцесс (без timeout=) — зависший git повесит весь прогон. "
        "Проведи вызов через shared.gitio.git/gitio.run ИЛИ задай timeout= явно. Нарушения: "
        + "; ".join(f"{rel}:{lines}" for rel, lines in sorted(offenders.items()))
    )


def test_detector_flags_git_call_without_timeout():
    """Позитивный кейс: git-субпроцесс без timeout= детектируется как нарушение."""
    src = 'import subprocess\nsubprocess.run(["git", "status"])\n'
    assert _unbounded_git_calls(ast.parse(src)) == [2]


def test_detector_passes_git_call_with_timeout():
    """Тот же вызов с timeout= нарушением НЕ считается."""
    src = 'import subprocess\nsubprocess.run(["git", "status"], timeout=5)\n'
    assert _unbounded_git_calls(ast.parse(src)) == []


def test_detector_ignores_non_git_subprocess():
    """Не-git субпроцесс без timeout= инвариант не трогает (речь только про git)."""
    src = 'import subprocess\nsubprocess.run(["gh", "pr", "list"])\n'
    assert _unbounded_git_calls(ast.parse(src)) == []


def test_detector_ignores_completed_process_construction():
    """`subprocess.CompletedProcess(["git", …])` — конструктор результата, не запуск: не флагаем."""
    src = 'import subprocess\nsubprocess.CompletedProcess(["git", "x"], 124, "", "")\n'
    assert _unbounded_git_calls(ast.parse(src)) == []
