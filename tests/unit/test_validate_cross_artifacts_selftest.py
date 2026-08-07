"""Селфтест validate_cross_artifacts, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_cross_artifacts import (  # noqa: F401 — имена, которые использует тело
    DASHBOARD,
    DS_BAD,
    DS_OK,
    Path,
    TP_OK,
    TRACKING,
    check_feature,
    tempfile,
)


@pytest.mark.slow
def test_validate_cross_artifacts_selftest():
    ok = True

    def expect(name, got, want):
        nonlocal ok
        good = got == want
        ok = ok and good
        print(f"{'PASS' if good else 'FAIL'} {name}" + ("" if good else f" (got {got})"))

    with tempfile.TemporaryDirectory() as td:
        def mk(name, tp=None, ds=None):
            d = Path(td) / name
            (d / "analytics").mkdir(parents=True)
            if tp is not None:
                (d / TRACKING).write_text(tp, encoding="utf-8")
            if ds is not None:
                (d / DASHBOARD).write_text(ds, encoding="utf-8")
            return d

        p, w, s = check_feature(mk("a", TP_OK, DS_OK))
        expect("согласованная пара -> чисто", (len(p), len(w)), (0, 0))
        p, _, _ = check_feature(mk("b", TP_OK, DS_BAD))
        expect("необъявленное событие в дашборде -> PROBLEM", len(p) > 0, True)
        p, _, s = check_feature(mk("c", TP_OK, None))
        expect("нет dashboard-spec -> skip без ошибок", (len(p), s is not None), (0, True))
        p, _, _ = check_feature(mk("d", None, DS_OK))
        expect("дашборд без tracking plan -> PROBLEM", len(p), 1)
        p, w, _ = check_feature(mk("e", "# Tracking Plan\nбез таблицы\n", DS_OK))
        expect("нераспарсиваемый tracking plan -> WARN, не fail", (len(p), len(w)), (0, 1))

    assert ok, "перенесённый селфтест validate_cross_artifacts: см. строки FAIL в выводе"
