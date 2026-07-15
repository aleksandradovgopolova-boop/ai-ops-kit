#!/usr/bin/env python3
"""Реестр активных работ репозитория (v2.22) — координация параллельных сессий.

Несколько сессий Claude могут работать в одном репозитории одновременно (новая фича,
фикс интерфейса, аналитика, безопасность). Чтобы они не уничтожали работу друг друга,
каждая регистрирует свою работу здесь: id WorkItem, ветка, затрагиваемые зоны, сессия.
Новая сессия видит карту и получает conflict forecast — предупреждение о пересечении
зон ДО старта, а не после мерджа.

Реестр — детерминированный источник; НЕ блокирует файлы жёстко, а предупреждает
(«две сессии трогают dashboard-editor — риск конфликта») и предлагает решение.

Использование:
  active_work.py register <file> <id> --branch B --areas a,b --session S [--workitem P] [--status in-progress] [--at DATE]
  active_work.py list     <file> [--json]
  active_work.py check    <file> --areas a,b [--exclude id] [--json]     # только прогноз пересечений
  active_work.py finish   <file> <id>                                    # пометить done
  active_work.py --selftest
Возврат: 0 — ок (для check: 0 даже при пересечениях — это предупреждение, не ошибка);
1 — ошибка использования/данных.
"""

import argparse
import json
import sys
from pathlib import Path

import yaml

STATUS = {"in-progress", "review", "blocked", "done"}


def load(path: Path):
    if not path.exists():
        return {"schema_version": 1, "kind": "active-work", "active": []}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data.setdefault("schema_version", 1)
    data.setdefault("kind", "active-work")
    data.setdefault("active", [])
    return data


