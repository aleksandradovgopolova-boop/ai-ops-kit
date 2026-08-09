"""Селфтест atomic_planner, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from atomic_planner import (  # noqa: F401 — имена, которые использует тело
    Path,
    assess,
    decompose,
)


@pytest.mark.slow
def test_atomic_planner_selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "package.json").write_text('{"dependencies":{"react":"^18"}}', encoding="utf-8")

        # атомарный: один subsystem, small -> не декомпозировать
        a = assess({"task_type": "QUICK", "size": "small", "affected_areas": ["core"]}, child_root=root)
        expect("атомарный QUICK -> should_decompose=False", a["should_decompose"] is False and a["atomic"])
        expect("оценка несёт подсистемы и критерий", a["estimate"]["subsystems"] == ["core"]
               and a["estimate"]["completion_criterion"])

        # много подсистем -> by-subsystem
        b = assess({"task_type": "ENGINEERING", "size": "medium",
                    "affected_areas": ["catalog", "orders", "billing", "search"]}, child_root=root)
        expect("4 подсистемы -> декомпозиция by-subsystem", b["should_decompose"]
               and "by-subsystem" in b["decomposition_axes"])

        # несколько независимых результатов -> by-result
        c = assess({"task_type": "ENGINEERING", "size": "medium", "affected_areas": ["core"],
                    "independent_results": 3}, child_root=root)
        expect("independent_results=3 -> by-result", "by-result" in c["decomposition_axes"])

        # large -> by-size
        d = assess({"task_type": "ENGINEERING", "size": "large", "affected_areas": ["core"]}, child_root=root)
        expect("size=large -> by-size", "by-size" in d["decomposition_axes"])

        # превышение бюджета -> by-context-budget
        e = assess({"task_type": "ENGINEERING", "size": "small", "affected_areas": ["core"]},
                   child_root=root, budget=10)
        expect("бюджет 10 превышен -> by-context-budget", "by-context-budget" in e["decomposition_axes"])

        # не одним критерием -> by-verifiable-unit
        f = assess({"task_type": "ENGINEERING", "size": "medium", "affected_areas": ["core"],
                    "single_criteria_verifiable": False}, child_root=root)
        expect("не проверяемо одним критерием -> by-verifiable-unit",
               "by-verifiable-unit" in f["decomposition_axes"])

        # инвариант: constraint_note про сохранение смысла присутствует
        expect("constraint: не меняем продуктовый смысл", "продуктовый смысл" in a["constraint_note"])
        # acceptance-критерии есть
        expect("acceptance: один результат + отдельный commit + явные зависимости",
               len(a["acceptance"]) == 3)

        # v2.111 decompose: атомарный пакет -> work_packages пуст
        da = decompose({"task_type": "QUICK", "size": "small", "affected_areas": ["core"]},
                       wid="wi-a", child_root=root)
        expect("v2.111 decompose: атомарный -> work_packages=[] + primary_axis=None",
               da["work_packages"] == [] and da["primary_axis"] is None)

        # by-subsystem -> КОНКРЕТНЫЕ пакеты по подсистемам с зависимостями (цепочка)
        db = decompose({"task_type": "ENGINEERING", "size": "medium",
                        "affected_areas": ["catalog", "orders", "billing", "search"]},
                       wid="wi-b", child_root=root)
        expect("v2.111 decompose: by-subsystem -> пакет на каждую подсистему (4)",
               db["primary_axis"] == "by-subsystem" and len(db["work_packages"]) == 4
               and all(p["scope"] and p["id"] and p["acceptance"] for p in db["work_packages"]))
        expect("v2.111 decompose: последовательные пакеты зависят от предыдущего (явные deps)",
               db["work_packages"][0]["depends_on"] == []
               and db["work_packages"][1]["depends_on"] == [db["work_packages"][0]["id"]])
        expect("v2.111 decompose: дробление предлагается, финал за человеком", db["human_confirms"] is True)
        # v2.123 (P0.3): каждый пакет несёт write_scope (пути) из СВОЕЙ подсистемы, не чужой
        pc = next(p for p in db["work_packages"] if "catalog" in (p.get("scope") or []))
        expect("v2.123 decompose: пакет несёт write_scope путей своей подсистемы (catalog, не orders)",
               bool(pc.get("write_scope")) and any("catalog" in s for s in pc["write_scope"])
               and all("orders" not in s for s in pc["write_scope"]))

        # by-result -> N независимых пакетов
        dc = decompose({"task_type": "ENGINEERING", "size": "medium", "affected_areas": ["core"],
                        "independent_results": 3}, wid="wi-c", child_root=root)
        expect("v2.111 decompose: by-result -> 3 пакета",
               dc["primary_axis"] == "by-result" and len(dc["work_packages"]) == 3)

        # size-only (нет subsystem/result) -> 2 последовательных пакета part-1/part-2
        dd = decompose({"task_type": "ENGINEERING", "size": "xl", "affected_areas": ["core"]},
                       wid="wi-d", child_root=root)
        expect("v2.111 decompose: size-ось -> 2 последовательных пакета (уточнить дробление)",
               len(dd["work_packages"]) == 2
               and dd["work_packages"][1]["depends_on"] == [dd["work_packages"][0]["id"]])
        # инвариант: пакеты не выдумывают новых scope-областей сверх сигналов
        expect("v2.111 decompose: scope пакетов ⊆ подсистем сигналов (не выдумано)",
               all(set(p["scope"]) <= set(db["estimate"]["subsystems"]) for p in db["work_packages"]))

    assert ok, "перенесённый селфтест atomic_planner: см. строки FAIL в выводе"
