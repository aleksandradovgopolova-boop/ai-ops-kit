#!/usr/bin/env python3
"""Мутационные пробы: проверка, что снятие ОХРАННОЙ проверки роняет свой тест (2026-08-14).

ПОВОД — ЗАМЕР, а не дисциплина ради дисциплины. За 14.08.2026 один PR (#118) прошёл пять кругов
свежего ревью: 36 находок, шесть уровня HIGH, и НИ ОДНУ не поймали 11 обязательных джоб CI. Причина
одна и та же: тест писался по тому же представлению, что и правка, поэтому подтверждал представление,
а не поведение. Восемь правок того дня были «покрыты тестами» и не проверялись ничем — снятие
проверки оставляло тесты зелёными. Раньше это же измеряли шире: мутационное ревью дало 61% убитых
мутантов при заявленной дисциплине «три теста на capability» (`rules/core/field-lessons.yaml`).

ЧТО ЭТО ДЕЛАЕТ. Реестр `quality/mutation-probes.yaml` называет ОХРАННЫЕ проверки — те строки, ради
которых механизм существует, — и тесты, которые обязаны покраснеть, если проверку снять. Прогон
копирует дерево, нейтрализует охрану в копии и запускает названные тесты. Тест остался зелёным =
мутант ВЫЖИЛ = проверка не проверяется ничем. Это ровно тот класс, который CI не видит.

ПОЧЕМУ КОПИЯ, А НЕ ПРАВКА НА МЕСТЕ. За тот же день правка «на месте» дважды оставляла мутацию в
рабочем дереве после исключения — и один раз это заметилось только сверкой с бэкапом. Прогон, который
может испортить дерево, которое проверяет, не годится в контур.

ПОЧЕМУ БАЗОВЫЙ ПРОГОН ОБЯЗАТЕЛЕН. Если названные тесты красные ДО мутации, «мутант убит» ничего не
значит: он был бы убит и без мутации. Такой исход честно называется `not_verified`, а не `killed` —
тот же инвариант, что `unavailable != 0`.

Использование:
  mutation_probe.py <repo> [--only id,id] [--json]
  mutation_probe.py --selftest        # объяснение модуля (проверки — в tests/unit/)
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
            Path(__file__).resolve().parents[2])
PROBES_REL = "quality/mutation-probes.yaml"
KIND = "mutation-probes"
#: Что не копируем в дерево прогона: история, кеши, окружения. Копия нужна только для запуска тестов.
SKIP = shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".venv", "node_modules", ".mypy_cache",
                              ".pytest_cache", ".ruff_cache", "htmlcov", ".ai")


def load_probes(root=None) -> list:
    """Реестр проб. -> список. Файла нет — пустой список (реестр необязателен для child-репо)."""
    p = Path(root or PKG) / PROBES_REL
    if not p.is_file():
        return []
    doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if doc.get("kind") != KIND:
        raise ValueError(f"{PROBES_REL}: kind должен быть '{KIND}', получен '{doc.get('kind')}'")
    return [x for x in (doc.get("probes") or []) if isinstance(x, dict)]


def _pytest(root, tests, python=None, timeout=900):
    """Прогон названных тестов в дереве `root`. -> (rc, хвост вывода)."""
    cmd = [python or sys.executable, "-m", "pytest", *tests, "-q", "-p", "no:cacheprovider"]
    try:
        r = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, timeout=timeout,
                           env={**__import__("os").environ, "PYTHONPATH": str(root)})
    except subprocess.TimeoutExpired:
        return 124, "прогон превысил таймаут"
    return r.returncode, (r.stdout or "")[-400:]


def run(root=None, only=None, python=None, timeout=900) -> dict:
    """Прогнать пробы. -> {"checked": n, "survived": [...], "not_verified": [...], "probes": [...]}.

    `survived` — мутант выжил: охранная проверка снята, а тесты зелёные. Это ДЕФЕКТ КОНТУРА, и он
    возвращается ошибкой, а не предупреждением: механизм, чья охрана ничем не проверяется, держится
    на честном слове автора.
    """
    root = Path(root or PKG)
    probes = [p for p in load_probes(root) if not only or p.get("id") in set(only)]
    out, survived, not_verified = [], [], []
    baseline_cache = {}

    with tempfile.TemporaryDirectory(prefix="mutation-probe-") as tmp:
        work = Path(tmp) / "tree"
        shutil.copytree(root, work, ignore=SKIP, symlinks=True)
        for pr in probes:
            pid = str(pr.get("id"))
            tests = list(pr.get("tests") or [])
            target = work / str(pr.get("file"))
            entry = {"id": pid, "file": pr.get("file"), "tests": tests, "why": pr.get("why")}

            # 1. База: названные тесты обязаны быть ЗЕЛЁНЫМИ до мутации.
            key = tuple(tests)
            if key not in baseline_cache:
                baseline_cache[key] = _pytest(work, tests, python, timeout)
            base_rc, base_tail = baseline_cache[key]
            if base_rc != 0:
                entry.update(outcome="not_verified",
                            reason=f"базовый прогон КРАСНЫЙ (rc={base_rc}) — «мутант убит» ничего не "
                                   f"значил бы: тест падал бы и без мутации. {base_tail[-160:]}")
                not_verified.append(pid); out.append(entry); continue

            # 2. Мутация в КОПИИ, с восстановлением после прогона.
            if not target.is_file():
                entry.update(outcome="not_verified", reason=f"файл {pr.get('file')} не найден")
                not_verified.append(pid); out.append(entry); continue
            src = target.read_text(encoding="utf-8")
            find, repl = str(pr.get("find")), str(pr.get("replace_with"))
            hits = src.count(find)
            if hits != 1:
                entry.update(outcome="not_verified",
                            reason=f"образец охраны встречается {hits} раз(а), ожидался ровно один — "
                                   f"мутация неоднозначна")
                not_verified.append(pid); out.append(entry); continue
            try:
                target.write_text(src.replace(find, repl, 1), encoding="utf-8")
                rc, tail = _pytest(work, tests, python, timeout)
            finally:
                target.write_text(src, encoding="utf-8")

            if rc == 0:
                entry.update(outcome="survived",
                            reason="охрана снята, а названные тесты ЗЕЛЁНЫЕ — проверка не проверяется")
                survived.append(pid)
            else:
                entry.update(outcome="killed", reason=f"тест покраснел (rc={rc}), как и требуется")
            out.append(entry)

    return {"schema_version": 1, "kind": "mutation-probe-report", "checked": len(out),
            "survived": survived, "not_verified": not_verified, "probes": out}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mutation_probe.py")
    ap.add_argument("repo", nargs="?", default=str(PKG))
    ap.add_argument("--only", default="")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ns = ap.parse_args(argv if argv is not None else sys.argv[1:])
    if ns.selftest:
        print(__doc__)
        print("Проверки модуля — в tests/unit/test_mutation_probe.py (в том числе выживший мутант).")
        return 0
    rep = run(ns.repo, only=[x for x in ns.only.split(",") if x])
    if ns.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        for p in rep["probes"]:
            mark = {"killed": "✓", "survived": "✗", "not_verified": "?"}[p["outcome"]]
            print(f"  {mark} {p['id']}: {p['reason']}")
        print(f"ПРОБЫ: проверено {rep['checked']}, выжило {len(rep['survived'])}, "
              f"не проверено {len(rep['not_verified'])}")
    # Выживший мутант — ошибка. «Не проверено» тоже не зелёное: неизвестность не выдаём за успех.
    return 1 if (rep["survived"] or rep["not_verified"]) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
