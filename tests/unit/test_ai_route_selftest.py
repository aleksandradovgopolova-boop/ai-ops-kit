"""Селфтест ai_route, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from ai_route import (  # noqa: F401 — имена, которые использует тело
    REQUIRED_KEYS,
    SCENARIOS,
    route,
)


@pytest.mark.slow
def test_ai_route_selftest():
    ok = True
    for sc in SCENARIOS:
        d = route(sc["inp"])
        missing = [k for k in REQUIRED_KEYS if k not in d or d[k] in (None, "")]
        # selected_provider may legitimately be None only if no provider; here always set
        problems = []
        if missing:
            problems.append(f"нет ключей {missing}")
        for k, v in sc["expect"].items():
            if d.get(k) != v:
                problems.append(f"{k}={d.get(k)!r} != ожидалось {v!r}")
        if not d.get("reasons"):
            problems.append("пустые reasons")
        status = "OK  " if not problems else "FAIL"
        if problems:
            ok = False
        print(f"{status} [{sc['name']}] -> wf={d['workflow']} prov={d['selected_provider']} "
              f"rt={d['selected_runtime']} class={d['selected_model_class']} mode={d['execution_mode']} "
              f"approval={d['human_approval_required']}")
        for p in problems:
            print(f"       - {p}")
    print("routing self-test:", "PASS" if ok else "FAIL")

    assert ok, "перенесённый селфтест ai_route: см. строки FAIL в выводе"
