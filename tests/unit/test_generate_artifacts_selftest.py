"""Селфтест generate_artifacts, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from generate_artifacts import (  # noqa: F401 — имена, которые использует тело
    Path,
    cmd_add,
    cmd_check,
    cmd_new,
    cmd_scaffold,
    tempfile,
)


@pytest.mark.slow
def test_generate_artifacts_selftest():
    ok = True

    def expect(name, got, want):
        nonlocal ok
        good = got == want
        ok = ok and good
        print(f"{'PASS' if good else 'FAIL'} {name}" + ("" if good else f" (got {got})"))

    with tempfile.TemporaryDirectory() as td:
        feats = Path(td) / "features"
        expect("new создаёт blueprint", cmd_new(feats, "demo-x", "Demo X"), 0)
        fdir = feats / "demo-x"
        expect("scaffold discovery", cmd_scaffold(fdir, "discovery"), 0)
        ps = fdir / "discovery" / "problem-statement.md"
        expect("скелет problem-statement создан", ps.exists(), True)
        expect("check: незаполненные скелеты discovery -> 1", cmd_check(fdir), 1)
        ps.write_text(ps.read_text(encoding="utf-8") + "\nНастоящее содержание.\n", encoding="utf-8")
        hyp = fdir / "discovery" / "hypotheses.md"
        hyp.write_text(hyp.read_text(encoding="utf-8") + "\nH1.\n", encoding="utf-8")
        expect("check: после заполнения -> 0", cmd_check(fdir), 0)
        expect("scaffold идемпотентен (не перезаписывает)",
               "Настоящее содержание." in ps.read_text(encoding="utf-8") if cmd_scaffold(fdir, "discovery") == 0 else False,
               True)
        expect("add experiment", cmd_add(fdir, "discovery", "experiments/exp-1.md",
                                         "templates/product/Experiment.md"), 0)
        expect("файл эксперимента создан", (fdir / "experiments" / "exp-1.md").exists(), True)

    assert ok, "перенесённый селфтест generate_artifacts: см. строки FAIL в выводе"
