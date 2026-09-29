"""Докстрока security-скана называет только то, что можно запустить (#1096).

ПОВОД. Докстрока `security_scan.py` с v2.95 объявляла способ самопроверки — `security_scan.py
--selftest`, — а флага не было ни дня: argparse знал только `root`, `--base` и `--json`. По истории
он не удалялся, он никогда не существовал. Это тот же класс, что разобран в
`research/ACCEPTANCE.md`: СТРОКА ПРИЁМКИ НАЗЫВАЕТ ПРОВЕРКУ, КОТОРОЙ НЕ ПРОИСХОДИТ. Цена здесь выше
средней — модуль производит улики для блокирующего гейта `security`, и человек, читающий его
описание, разумно считает, что у детектора есть способ проверить себя.

Дефект закрыт ИСПОЛНЕНИЕМ, а не переписыванием формулировки: докстрока теперь называет
`pytest tests/unit/test_security_scan*.py`, а сама проверка там усилена — у каждого правила
детектора есть образец и безобидный двойник (корпус и сторож охвата в `test_security_scan.py`).
Реализовать `--selftest` в самом модуле нельзя: AGENTS.md — «selftest не живёт в продакшн-модуле»,
модули `ai_ops_kit/` едут в child-репозиторий.

ЗДЕСЬ СТОРОЖИТСЯ ОДНО И МЕХАНИЧЕСКИ, а не перечитыванием текста глазами: каждое упоминание
`--флаг` в докстроке обязано быть среди принимаемых argparse. Сверка идёт с `--help` САМОГО
СКРИПТА, запущенного как в проде — из корня репозитория и без `PYTHONPATH` (модуль намеренно не
импортирует пакет `ai_ops_kit`: иначе `ModuleNotFoundError`, потому что `sys.path[0]` — каталог
скрипта). Проверять это импортом значило бы проверять не тот способ запуска.

Три обязательных теста на capability (AGENTS.md):
  * positive     — скрипт запускается из корня без пояса, и обещанное им принимается;
  * fail-closed  — обещание несуществующего флага краснеет, а неизвестный флаг по-прежнему
                   отвергается (иначе сверка обесценилась бы принятием чего попало);
  * side-effect  — названный в докстроке способ проверки существует на диске, а не является
                   второй мёртвой ссылкой на месте первой.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from ai_ops_kit.security import security_scan as ss

pytestmark = pytest.mark.unit

PKG = Path(__file__).resolve().parents[2]
SCRIPT = PKG / "ai_ops_kit" / "security" / "security_scan.py"
# `--флаг` в тексте докстроки. Хвост (`<sha>`, `BASE`) не важен — важно имя опции.
_FLAG = re.compile(r"--[a-z][a-z0-9-]*")


def _run(*args):
    """Запуск как в проде: скрипт, из корня, без PYTHONPATH (окружение пользователя, без пояса)."""
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=PKG, env=env,
                          capture_output=True, text=True, timeout=300)


# ─── positive ──────────────────────────────────────────────────────────────────────────────────

def test_the_scanner_runs_as_a_script_without_pythonpath():
    assert SCRIPT.is_file(), "модуль исчез — сверять докстроку не с чем"
    r = _run("--help")
    assert r.returncode == 0, (r.stdout + r.stderr)[-1000:]
    assert "usage: security_scan.py" in r.stdout, r.stdout[:300]


# ─── fail-closed ───────────────────────────────────────────────────────────────────────────────

def test_the_docstring_promises_only_flags_that_argparse_accepts():
    """Корень дефекта. Сверка механическая: имена из докстроки против `--help` самого скрипта."""
    promised = set(_FLAG.findall(ss.__doc__ or ""))
    accepted = _run("--help").stdout
    missing = sorted(f for f in promised if f not in accepted)
    assert missing == [], (
        f"докстрока обещает флаги, которых нет в argparse: {missing} — описание называет способ "
        f"запуска, которого не существует")


def test_the_docstring_still_names_how_to_run_the_scanner():
    """Обратная половина: «ничего не обещать» — тоже способ пройти сверку, и он не годится."""
    doc = ss.__doc__ or ""
    assert "security_scan.py <root>" in doc, "докстрока перестала называть способ запуска вовсе"
    assert "--base" in doc, "докстрока перестала называть разбор против базы"


def test_an_unknown_flag_is_still_rejected():
    """Argparse не стал принимать что попало ради зелёной сверки."""
    r = _run("--нет-такого-флага")
    assert r.returncode != 0, "неизвестный флаг принят — сверка докстроки обесценена"


# ─── side-effect proof ─────────────────────────────────────────────────────────────────────────

def test_the_named_way_to_check_the_module_actually_exists():
    """Докстрока называет набор тестов. Мёртвая ссылка на них — тот же дефект другим текстом."""
    doc = ss.__doc__ or ""
    assert "tests/unit/test_security_scan" in doc, (
        "докстрока не называет реальный способ проверки модуля")
    found = sorted(p.name for p in (PKG / "tests" / "unit").glob("test_security_scan*.py"))
    assert found, "названный в докстроке набор tests/unit/test_security_scan*.py не существует"
    assert "test_security_scan.py" in found, found