def save(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def overlaps(active, areas, exclude_id=None):
    """Активные работы (кроме done и exclude_id), чьи зоны пересекаются с areas."""
    want = set(areas)
    out = []
    for w in active:
        if w.get("status") == "done" or w.get("id") == exclude_id:
            continue
        shared = sorted(want & set(w.get("affected_areas") or []))
        if shared:
            out.append({"id": w.get("id"), "branch": w.get("branch"),
                        "owner_session": w.get("owner_session"), "shared_areas": shared})
    return out


def _forecast_lines(confs):
    lines = []
    for c in confs:
        lines.append(f"  ⚠ пересечение с '{c['id']}' (ветка {c['branch']}, сессия "
                     f"{c['owner_session']}): общие зоны {', '.join(c['shared_areas'])}")
    if confs:
        lines.append("  Варианты: дождаться · перенести зависимость · объединить задачи · "
                     "зафиксировать общий контракт · работать в разных слоях.")
    return lines


def register(path, wid, branch, areas, session, workitem=None, status="in-progress", at=None):
    if branch in (None, "", "main", "master"):
        print("ОШИБКА: работа не должна вестись в main/master — задайте ветку/worktree.")
        return 1
    if status not in STATUS:
        print(f"ОШИБКА: status '{status}' не в {sorted(STATUS)}")
        return 1
    if not areas:
        print("ОШИБКА: нужны affected_areas (основа conflict forecast).")
        return 1
    data = load(path)
    confs = overlaps(data["active"], areas, exclude_id=wid)
    entry = {"id": wid, "branch": branch, "status": status,
             "affected_areas": list(areas), "owner_session": session}
    if workitem:
        entry["workitem"] = workitem
    if at:
        entry["started_at"] = at
    data["active"] = [w for w in data["active"] if w.get("id") != wid] + [entry]
    save(path, data)
    print(f"ACTIVE-WORK: зарегистрирована работа '{wid}' (ветка {branch}, сессия {session}).")
    for line in _forecast_lines(confs):
        print(line)
    return 0


def list_cmd(path, as_json=False):
    data = load(path)
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    act = [w for w in data["active"] if w.get("status") != "done"]
    if not act:
        print("ACTIVE-WORK: активных работ нет.")
        return 0
    print(f"ACTIVE-WORK: {len(act)} активных работ:")
    for w in act:
        print(f"  - {w.get('id')} [{w.get('status')}] ветка {w.get('branch')} "
              f"зоны: {', '.join(w.get('affected_areas') or [])} (сессия {w.get('owner_session')})")
    return 0


def check_cmd(path, areas, exclude_id=None, as_json=False):
    data = load(path)
    confs = overlaps(data["active"], areas, exclude_id=exclude_id)
    if as_json:
        print(json.dumps({"schema_version": 1, "kind": "conflict-forecast",
                          "areas": list(areas), "conflicts": confs}, ensure_ascii=False, indent=2))
        return 0
    if not confs:
        print(f"CONFLICT-FORECAST: пересечений по зонам {', '.join(areas)} нет — можно стартовать.")
        return 0
    print(f"CONFLICT-FORECAST: возможны пересечения по зонам {', '.join(areas)}:")
    for line in _forecast_lines(confs):
        print(line)
    return 0


def finish_cmd(path, wid):
    data = load(path)
    found = False
    for w in data["active"]:
        if w.get("id") == wid:
            w["status"] = "done"
            found = True
    if not found:
        print(f"ACTIVE-WORK: работа '{wid}' не найдена.")
        return 1
    save(path, data)
    print(f"ACTIVE-WORK: работа '{wid}' помечена done.")
    return 0


def selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "active-work.yaml"
        register(p, "dashboard-editing", "feature/dashboard-editing",
                 ["dashboard-editor", "session-context"], "session-1", at="2026-07-15")
        d = load(p)
        expect("register: запись добавлена", any(w["id"] == "dashboard-editing" for w in d["active"]))

        expect("register в main -> ошибка", register(p, "x", "main", ["a"], "s") == 1)
        expect("register без areas -> ошибка", register(p, "x", "feature/x", [], "s") == 1)

        # пересечение по зоне session-context
        confs = overlaps(d["active"], ["session-context", "catalog"])
        expect("overlaps: находит пересечение зоны", any(c["id"] == "dashboard-editing"
               and "session-context" in c["shared_areas"] for c in confs))

        # непересекающаяся работа
        confs2 = overlaps(d["active"], ["catalog", "api"])
        expect("overlaps: непересекающиеся зоны -> пусто", confs2 == [])

        # exclude_id: сама себя не считает конфликтом
        confs3 = overlaps(d["active"], ["dashboard-editor"], exclude_id="dashboard-editing")
        expect("overlaps: exclude_id исключает себя", confs3 == [])

        # done не участвует в прогнозе
        finish_cmd(p, "dashboard-editing")
        confs4 = overlaps(load(p)["active"], ["dashboard-editor"])
        expect("done не даёт conflict forecast", confs4 == [])

        # реестр валиден по схеме (проверяем форму)
        d2 = load(p)
        expect("форма: kind active-work", d2.get("kind") == "active-work")

    print("active_work selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    ap = argparse.ArgumentParser(prog="active_work.py")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("register")
    r.add_argument("file"); r.add_argument("id")
    r.add_argument("--branch", required=True)
    r.add_argument("--areas", required=True, help="через запятую")
    r.add_argument("--session", required=True)
    r.add_argument("--workitem")
    r.add_argument("--status", default="in-progress")
    r.add_argument("--at")

    l = sub.add_parser("list")
    l.add_argument("file"); l.add_argument("--json", action="store_true")

    c = sub.add_parser("check")
    c.add_argument("file"); c.add_argument("--areas", required=True)
    c.add_argument("--exclude"); c.add_argument("--json", action="store_true")

    f = sub.add_parser("finish")
    f.add_argument("file"); f.add_argument("id")

    a = ap.parse_args(argv)
    if a.cmd == "register":
        areas = [x.strip() for x in a.areas.split(",") if x.strip()]
        return register(Path(a.file), a.id, a.branch, areas, a.session, a.workitem, a.status, a.at)
    if a.cmd == "list":
        return list_cmd(Path(a.file), a.json)
    if a.cmd == "check":
        areas = [x.strip() for x in a.areas.split(",") if x.strip()]
        return check_cmd(Path(a.file), areas, a.exclude, a.json)
    if a.cmd == "finish":
        return finish_cmd(Path(a.file), a.id)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
