#!/usr/bin/env python3
"""Тесты инсталлятора `installer/ai_ops.py` — точка входа `./ai-ops`, байткод, selftest.

Разрез монолита tests/unit/test_installer.py; общая инфраструктура — в `_installer_helpers.py`.
"""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

from _installer_helpers import installed, _path_python_with_pyyaml

KIT = Path(__file__).resolve().parents[2]
INSTALLER = KIT / "installer" / "ai_ops.py"

pytestmark = pytest.mark.unit


def _load_installer():
    """Импортировать installer/ai_ops.py как модуль (он не пакет — грузим по пути)."""
    spec = importlib.util.spec_from_file_location("installer_ai_ops_under_test", INSTALLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ai_ops():
    return _load_installer()


def test_child_gets_a_runnable_entry_point(installed):
    """НАХОДКА РЕВЬЮ, ломавшая обещание слоя коммуникации на ПЕРВОЙ команде: все подсказки кита
    печатали `ai-ops …`, а такой команды не существует — ни `console_scripts`, ни файла. Владелец
    копировал строку и получал `command not found`.

    Политика требует в каждом сообщении «что дальше». Пункт, который нельзя выполнить, этому
    требованию не удовлетворяет: в подсказке обязано быть то, что копируется и запускается.
    """
    import os
    import subprocess
    if not _path_python_with_pyyaml():
        pytest.skip("в PATH нет python3 с pyyaml — на этой машине кит не запускается, "
                    "и тест обёртки мерил бы окружение, а не её")
    entry = installed / "ai-ops"
    assert entry.is_file(), "в репозиторий не положена запускаемая точка входа"
    assert os.access(entry, os.X_OK), "точка входа не исполняемая"
    r = subprocess.run([str(entry), "status"], cwd=str(installed),
                       capture_output=True, text=True, timeout=120)
    assert r.returncode in (0, 1), f"./ai-ops status не работает: {r.returncode} {r.stderr[:300]}"
    # `status` — ПРОДУКТОВЫЙ вопрос («что идёт прямо сейчас»), а не отчёт о слое кита: у владельца
    # это первое значение слова. Состояние самого кита спрашивают реже и зовут `kit-status`.
    assert "идёт" in r.stdout or "не начата" in r.stdout, r.stdout[:300]
    assert "managed" not in r.stdout, "продуктовый вопрос ответил отчётом о внутренностях кита"


def test_entry_point_without_usable_python_says_what_to_do(installed):
    """fail-closed: нет интерпретатора с pyyaml -> внятное сообщение, а НЕ трейсбек.

    До ревизии 2026-08-11 обёртка звала голое `python3` из PATH. На машине, где pyyaml стоит в
    другом интерпретаторе (brew поднял минорную версию; кит ставили из venv), владелец получал
    `ModuleNotFoundError: No module named 'yaml'` — трейсбек вместо сообщения, на ПЕРВОЙ команде.
    Пустой PATH здесь моделирует именно это: ни один кандидат не пригоден.
    """
    import subprocess
    entry = installed / "ai-ops"
    env = {"PATH": str(installed / "no-python-here"), "HOME": os.environ.get("HOME", "/tmp")}
    r = subprocess.run([str(entry), "status"], cwd=str(installed), env=env,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 2, f"ожидался fail-closed rc=2, получено {r.returncode}"
    err = r.stderr
    assert "Traceback" not in err and "ModuleNotFoundError" not in err, (
        f"вместо сообщения показан трейсбек:\n{err[:400]}")
    assert "pyyaml" in err, f"не названа причина:\n{err[:400]}"
    assert "AI_OPS_PYTHON" in err and "pip install" in err, (
        f"сказано, что сломано, но не сказано, что делать:\n{err[:400]}")


def test_entry_point_honours_explicit_interpreter(installed):
    """positive + side-effect proof: AI_OPS_PYTHON сильнее перебора PATH.

    Явное слово владельца обязано работать даже когда в PATH пригодного python3 нет вообще —
    иначе на машине с нестандартным окружением кит остаётся незапускаемым при живом интерпретаторе.
    """
    import subprocess
    entry = installed / "ai-ops"
    # PYTHONDONTWRITEBYTECODE в env НЕ передаём намеренно — так запускает владелец, и именно так
    # был найден дефект: успешная команда роняла 11 `.pyc` в checksummed managed-слой.
    env = {"PATH": str(installed / "no-python-here"), "HOME": os.environ.get("HOME", "/tmp"),
           "AI_OPS_PYTHON": sys.executable}

    # side-effect proof: кит не сорит в чужом репозитории. `.gitignore` установщик в дочку не
    # пишет, поэтому байткод в managed уехал бы в коммит владельца по `git add -A`.
    # R-39: замеряем ТОЛЬКО эффект своей команды — снимок до/до сравнивается со снимком после.
    # Фикстура `installed` общая на модуль, и раньше этот assert краснел из-за байткода СОСЕДА,
    # показывая при этом на обёртку, которая байткод как раз подавляет.
    def _pyc():
        return {str(p.relative_to(installed)) for p in (installed / ".ai" / "managed").rglob("*.pyc")}

    before = _pyc()
    r = subprocess.run([str(entry), "status"], cwd=str(installed), env=env,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode in (0, 1), (
        f"AI_OPS_PYTHON={sys.executable} не был использован: rc={r.returncode}\n{r.stderr[:400]}")
    assert "идёт" in r.stdout or "не начата" in r.stdout, r.stdout[:300]
    left = sorted(_pyc() - before)
    assert not left, f"команда оставила байткод кита в managed-слое дочки: {left[:5]}"


def test_direct_installer_call_leaves_no_bytecode(installed):
    """R-39: у кита ДВА документированных входа, а защита стояла на одном.

    Обёртка `./ai-ops` экспортирует `PYTHONDONTWRITEBYTECODE=1` с ревизии 11.08, но прямой вызов
    `python3 ~/ai-ops-kit/installer/ai_ops.py doctor` описан наравне с ней — и оставлял байткод.
    Замер до правки: 19 файлов `.pyc` в checksummed `.ai/managed` за одну команду. Так и должно
    быть по устройству: `doctor` намеренно импортирует доставленную копию из managed, а не свою.
    """
    import subprocess

    def _pyc():
        return {str(p.relative_to(installed)) for p in (installed / ".ai" / "managed").rglob("*.pyc")}

    before = _pyc()
    r = subprocess.run([sys.executable, str(INSTALLER), "doctor"], cwd=str(installed),
                       capture_output=True, text=True, timeout=180)
    assert "Traceback" not in (r.stdout + r.stderr), (r.stdout + r.stderr)[-400:]
    left = sorted(_pyc() - before)
    assert not left, (
        f"прямой вызов установщика оставил байткод в checksummed managed-слое: {left[:5]} "
        f"(всего {len(left)}); `.gitignore` в дочку не пишется — это уедет в коммит владельца")


@pytest.mark.parametrize("script", [
    pytest.param("ai_ops_kit/validation/validate_ai_ops_child.py", id="валидатор"),
    pytest.param("tools/ai_ops_cli.py", id="плоский-алиас"),
])
def test_running_from_managed_leaves_no_bytecode(installed, script):
    """R-39, третий и четвёртый входы: человек зовёт код ИЗ managed напрямую.

    Так это описано в документации и так родился F-025. Обёртка `./ai-ops` тут не участвует,
    поэтому защита живёт в самих `_bootstrap` — условно, только когда корень оказался
    managed-слоем дочки. В дереве самого кита байткод остаётся нормой.

    Переменную `PYTHONDONTWRITEBYTECODE` из окружения СНИМАЕМ намеренно: её ставят группы CI, и
    без снятия тест был бы зелёным в CI по чужой причине, ничего не проверяя.
    """
    import subprocess

    def _pyc():
        return {str(p.relative_to(installed)) for p in (installed / ".ai" / "managed").rglob("*.pyc")}

    env = {k: v for k, v in os.environ.items() if k != "PYTHONDONTWRITEBYTECODE"}
    before = _pyc()
    r = subprocess.run([sys.executable, str(installed / ".ai" / "managed" / script)],
                       cwd=str(installed), capture_output=True, text=True, timeout=300, env=env)
    left = sorted(_pyc() - before)
    assert not left, (
        f"запуск `{script}` из managed оставил байткод в checksummed-слое: {left[:5]} "
        f"(всего {len(left)}); слой сверяется контрольными суммами — кит примет это за правку "
        f"владельца (F-025). rc={r.returncode}")


def test_hints_point_to_something_runnable(installed, ai_ops):
    """Ни одна подсказка не должна учить неработающей команде."""
    import subprocess
    out = subprocess.run(["python3", str(ai_ops.PKG / "installer" / "ai_ops.py"), "doctor"],
                         cwd=str(installed), capture_output=True, text=True, timeout=180).stdout
    bad = [ln for ln in out.splitlines()
           if "`ai-ops " in ln and "./ai-ops" not in ln and "python3" not in ln]
    assert not bad, f"подсказки учат несуществующей команде: {bad[:3]}"


@pytest.mark.slow   # тяжёлая обёртка селфтеста: в быстрый профиль не входит
def test_installer_selftest_passes():
    """Собственный selftest инсталлятора остаётся зелёным (не подменяем его этими тестами)."""
    r = subprocess.run([sys.executable, str(INSTALLER), "--selftest"],
                       cwd=str(KIT), capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]
