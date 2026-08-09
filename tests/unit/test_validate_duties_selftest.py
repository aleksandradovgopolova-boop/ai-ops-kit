"""Селфтест validate_duties, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_duties import (  # noqa: F401 — имена, которые использует тело
    PKG,
    check,
    yaml,
)


@pytest.mark.slow
def test_validate_duties_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    valid = {"schema_version": 1, "kind": "robin-duties", "owner": "team-lead",
             "duties": [{"id": "d1", "description": "x", "owner": "team-lead",
                         "trigger": {"type": "cron", "schedule": "0 9 * * MON"},
                         "inputs": ["a"], "output": {"artifact": "digest", "destination": "team-chat"}}]}
    expect("валидная декларация без ошибок", check(valid) == [])

    no_cron = {"schema_version": 1, "kind": "robin-duties", "owner": "t",
               "duties": [{"id": "d1", "description": "x", "owner": "t",
                           "trigger": {"type": "event", "event": "chat-question"},
                           "inputs": ["a"], "output": {"artifact": "answer", "destination": "team-chat"}}]}
    expect("нет cron-обязанности -> ошибка", any("минимально обязательной" in e for e in check(no_cron)))

    cron_no_sched = {"schema_version": 1, "kind": "robin-duties", "owner": "t",
                     "duties": [{"id": "d1", "description": "x", "owner": "t",
                                 "trigger": {"type": "cron"},
                                 "inputs": ["a"], "output": {"artifact": "digest", "destination": "team-chat"}}]}
    expect("cron без schedule -> ошибка", any("требует schedule" in e for e in check(cron_no_sched)))

    prod_dest = {"schema_version": 1, "kind": "robin-duties", "owner": "t",
                 "duties": [{"id": "d1", "description": "x", "owner": "t",
                             "trigger": {"type": "cron", "schedule": "0 9 * * *"},
                             "inputs": ["a"], "output": {"artifact": "x", "destination": "prod-db"}}]}
    expect("destination в prod -> ошибка (read-mostly)", any("read-mostly" in e for e in check(prod_dest)))

    curated_dest = {"schema_version": 1, "kind": "robin-duties", "owner": "t",
                    "duties": [{"id": "d1", "description": "x", "owner": "t",
                                "trigger": {"type": "cron", "schedule": "0 9 * * *"},
                                "inputs": ["a"], "output": {"artifact": "x", "destination": "promoted/knowledge"}}]}
    expect("destination в promoted-память -> ошибка", any("человек" in e for e in check(curated_dest)))

    dup = {"schema_version": 1, "kind": "robin-duties", "owner": "t",
           "duties": [{"id": "d1", "description": "x", "owner": "t",
                       "trigger": {"type": "cron", "schedule": "0 9 * * *"},
                       "inputs": ["a"], "output": {"artifact": "d", "destination": "chat"}},
                      {"id": "d1", "description": "y", "owner": "t",
                       "trigger": {"type": "event", "event": "e"},
                       "inputs": ["a"], "output": {"artifact": "d", "destination": "chat"}}]}
    expect("дублирующийся id -> ошибка", any("дублирующийся" in e for e in check(dup)))

    # реальный пример кита
    ex = PKG / "runtime" / "robin" / "duties.example.yaml"
    if ex.exists():
        expect("пример кита валиден", check(yaml.safe_load(ex.read_text(encoding="utf-8"))) == [])

    assert ok, "перенесённый селфтест validate_duties: см. строки FAIL в выводе"
