"""Селфтест validate_event_catalog, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_event_catalog import (  # noqa: F401 — имена, которые использует тело
    PKG,
    Path,
    check,
    scan_code,
    yaml,
)


@pytest.mark.slow
def test_validate_event_catalog_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    valid = {"schema_version": 1, "kind": "event-catalog", "events": [
        {"name": "object.version_created", "kind": "domain", "payload": ["objectId", "version"]},
        {"name": "task.completed", "kind": "domain", "payload": ["taskId"]},
        {"name": "object.version_saved", "kind": "audit", "maps_to": "object.version_created",
         "fields": ["actorId", "action", "result"]},
        {"name": "catalog.published", "kind": "analytics", "maps_to": "object.version_created"},
    ]}
    e, w = check(valid)
    expect("валидный каталог без ошибок", e == [])

    # дубль имени -> ошибка
    e, _ = check({"schema_version": 1, "kind": "event-catalog", "events": [
        {"name": "task.completed", "kind": "domain"},
        {"name": "task.completed", "kind": "domain"}]})
    expect("дубль имени -> ошибка", any("дублирующееся" in x for x in e))

    # плохая грамматика
    e, _ = check({"schema_version": 1, "kind": "event-catalog",
                  "events": [{"name": "task.Complete", "kind": "domain"}]})
    expect("camelCase/грамматика -> ошибка", any("грамматике" in x for x in e))

    # audit без maps_to
    e, _ = check({"schema_version": 1, "kind": "event-catalog", "events": [
        {"name": "task.completed", "kind": "domain"},
        {"name": "task.complete", "kind": "audit"}]})
    expect("audit без maps_to -> ошибка", any("нет maps_to" in x for x in e))

    # maps_to в несуществующее domain
    e, _ = check({"schema_version": 1, "kind": "event-catalog", "events": [
        {"name": "task.completed", "kind": "domain"},
        {"name": "task.done", "kind": "analytics", "maps_to": "task.nope"}]})
    expect("maps_to на несуществующее -> ошибка", any("нет такого domain" in x for x in e))

    # domain подменён audit-полями
    e, _ = check({"schema_version": 1, "kind": "event-catalog", "events": [
        {"name": "object.opened", "kind": "domain", "fields": ["actorId", "action", "result"]}]})
    expect("domain с audit-полями -> ошибка (подмена)", any("AuditEvent" in x for x in e))

    # standalone без reason
    e, _ = check({"schema_version": 1, "kind": "event-catalog", "events": [
        {"name": "d.happened", "kind": "domain"},
        {"name": "sys.pinged", "kind": "audit", "standalone": True}]})
    expect("standalone без reason -> ошибка", any("standalone требует reason" in x for x in e))

    # drift-скан по коду
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        code = Path(td) / "server.ts"
        code.write_text('emit("object.version.save"); emit("object.version_created");', encoding="utf-8")
        drift = scan_code(["object.version_created"], [], [str(code)])
        expect("scan: ловит незнакомый литерал", any(d["literal"] == "object.version.save" for d in drift))
        expect("scan: каноничное имя не в drift", all(d["literal"] != "object.version_created" for d in drift))

    ex = PKG / "examples" / "event-catalog-demo" / "events.yaml"
    if ex.exists():
        e, _ = check(yaml.safe_load(ex.read_text(encoding="utf-8")))
        expect("пример кита валиден", e == [])

    assert ok, "перенесённый селфтест validate_event_catalog: см. строки FAIL в выводе"
