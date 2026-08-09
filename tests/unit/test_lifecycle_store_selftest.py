"""Селфтест lifecycle_store, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from lifecycle_store import (  # noqa: F401 — имена, которые использует тело
    Path,
    durable_write,
    durable_write_json,
    journal_append,
    journal_read,
    load_guarded,
    validate_trace,
)


@pytest.mark.slow
def test_lifecycle_store_selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        p = root / "sub" / "x.yaml"
        # durable_write: round-trip + создание каталога + перечитывание
        w = durable_write(p, {"kind": "t", "a": 1}, require_keys=("kind", "a"))
        expect("durable_write: ok, файл создан с каталогом", w["ok"] and p.is_file())
        expect("durable_write: временный .tmp не остался", not (root / "sub" / "x.yaml.tmp").exists())
        # require_keys не выполнены -> ok=False (fail-closed)
        w2 = durable_write(root / "y.yaml", {"kind": "t"}, require_keys=("kind", "missing"))
        expect("durable_write: отсутствует required key -> ok=False", not w2["ok"] and "missing" in w2["error"])

        # load_guarded: ok
        g = load_guarded(p, required_keys=("kind", "a"), kind="t")
        expect("load_guarded: валидный -> state=ok + data", g["state"] == "ok" and g["data"]["a"] == 1)
        # absent
        expect("load_guarded: нет файла -> absent", load_guarded(root / "nope.yaml")["state"] == "absent")
        # corrupt: пустой файл
        (root / "empty.yaml").write_text("", encoding="utf-8")
        expect("load_guarded: пустой файл -> corrupt (не absent)",
               load_guarded(root / "empty.yaml")["state"] == "corrupt")
        # corrupt: битый YAML
        (root / "bad.yaml").write_text("a: [1, 2\n  b: {", encoding="utf-8")
        expect("load_guarded: битый YAML -> corrupt", load_guarded(root / "bad.yaml")["state"] == "corrupt")
        # corrupt: не dict
        (root / "scalar.yaml").write_text("just a string\n", encoding="utf-8")
        expect("load_guarded: не dict -> corrupt", load_guarded(root / "scalar.yaml")["state"] == "corrupt")
        # corrupt: не тот kind
        expect("load_guarded: не тот kind -> corrupt",
               load_guarded(p, kind="other")["state"] == "corrupt")
        # corrupt: нет обязательного ключа
        expect("load_guarded: нет обязательного ключа -> corrupt",
               load_guarded(p, required_keys=("kind", "zzz"))["state"] == "corrupt")

        # v3.0.14 (#2): durable_write_json — round-trip + require_keys
        jp = root / "r.json"
        wj = durable_write_json(jp, {"kind": "run-report", "status": "ok"}, require_keys=("kind", "status"))
        expect("durable_write_json: ok + файл создан", wj["ok"] and jp.is_file())
        expect("durable_write_json: отсутствует required key -> ok=False",
               not durable_write_json(root / "r2.json", {"kind": "x"}, require_keys=("kind", "miss"))["ok"])

        # v3.0.15 (LifecycleStore v1.1, P1): validate-before-replace — невалидная запись НЕ затирает
        # прежний валидный файл (валидация до os.replace), и не остаётся мусорных temp.
        good = root / "src.yaml"
        durable_write(good, {"kind": "t", "n": 1}, require_keys=("kind", "n"))
        _before = good.read_text(encoding="utf-8")
        _bad = durable_write(good, {"kind": "t"}, require_keys=("kind", "n"))   # нет required n
        expect("v3.0.15: невалидная запись -> ok=False", not _bad["ok"])
        expect("v3.0.15: прежний валидный файл НЕ затёрт невалидной записью",
               good.read_text(encoding="utf-8") == _before)
        expect("v3.0.15: не dict -> ok=False, файл цел",
               not durable_write(good, "не dict")["ok"]
               and good.read_text(encoding="utf-8") == _before)
        expect("v3.0.15: нет остаточных .tmp после операций",
               not any(x.name.endswith(".tmp") or ".tmp" in x.name for x in good.parent.iterdir()))
        # keep_backup сохраняет ссылку на прежнее валидное состояние
        durable_write(good, {"kind": "t", "n": 2}, require_keys=("kind", "n"), keep_backup=True)
        expect("v3.0.15: keep_backup -> .bak с прежним валидным состоянием",
               (good.with_suffix(good.suffix + ".bak")).is_file())

        # v3.0.14 (#3): event journal — append-only, checksum-цепочка, обнаружение подмены
        jn = root / "journal.jsonl"
        journal_append(jn, {"kind": "run_start", "run_id": "R1", "workitem_id": "w"})
        journal_append(jn, {"kind": "package_start", "run_id": "R1", "package_id": "WP1"})
        journal_append(jn, {"kind": "gate", "run_id": "R1", "package_id": "WP1", "gate": "security", "status": "pass"})
        jr = journal_read(jn)
        expect("journal: 3 события, цепочка цела (ok)", jr["ok"] and len(jr["events"]) == 3)
        expect("journal: seq монотонный 0,1,2", [e["seq"] for e in jr["events"]] == [0, 1, 2])
        expect("journal: Run->Package->Gate связи сохранены",
               jr["events"][2]["run_id"] == "R1" and jr["events"][2]["package_id"] == "WP1"
               and jr["events"][2]["gate"] == "security")
        # подмена средней строки -> цепочка/checksum рвётся -> ok=False
        _lines = jn.read_text(encoding="utf-8").splitlines()
        import json as _js
        _tamp = _js.loads(_lines[1]); _tamp["status"] = "HACKED"
        _lines[1] = _js.dumps(_tamp, ensure_ascii=False)
        jn.write_text("\n".join(_lines) + "\n", encoding="utf-8")
        expect("journal: подмена строки -> обнаружено (ok=False, broken_at)",
               journal_read(jn)["ok"] is False)
        # усечение (crash в середине записи) -> оборванная строка -> ok=False
        jn2 = root / "j2.jsonl"
        journal_append(jn2, {"kind": "run_start", "run_id": "R2"})
        with open(jn2, "a", encoding="utf-8") as _f:
            _f.write('{"kind": "run_end", "run_i')   # оборванная запись без \n
        expect("journal: усечённая последняя строка -> ok=False", journal_read(jn2)["ok"] is False)

        # v3.1 (trace v0.2): verify-before-append — на битый журнал не дописываем
        jn3 = root / "j3.jsonl"
        journal_append(jn3, {"kind": "run_start", "run_id": "R3"})
        journal_append(jn3, {"kind": "package_end", "run_id": "R3", "package_id": "P1"})
        _l3 = jn3.read_text(encoding="utf-8").splitlines()
        _t = _js.loads(_l3[0]); _t["run_id"] = "TAMPER"; _l3[0] = _js.dumps(_t, ensure_ascii=False)
        jn3.write_text("\n".join(_l3) + "\n", encoding="utf-8")   # подмена -> цепочка битая
        _ap = journal_append(jn3, {"kind": "run_end", "run_id": "R3"})
        expect("v3.1 journal v0.2: append на битую цепочку -> ok=False (не расширяем повреждённое)",
               _ap["ok"] is False and "повреждён" in _ap.get("error", ""))

        # v3.1 (trace v0.2): head-marker ловит усечение ЦЕЛОЙ последней строки (v0.1 не мог)
        jn4 = root / "j4.jsonl"
        journal_append(jn4, {"kind": "run_start", "run_id": "R4"})
        journal_append(jn4, {"kind": "run_end", "run_id": "R4"})
        expect("v3.1 journal v0.2: цела -> ok (head-marker есть)",
               journal_read(jn4)["ok"] and (root / "j4.jsonl.head").exists())
        _l4 = jn4.read_text(encoding="utf-8").splitlines()
        jn4.write_text(_l4[0] + "\n", encoding="utf-8")   # удаляем последнюю ЦЕЛУЮ строку (валидный префикс)
        _r4 = journal_read(jn4)
        expect("v3.1 journal v0.2: удалена целая последняя строка -> ok=False (head-marker детектит усечение)",
               _r4["ok"] is False and "усечение" in (_r4.get("reason") or ""))

        # v3.1 (trace v0.2): validate_trace — обязательные ID своей связи
        _good = [{"kind": "run_start", "run_id": "R", "workitem_id": "R", "attempt_id": "R#a1"},
                 {"kind": "package_end", "run_id": "R", "workitem_id": "R", "package_id": "WP1"},
                 {"kind": "delivery_receipt", "run_id": "R", "delivery_id": "d1"},
                 {"kind": "run_end", "run_id": "R", "workitem_id": "R", "attempt_id": "R#a1", "status": "delivered"}]
        expect("v3.1 trace-schema: полный валидный трейс -> нет ошибок", validate_trace(_good) == [])
        expect("v3.1 trace-schema: package_end без package_id -> ошибка",
               any("package_id" in e for e in validate_trace([{"kind": "package_end", "run_id": "R", "workitem_id": "R"}])))
        expect("v3.1 trace-schema: delivery без delivery_id -> ошибка",
               any("delivery_id" in e for e in validate_trace([{"kind": "delivery", "run_id": "R"}])))
        expect("v3.1 trace-schema: run_start без attempt_id -> ошибка",
               any("attempt_id" in e for e in validate_trace([{"kind": "run_start", "run_id": "R", "workitem_id": "R"}])))

    assert ok, "перенесённый селфтест lifecycle_store: см. строки FAIL в выводе"
