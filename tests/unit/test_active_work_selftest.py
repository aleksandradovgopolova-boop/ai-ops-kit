"""Селфтест active_work, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from active_work import (  # noqa: F401 — имена, которые использует тело
    ActiveWorkCorrupt,
    Path,
    classify,
    finish_cmd,
    load,
    register,
)


@pytest.mark.slow
def test_active_work_selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "active-work.yaml"
        register(p, "dashboard-editing", "feature/dashboard-editing",
                 ["dashboard-editor", "session-context"], "session-1",
                 contracts=["schemas/dashboard.schema.json"], at="2026-07-15")
        d = load(p)
        expect("register: запись добавлена", any(w["id"] == "dashboard-editing" for w in d["active"]))
        expect("register в main -> ошибка", register(p, "x", "main", ["a"], "s") == 1)
        expect("register без areas -> ошибка", register(p, "x", "feature/x", [], "s") == 1)

        # area-конфликт
        confs = classify(d["active"], {"id": "new", "affected_areas": ["session-context", "catalog"]})
        expect("classify: area-конфликт", any(c["kind"] == "area" and "session-context" in c["detail"] for c in confs))

        # contract-конфликт
        confs = classify(d["active"], {"id": "new", "affected_areas": ["x"],
                                       "shared_contracts": ["schemas/dashboard.schema.json"]})
        expect("classify: contract-конфликт", any(c["kind"] == "contract" for c in confs))

        # dependency: новая зависит от активной
        confs = classify(d["active"], {"id": "new", "affected_areas": ["x"],
                                       "depends_on": ["dashboard-editing"]})
        expect("classify: dependency на активную", any(c["kind"] == "dependency" for c in confs))

        # непересекающееся -> пусто
        confs = classify(d["active"], {"id": "new", "affected_areas": ["catalog", "api"]})
        expect("classify: непересекающееся -> пусто", confs == [])

        # exclude себя
        confs = classify(d["active"], {"id": "dashboard-editing", "affected_areas": ["dashboard-editor"]})
        expect("classify: сама себя не считает", confs == [])

        # цикл зависимостей -> ошибка register
        register(p, "a", "feature/a", ["za"], "s", depends=["b"], at="2026-07-15")
        rc = register(p, "b", "feature/b", ["zb"], "s", depends=["a"], at="2026-07-15")
        expect("цикл зависимостей a<->b -> ошибка", rc == 1)

        # done не участвует
        finish_cmd(p, "dashboard-editing")
        confs = classify(load(p)["active"], {"id": "new", "affected_areas": ["dashboard-editor"]})
        expect("done не даёт конфликт", all(c["id"] != "dashboard-editing" for c in confs))

        # v3.0.12 (finding аудита блок B): durable + fail-closed чтение общего реестра.
        expect("v3.0.12: save пишет атомарно (нет остаточного .tmp)",
               p.is_file() and not p.with_suffix(p.suffix + ".tmp").exists())
        p.write_text("", encoding="utf-8")   # оборванная запись
        try:
            load(p)
            expect("v3.0.12: пустой реестр -> ActiveWorkCorrupt (не тихая пустая карта)", False)
        except ActiveWorkCorrupt:
            expect("v3.0.12: пустой реестр -> ActiveWorkCorrupt (не тихая пустая карта)", True)
        p.write_text("kind: active-work\nactive: [ :::\n", encoding="utf-8")   # битый YAML
        try:
            load(p)
            expect("v3.0.12: битый YAML реестр -> ActiveWorkCorrupt", False)
        except ActiveWorkCorrupt:
            expect("v3.0.12: битый YAML реестр -> ActiveWorkCorrupt", True)
        p.unlink()
        expect("v3.0.12: отсутствующий реестр -> fresh (не ошибка)", load(p)["active"] == [])

    assert ok, "перенесённый селфтест active_work: см. строки FAIL в выводе"
