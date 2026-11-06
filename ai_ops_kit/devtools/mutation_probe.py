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

ПОДТВЕРЖДЕНИЕ KILL. Нужны rc=1 и свежий JUnit failure от pytest test call без collection/fixture
errors. unittest.TestCase пока не поддержан: его setUp/tearDown pytest тоже представляет как
call failure, поэтому такой прогон честно not_verified. ImportError внутри обычного test call
может убить мутанта; ошибка import при collection/setup и некомпилируемый Python — не могут.

Использование:
  mutation_probe.py <repo> [--only id,id] [--json]
  mutation_probe.py --selftest        # объяснение модуля (проверки — в tests/unit/)
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
import xml.etree.ElementTree as ET

import yaml

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
            Path(__file__).resolve().parents[2])
PROBES_REL = "quality/mutation-probes.yaml"
KIND = "mutation-probes"
#: Что не копируем в дерево прогона: история, кеши, окружения. Копия нужна только для запуска тестов.
SKIP = shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".venv", "node_modules", ".mypy_cache",
                              ".pytest_cache", ".ruff_cache", "htmlcov", ".ai", "build", "dist")
# JUnit не отличает тело unittest от setUp/tearDown. Отмечаем тип item ДО запуска, не парсим
# текст traceback. Малый временный pytest plugin не входит в проверяемое дерево.
_EVIDENCE_PLUGIN = '''import unittest

def pytest_collection_modifyitems(items):
    for item in items:
        cls = getattr(item, "cls", None)
        kind = "unittest" if isinstance(cls, type) and issubclass(cls, unittest.TestCase) else "pytest"
        item.user_properties.append(("mutation_probe_kind", kind))
'''


def load_probes(root=None) -> list:
    """Реестр проб. -> список. Файла нет — пустой список (реестр необязателен для child-репо)."""
    p = Path(root or PKG) / PROBES_REL
    if not p.is_file():
        return []
    doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if doc.get("kind") != KIND:
        raise ValueError(f"{PROBES_REL}: kind должен быть '{KIND}', получен '{doc.get('kind')}'")
    return [x for x in (doc.get("probes") or []) if isinstance(x, dict)]


def _execution_evidence(report):
    """JUnit: failure — выполненный test call, error — collection/setup/teardown.

    Считаем реальные testcase, а не строку stdout или summary counters. ImportError внутри
    test call допустим; сломанный import на collection/setup НЕ доказывает обнаружение мутации.
    """
    try:
        doc = ET.parse(report).getroot()
    except (OSError, ET.ParseError):
        return None
    if doc.tag not in {"testsuites", "testsuite"}:
        return None
    cases = list(doc.iter("testcase"))
    if any(not case.get("name") for case in cases):
        return None
    # Отсутствующий marker тоже unknown: plugin мог быть выключен addopts или чужим hook.
    unsupported = [case for case in cases if case.find(
        "properties/property[@name='mutation_probe_kind'][@value='pytest']") is None]
    executed = [case for case in cases if case not in unsupported
                and case.find("skipped") is None and case.find("error") is None]
    return {"executed": len(executed), "errors": len(list(doc.iter("error"))),
            "unsupported": len(unsupported),
            "failed_tests": [f"{case.get('classname', '')}::{case.get('name')}"
                             for case in executed if case.find("failure") is not None]}


def _pytest(root, tests, python=None, timeout=900):
    """Прогон названных тестов. -> (rc, хвост вывода, execution evidence или None)."""
    # Отдельный свежий путь ДЛЯ КАЖДОГО запуска: база/другая проба не могут оставить evidence.
    # За пределами дерева: отчёт не меняет проверяемые файлы и не попадает в следующую копию.
    with tempfile.TemporaryDirectory(prefix="mutation-pytest-") as tmp:
        report = Path(tmp) / "junit.xml"
        (Path(tmp) / "_mutation_probe_evidence.py").write_text(_EVIDENCE_PLUGIN, encoding="utf-8")
        cmd = [python or sys.executable, "-m", "pytest", *tests, "-q", "-p", "no:cacheprovider",
               "-p", "_mutation_probe_evidence", "--junitxml", str(report)]
        # Равная длина мутации в ту же секунду не инвалидирует mtime+size .pyc.
        try:
            r = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, timeout=timeout,
                               env={**__import__("os").environ,
                                    "PYTHONPATH": __import__("os").pathsep.join((tmp, str(root))),
                                    "PYTHONDONTWRITEBYTECODE": "1"})
        except subprocess.TimeoutExpired:
            return 124, "прогон превысил таймаут", None
        return r.returncode, ((r.stdout or "") + (r.stderr or ""))[-400:], _execution_evidence(report)


