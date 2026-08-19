"""Сквозной путь владельца в одноразовом репозитории — от установки до status.

ЗАЧЕМ ЭТОТ ФАЙЛ. Замер EV-1107..EV-1109: 163 прогона CI дали 0 падений, а 7 живых прогонов на
чужих репозиториях дали 48 находок. 268 тестовых файлов из 271 лежат в tests/unit, а
tests/integration содержит только README.md. Слой, давший ВСЕ находки, не покрыт ничем.

Этот тест проходит путь install → doctor → onboard → specify → plan → next → status в одноразовом
репозитории с `--provider mock` (бесплатно, повторяемо, без живого провайдера). Каждый шаг — уже
случившаяся находка поля: точка входа ./ai-ops (F-031), разбор specify (F-029, B2-06), валидность
плана после bootstrap (F-030), next после обновления (F-032).

РЕШЕНИЕ ВЛАДЕЛЬЦА 17.08.2026 (ep-2026-08-17-dev-velocity-first-steps, п. 2): начать без живой
модели. Бесплатный и повторяемый прогон пойдёт на каждую заявку; платный — отдельной ночной
проверкой, после измерения стоимости.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[2]
INSTALLER = KIT / "installer" / "ai_ops.py"


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, check=False,
    )
    if check:
        assert r.returncode == 0, f"git {' '.join(args)}: {r.stderr[-300:]}"
    return r


def _ai_ops(
    root: Path, *args: str, timeout: int = 300,
) -> subprocess.CompletedProcess:
    """Вызов ./ai-ops из корня дочки — как его зовёт владелец."""
    env = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "AI_OPS_HOME": str(KIT),
    }
    entry = root / "ai-ops"
    return subprocess.run(
        [str(entry), *args],
        cwd=str(root),
        capture_output=True, text=True,
        timeout=timeout, env=env,
    )


@pytest.fixture(scope="module")
def child(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Чистый git-репозиторий — типовая точка входа владельца."""
    root = tmp_path_factory.mktemp("owner-full-path") / "product"
    root.mkdir(parents=True)
    (root / "README.md").write_text("# product\n", encoding="utf-8")
    _git(root, "init", "-q", "-b", "main", ".")
    _git(root, "config", "user.email", "owner@example.com")
    _git(root, "config", "user.name", "owner")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "initial")
    return root


@pytest.mark.slow
def test_owner_full_path(child: Path) -> None:
    """Полный путь владельца: install → doctor → onboard → specify → plan → next → status."""
    # ── шаг 1: установка ────────────────────────────────────────────────────────────────────────
    r = subprocess.run(
        [sys.executable, str(INSTALLER), "init", "."],
        cwd=str(child), capture_output=True, text=True, timeout=600,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert r.returncode == 0, f"init упал:\n{r.stdout[-900:]}\n{r.stderr[-600:]}"
    assert (child / ".ai" / "managed").is_dir(), "managed-слой не создан"
    assert (child / ".ai-ops.yaml").is_file(), "конфиг дочки не создан"
    assert (child / "ai-ops").is_file(), "точка входа ./ai-ops не создана"

    # продукт не тронут
    assert _git(child, "status", "--porcelain", "README.md").stdout.strip() == ""

    # ── шаг 2: doctor ───────────────────────────────────────────────────────────────────────────
    # F-031: doctor зелёный, но интерпретатор не видит pyyaml — класс «зелёное ничего не значит».
    doc = _ai_ops(child, "doctor")
    assert doc.returncode == 0, f"doctor упал:\n{doc.stdout[-600:]}\n{doc.stderr[-400:]}"

    # ── шаг 3: onboard ──────────────────────────────────────────────────────────────────────────
    # Определяет стек и команды репозитория. Без живого провайдера — сухой прогон.
    ob = _ai_ops(child, "onboard", "--provider", "mock")
    assert ob.returncode == 0, f"onboard упал:\n{ob.stdout[-600:]}\n{ob.stderr[-400:]}"

    # ── шаг 4: specify ──────────────────────────────────────────────────────────────────────────
    # F-029, B2-06: specify теряет содержание фразы, падает сырым argparse.
    # Путь идёт ПОСЛЕ интента (B2-15): обёртка подставляет каталог сама.
    spec = _ai_ops(child, "specify", "добавить hello-world endpoint", "--feature", "hello",
                   "--provider", "mock")
    assert spec.returncode == 0, (
        f"specify упал (класс F-029/B2-06):\n{spec.stdout[-600:]}\n{spec.stderr[-400:]}")
    # сырой traceback — класс отказа, который ловит этот тест
    assert "Traceback" not in spec.stderr, (
        f"specify оставил сырой traceback:\n{spec.stderr[-400:]}")

    # ── шаг 5: plan ─────────────────────────────────────────────────────────────────────────────
    # F-030: план невалиден после bootstrap.
    pl = _ai_ops(child, "plan", "добавить hello-world endpoint", "--feature", "hello",
                 "--provider", "mock")
    assert pl.returncode == 0, (
        f"plan упал:\n{pl.stdout[-600:]}\n{pl.stderr[-400:]}")
    assert "Traceback" not in pl.stderr, (
        f"plan оставил сырой traceback:\n{pl.stderr[-400:]}")

    # ── шаг 6: next ─────────────────────────────────────────────────────────────────────────────
    # F-032: next после обновления отказался работать.
    nx = _ai_ops(child, "next")
    assert nx.returncode == 0, (
        f"next упал (класс F-032):\n{nx.stdout[-600:]}\n{nx.stderr[-400:]}")

    # ── шаг 7: status ───────────────────────────────────────────────────────────────────────────
    st = _ai_ops(child, "status")
    assert st.returncode == 0, f"status упал:\n{st.stdout[-600:]}\n{st.stderr[-400:]}"


@pytest.mark.slow
def test_entry_point_exists_after_init(child: Path) -> None:
    """F-031: ./ai-ops существует после установки и отвечает на help."""
    entry = child / "ai-ops"
    assert entry.is_file(), "точка входа ./ai-ops не создана при init"
    assert os.access(entry, os.X_OK), "./ai-ops не исполняемый"

    # help (без дефисов) — маршрутизируется entry point в CLI; CLI требует intent,
    # поэтому проверяем не returncode, а отсутствие сырого traceback.
    r = _ai_ops(child, "help")
    assert "Traceback" not in r.stderr, (
        f"./ai-ops help оставил сырой traceback:\n{r.stderr[-400:]}")
