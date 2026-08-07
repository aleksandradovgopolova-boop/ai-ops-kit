"""Селфтест merge_memory, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from merge_memory import (  # noqa: F401 — имена, которые использует тело
    Path,
    record,
)


@pytest.mark.slow
def test_merge_memory_selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    with tempfile.TemporaryDirectory() as td:
        expect("без summary -> ошибка", record(td, "wi-1", "") == 1)

        # v3.7.1 (#4) governance-барьер: без human_confirmed self-ingested запись НЕ создаётся
        rc_block = record(td, "wi-0", "Правка без подтверждения куратора.", at="2026-07-15")
        f_block = Path(td) / "lessons-learned" / "2026-07-15-wi-0.md"
        expect("без human_confirmed -> BLOCKED, файл НЕ создан (анти-самоотравление)",
               rc_block == 1 and not f_block.exists())

        rc = record(td, "wi-1", "Добавлено редактирование дашборда после создания.",
                    areas=["dashboard-editor", "session-context"],
                    decisions="dashboard хранит source_session_id",
                    lessons="теряется связь artifact<->session; добавить версионирование",
                    at="2026-07-15", human_confirmed=True)
        f = Path(td) / "lessons-learned" / "2026-07-15-wi-1.md"
        expect("record c human_confirmed: файл создан", rc == 0 and f.exists())

        # v3.7.2 FAIL-CLOSED (#6): сбой governance-enforcement -> запись НЕ создаётся (не fail-open)
        import security_enforcement as _se
        _orig = _se.enforce_memory_entry
        _se.enforce_memory_entry = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            rc_crash = record(td, "wi-crash", "правка", at="2026-07-15", human_confirmed=True)
        finally:
            _se.enforce_memory_entry = _orig
        f_crash = Path(td) / "lessons-learned" / "2026-07-15-wi-crash.md"
        expect("governance enforcement упал -> BLOCKED, файл НЕ создан (fail-closed)",
               rc_crash == 1 and not f_crash.exists())
        txt = f.read_text(encoding="utf-8")
        expect("содержит summary", "редактирование дашборда" in txt)
        expect("содержит зоны", "dashboard-editor" in txt)
        expect("содержит решения", "source_session_id" in txt)
        expect("содержит уроки", "версионирование" in txt)
        expect("отсылает к decisions/registry", "decisions/registry.yaml" in txt)

    assert ok, "перенесённый селфтест merge_memory: см. строки FAIL в выводе"
