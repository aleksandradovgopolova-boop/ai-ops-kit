"""Селфтест session_telemetry, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from session_telemetry import (  # noqa: F401 — имена, которые использует тело
    check,
    snapshot,
    usage_ledger,
)


@pytest.mark.slow
def test_session_telemetry_selftest(monkeypatch, tmp_path):
    """Проверяет ветку ОЦЕНКИ по ledger — значит живая сессия рантайма должна быть не видна.

    ИЗОЛЯЦИЯ ДОБАВЛЕНА 2026-08-13. С момента, когда `snapshot()` начал ИЗМЕРЯТЬ расход сессии по
    транскрипту рантайма, этот селфтест на машине разработчика проверял не то, что заявляет: id
    сессии приходил из ENV, транскрипт находился, и контекст становился `measured` вместо
    `estimated`. В CI он проходил (там нет ни `~/.claude`, ни переменной) — то есть тест держался на
    том, чего на машине нет. Ровно тот класс скрытой зависимости, который здесь запрещён: пройденная
    проверка не должна означать разное на разных машинах.
    """
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    from ai_ops_kit.engops import session_telemetry_provider as _p
    for key in (*_p.ENV_SESSION_ID_KEYS, *_p.ENV_PROJECT_DIR_KEYS):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "no-runtime-home"))   # Path.home() -> без ~/.claude

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        # пустой продукт -> честный снимок без выдумок
        s = snapshot(td)
        expect("пустой продукт -> turns 0, context unavailable",
               s["turns"] == 0 and s["context_status"] == "unavailable" and s["context_current"] is None)
        expect("check валиден на пустом", check(s) == [])

        recs = [
            {"run_id": "r", "workitem_id": "WI-1", "role": "implementation", "provider": "claude-cli",
             "model": "m", "runtime": "claude-cli", "input_tokens": 120000, "output_tokens": 4000,
             "usage_status": "measured", "cost": 1.5, "cost_status": "measured", "trigger": "initial"},
            {"run_id": "r", "workitem_id": "WI-1", "role": "code_review", "provider": "deepseek",
             "model": "d", "runtime": "api", "input_tokens": 260000, "output_tokens": 2000,
             "usage_status": "measured", "cost": 0.02, "cost_status": "estimated", "trigger": "review"},
            {"run_id": "r", "workitem_id": "WI-1", "role": "author", "provider": "x", "model": "y",
             "runtime": "api", "input_tokens": None, "output_tokens": None,
             "usage_status": "unavailable", "cost": None, "cost_status": "unavailable", "trigger": "initial"},
        ]
        usage_ledger.append(td, "WI-1", recs, run_id="r")
        s = snapshot(td, workitem_id="WI-1")
        expect("context_current ≈ вход последнего вызова (estimated)",
               s["context_current"] == 260000 and s["context_status"] == "estimated")
        expect("context_peak = max входа", s["context_peak"] == 260000)
        expect("turns = число записей (3)", s["turns"] == 3)
        expect("unavailable-вызов не топит суммы токенов", s["input_tokens"] == 380000)
        expect("cost НЕполная (есть unavailable cost)", s["cost_complete"] is False)
        expect("usage_status=partial при 1 unavailable", s["usage_status"] == "partial")
        expect("unknown usage не как 0 — счётчик отдельно", s["usage_unavailable_calls"] == 1)
        expect("cache unavailable = None, не 0",
               s["cache_read_tokens"] is None and s["cache_status"] == "unavailable")

        s2 = snapshot(td, workitem_id="WI-1", context_current=95000)
        expect("runtime-контекст (/context) -> measured, перекрывает оценку",
               s2["context_current"] == 95000 and s2["context_status"] == "measured")

    assert ok, "перенесённый селфтест session_telemetry: см. строки FAIL в выводе"
