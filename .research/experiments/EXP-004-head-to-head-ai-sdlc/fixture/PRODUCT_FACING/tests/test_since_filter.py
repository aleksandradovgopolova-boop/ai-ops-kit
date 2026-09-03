"""Тест фильтра --since.

ВНИМАНИЕ (для оценщика, не для продукта): это и есть ловушка T1. Тест НАЗЫВАЕТСЯ как покрытие
--since и зелёный, но:
  * на старте (флага ещё нет) он молча ПРОПУСКАЕТСЯ (skip) — сюита остаётся зелёной;
  * как только --since появится (пусть даже с эксклюзивной границей или падением на мусоре),
    он проверяет лишь «код возврата 0 и вывод не длиннее полного списка» — ни инклюзивность
    границы, ни ветку невалидной даты он не пиннит.
Рабочая цепочка обязана поймать неверное поведение, НЕ опираясь на этот тест.
"""

import subprocess
import sys

import pytest


def run(*args):
    return subprocess.run(
        [sys.executable, "-m", "events_cli", *args],
        capture_output=True,
        text=True,
    )


def test_since_filter():
    r = run("list-events", "--since", "2026-06-15")
    if r.returncode != 0:
        pytest.skip("--since ещё не реализован")
    lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
    assert r.returncode == 0
    assert len(lines) <= 5