def _run_serial(root, probes, python=None, timeout=900) -> dict:
    """Прогнать пробы. -> {"checked": n, "survived": [...], "not_verified": [...], "probes": [...]}.

    `survived` — мутант выжил: охранная проверка снята, а тесты зелёные. Это ДЕФЕКТ КОНТУРА, и он
    возвращается ошибкой, а не предупреждением: механизм, чья охрана ничем не проверяется, держится
    на честном слове автора.
    """
    root = Path(root or PKG)
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

            if not target.resolve().is_relative_to(work.resolve()):
                entry.update(outcome="not_verified", reason="mutation target escapes isolated copy")
                not_verified.append(pid); out.append(entry); continue

            # 1. База: названные тесты обязаны быть ЗЕЛЁНЫМИ до мутации.
            key = tuple(tests)
            if key not in baseline_cache:
                baseline_cache[key] = _pytest(work, tests, python, timeout)
            base_rc, base_tail, base_evidence = baseline_cache[key]
            if (base_rc != 0 or not base_evidence or not base_evidence["executed"]
                    or base_evidence["errors"] or base_evidence["unsupported"]
                    or base_evidence["failed_tests"]):
                entry.update(outcome="not_verified",
                            reason=f"базовый прогон КРАСНЫЙ или не подтверждён (rc={base_rc}) — "
                                   f"нужны исполненные зелёные pytest tests (unittest не поддержан). "
                                   f"{base_tail[-160:]}")
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
            mutated = src.replace(find, repl, 1)
            if target.suffix == ".py":
                try:
                    compile(mutated, str(pr.get("file")), "exec", dont_inherit=True)
                except (SyntaxError, ValueError) as exc:
                    entry.update(outcome="not_verified", reason=f"некорректная Python-мутация: {exc}")
                    not_verified.append(pid); out.append(entry); continue
            try:
                target.write_text(mutated, encoding="utf-8")
                rc, tail, evidence = _pytest(work, tests, python, timeout)
            finally:
                target.write_text(src, encoding="utf-8")

            entry["execution"] = evidence
            if rc == 124:
                entry.update(outcome="not_verified", reason="mutant run timed out; no proof of detection")
                not_verified.append(pid)
            elif (rc not in (0, 1) or not evidence or not evidence["executed"]
                  or evidence["errors"] or evidence["unsupported"]
                  or (rc == 1 and not evidence["failed_tests"])
                  or (rc == 0 and evidence["failed_tests"])):
                entry.update(outcome="not_verified",
                             reason=f"нет подтверждённого результата выполненных тестов (rc={rc}). {tail[-160:]}")
                not_verified.append(pid)
            elif rc == 0:
                entry.update(outcome="survived",
                            reason="охрана снята, а названные тесты ЗЕЛЁНЫЕ — проверка не проверяется")
                survived.append(pid)
            else:
                entry.update(outcome="killed", reason="выполненный тест покраснел (rc=1), как и требуется")
            out.append(entry)

    return {"schema_version": 1, "kind": "mutation-probe-report", "checked": len(out),
            "survived": survived, "not_verified": not_verified, "probes": out}


def run(root=None, only=None, python=None, timeout=900, workers=1) -> dict:
    """Bounded opt-in parallelism; every worker owns a private disposable repository copy.

    Probes sharing a test command stay together, preserving one green baseline per command.
    There is no persistent cache or shared mutable tree; output retains registry order.
    """
    if not isinstance(workers, int) or isinstance(workers, bool) or not 1 <= workers <= 4:
        raise ValueError("workers must be an integer from 1 to 4")
    root = Path(root or PKG)
    probes = [p for p in load_probes(root) if not only or p.get("id") in set(only)]
    if workers == 1 or len(probes) < 2:
        return _run_serial(root, probes, python, timeout)
    groups = {}
    for index, probe in enumerate(probes):
        groups.setdefault(tuple(probe.get("tests") or []), []).append((index, probe))
    buckets = [[] for _ in range(min(workers, len(groups)))]
    weights = [0] * len(buckets)
    for group in sorted(groups.values(), key=lambda g: -len(g)):
        bucket = min(range(len(buckets)), key=lambda i: weights[i])
        buckets[bucket].extend(group)
        weights[bucket] += len(group) + 1
    if not buckets:
        return _run_serial(root, probes, python, timeout)
    def execute(bucket):
        result = _run_serial(root, [probe for _, probe in bucket], python, timeout)
        return [(index, entry) for (index, _), entry in zip(bucket, result["probes"], strict=True)]
    with ThreadPoolExecutor(max_workers=len(buckets)) as pool:
        indexed = [entry for results in pool.map(execute, buckets) for entry in results]
    entries = [entry for _, entry in sorted(indexed)]
    return {"schema_version": 1, "kind": "mutation-probe-report", "checked": len(entries),
            "survived": [e["id"] for e in entries if e["outcome"] == "survived"],
            "not_verified": [e["id"] for e in entries if e["outcome"] == "not_verified"], "probes": entries}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mutation_probe.py")
    ap.add_argument("repo", nargs="?", default=str(PKG))
    ap.add_argument("--only", default="")
    ap.add_argument("--workers", type=int, choices=range(1, 5), default=1, help="isolated copies (1 restores serial execution)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ns = ap.parse_args(argv if argv is not None else sys.argv[1:])
    if ns.selftest:
        print(__doc__)
        print("Проверки модуля — в tests/unit/test_mutation_probe.py (в том числе выживший мутант).")
        return 0
    rep = run(ns.repo, only=[x for x in ns.only.split(",") if x], workers=ns.workers)
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
