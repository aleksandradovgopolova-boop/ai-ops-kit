"""Селфтест effect_metrics, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from effect_metrics import (  # noqa: F401 — имена, которые использует тело
    Path,
    build,
    json,
    tempfile,
)


@pytest.mark.slow
def test_effect_metrics_selftest():
    ok = True

    def expect(name, got, want):
        nonlocal ok
        good = got == want
        ok = ok and good
        print(f"{'PASS' if good else 'FAIL'} {name}" + ("" if good else f" (got {got})"))

    with tempfile.TemporaryDirectory() as td:
        h = Path(td)
        def entry(ts, verdict, stage, filled):
            return json.dumps({"schema_version": 1, "ts": ts, "feature": "f",
                               "verdict": verdict, "current_stage": stage,
                               "coverage": {"filled": filled}, "problems": 0, "warns": 0})
        (h / "feat-a.jsonl").write_text("\n".join([
            entry("2026-07-01T10:00:00+00:00", "PROBLEM", "discovery", 1),
            entry("2026-07-04T10:00:00+00:00", "WARN", "delivery", 5),
            entry("2026-07-08T10:00:00+00:00", "OK", "retrospective", 9),
        ]) + "\n", encoding="utf-8")
        (h / "feat-b.jsonl").write_text(entry("2026-07-09T10:00:00+00:00", "OK", "definition", 3) + "\n",
                                        encoding="utf-8")
        r = build(h)
        a = r["per_feature"]["feat-a"]
        expect("feat-a: 3 среза достаточно", a["sufficient"], True)
        expect("feat-a: problem_rate 0.33", a["problem_rate"], 0.33)
        expect("feat-a: 7 дней в полёте", a["period_days"], 7.0)
        expect("feat-a: стадий пройдено 10", a["stages_advanced"], 10)
        expect("feat-b: insufficient", r["per_feature"]["feat-b"]["sufficient"], False)
        expect("медиана до retrospective = 7", r["aggregate"]["median_days_to_retrospective"], 7.0)
        expect("baseline не готов (< 3 фич с историей)", r["aggregate"]["baseline_ready"], False)

    assert ok, "перенесённый селфтест effect_metrics: см. строки FAIL в выводе"
