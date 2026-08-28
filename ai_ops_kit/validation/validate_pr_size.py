#!/usr/bin/env python3
"""validate_pr_size.py — одна работа = один малый PR: код+тесты+newsfragment, green сам.

ПОВОД ЗАМЕРЕН (docs/parallel-execution-retro.md §1.7, §2). Лента 5 сложила всю Фазу 4 в ОДИН PR на
+2589 строк — незарегистрированный пакет, четыре модуля на 0% покрытия, пробитые потолки; сессия
закрылась, и весь долг лёг на координатора серией мелких правок. Durable-fix, записанный в ретро, —
не «договоримся сдавать малыми PR», а ПРОВЕРКА размера/охвата PR.

ПРОВЕРКА — ПО ДИФФУ. Берём `git diff --numstat <base>...HEAD` и складываем изменённые строки и файлы,
но ТОЛЬКО по неисключённым путям. Исключены (из `quality/pr-budget.yaml`): newsfragments/ и docs/
(сопроводительное, не «код территории») и координационные файлы (их ведёт координатор чистым
бухгалтерским PR — тот же список, что охраняет validate_parallel_safety). Так честный chore(plan)-PR,
переписывающий план, не краснеет за размер, а лента-«вся-фаза-одним-PR» — краснеет.

Потолки — ЧИСЛАМИ в `quality/pr-budget.yaml` (их читает эта проверка, а не хардкод здесь: два
источника одной правды разошлись бы, как это уже случалось с derived-числами, ретро §1.2). Ратчет
ходит вниз, как func-size.

НЕ БЛОКИРУЕТ по умолчанию (dp-002): новый гейт обкатывается non-blocking. С `--strict` — ненулевой
код на НАСТОЯЩЕМ превышении потолка, но не на «не проверено». Fail-open: без `--base` (или если база
не резолвится git'ом) проверять нечего — это «не проверено», а не «в пределах».
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
           Path(__file__).resolve().parents[2])

_BUDGET = "quality/pr-budget.yaml"


def load_budget(root: Path, path: str | None = None) -> dict:
    """Прочитать реестр потолков PR. -> dict (пустой при отсутствии/битом файле).

    `path` — путь к базовому реестру ВНЕ дерева `root` (в дочкином CI это клон кита: у свежей дочки
    своего `quality/pr-budget.yaml` нет, и без базы проверка структурно не может покраснеть)."""
    p = Path(path) if path else (Path(root) / _BUDGET)
    if not p.is_file():
        return {}
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}


def _norm(p: str) -> str:
    return (p or "").strip().lstrip("./")


def is_exempt(path: str, prefixes: list, paths: set) -> bool:
    """Путь исключён из размера PR? (сопроводительное или координационный файл)."""
    n = _norm(path)
    if n in paths:
        return True
    return any(n.startswith(_norm(pre).rstrip("/") + "/") for pre in prefixes if pre)


def changed_numstat(root: Path, base: str) -> list | None:
    """Изменения ветки против base как [{"path","added","deleted"}]. -> список или None (git недоступен/база не найдена).

    Бинарные файлы numstat помечает '-'/'-' — считаем их 0 строк (строки в них не считаемы)."""
    r = subprocess.run(["git", "-C", str(root), "diff", "--numstat", f"{base}...HEAD"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    out = []
    for line in r.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added = int(parts[0]) if parts[0].isdigit() else 0
        deleted = int(parts[1]) if parts[1].isdigit() else 0
        out.append({"path": parts[2].strip(), "added": added, "deleted": deleted})
    return out


def measure(numstat: list, prefixes: list, exempt_paths: set) -> dict:
    """Размер PR по неисключённым путям. -> {"changed_files","diff_lines","counted","exempt"}."""
    counted, exempt = [], []
    diff_lines = 0
    for f in numstat:
        if is_exempt(f["path"], prefixes, exempt_paths):
            exempt.append(f["path"])
            continue
        counted.append(f["path"])
        diff_lines += f["added"] + f["deleted"]
    return {"changed_files": len(counted), "diff_lines": diff_lines,
            "counted": sorted(counted), "exempt": sorted(exempt)}


def assess(root, base=None, budget_path=None) -> dict:
    root = Path(root)
    budget = load_budget(root, path=budget_path)
    ceilings = (budget.get("ceilings") or {})
    max_files = ceilings.get("max_changed_files")
    max_lines = ceilings.get("max_diff_lines")
    exemptions = (budget.get("exemptions") or {})
    prefixes = exemptions.get("prefixes") or []
    exempt_paths = {_norm(p) for p in (exemptions.get("paths") or [])}

    rep = {"schema_version": 1, "kind": "pr-size",
           "ceilings": {"max_changed_files": max_files, "max_diff_lines": max_lines},
           "diff": None, "findings": []}

    if not isinstance(max_files, int) or isinstance(max_files, bool) \
            or not isinstance(max_lines, int) or isinstance(max_lines, bool):
        rep["findings"].append("реестр потолков PR (quality/pr-budget.yaml) не найден или без чисел "
                               "ceilings — проверять нечего (не «в пределах», а «не проверено»)")
        rep["checked"] = False
        return rep
    rep["checked"] = True

    if base:
        numstat = changed_numstat(root, base)
        if numstat is None:
            rep["diff"] = {"base": base, "available": False}
            rep["findings"].append(f"дифф против '{base}' не прочитан — размер PR не проверен "
                                   f"(не «в пределах»)")
        else:
            m = measure(numstat, prefixes, exempt_paths)
            over_files = m["changed_files"] > max_files
            over_lines = m["diff_lines"] > max_lines
            rep["diff"] = {"base": base, "available": True, "over": over_files or over_lines, **m}
            if over_files:
                rep["findings"].append(
                    f"PR меняет {m['changed_files']} файлов (потолок {max_files}): «вся фаза одним "
                    f"PR» копит долг на координатора. Одна работа = один малый PR — код своей "
                    f"территории + тесты + newsfragment, green сам (docs/parallel-execution-retro.md §2).")
            if over_lines:
                rep["findings"].append(
                    f"PR меняет {m['diff_lines']} строк (потолок {max_lines}): разбей на несколько "
                    f"PR по одной работе. Дамп на +2589 строк одним PR — тот самый повод "
                    f"(docs/parallel-execution-retro.md §1.7). newsfragments/docs/координация в счёт не идут.")
    return rep


def render(rep: dict) -> str:
    if not rep.get("checked"):
        return "PR-SIZE: не проверено — " + "; ".join(rep["findings"])
    if not rep["findings"]:
        d = rep.get("diff") or {}
        if d.get("available"):
            return (f"PR-SIZE-OK: {d['changed_files']} файлов / {d['diff_lines']} строк "
                    f"(потолки {rep['ceilings']['max_changed_files']}/{rep['ceilings']['max_diff_lines']}), "
                    f"в пределах.")
        return f"PR-SIZE-OK: потолки заданы ({rep['ceilings']}), дифф не проверялся."
    return "PR-SIZE: найдено:\n" + "\n".join("  ✗ " + f for f in rep["findings"])


def main(argv):
    root, base, budget_path, js, strict = ".", None, None, False, False
    it = iter(argv[1:])
    for a in it:
        if a == "--base":
            base = next(it, None)
        elif a == "--budget":
            budget_path = next(it, None)
        elif a == "--json":
            js = True
        elif a == "--strict":
            strict = True
        elif not a.startswith("-"):
            root = a
    import json
    rep = assess(root, base=base, budget_path=budget_path)
    print(json.dumps(rep, ensure_ascii=False, indent=2) if js else render(rep))
    # НЕ БЛОКИРУЕТ по умолчанию (dp-002). С --strict — ненулевой код только на настоящем превышении
    # потолка (checked + diff.over), но не на «не проверено».
    if strict and rep.get("checked") and (rep.get("diff") or {}).get("over"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
