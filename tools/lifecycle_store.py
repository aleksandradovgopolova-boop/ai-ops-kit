#!/usr/bin/env python3
"""Durable lifecycle I/O (v3.0.12, finding аудита блока B) — единый контракт надёжной записи и
fail-closed чтения КРИТИЧЕСКИХ resume-артефактов (run-settings, run-handoff, active-work, SequencePlan).

Проблема (сквозной самоаудит): большинство lifecycle-файлов писались plain `write_text`/`json.dump`
(неатомарно, без fsync, без перечитывания), а битые/пустые читались как «отсутствующие» -> тихая
потеря policy и ложный «resume безопасен». Здесь — ОДИН источник истины:

  * durable_write — tmp -> flush+fsync(файл) -> os.replace -> fsync(КАТАЛОГ) -> перечитать+провалидировать;
  * load_guarded — различает ОТСУТСТВУЕТ / ПОВРЕЖДЁН (parse-error/пустой/не dict/не тот kind/нет ключей)
    и НЕ даёт вызывающему молча дефолтить или перезаписать повреждённый источник.

CLI: lifecycle_store.py --selftest
"""

import argparse
import os
import sys
from pathlib import Path

import yaml


def _durable(path, data, serialize, parse, require_keys, keep_backup):
    """v3.0.15 (LifecycleStore v1.1, finding аудита P1): АТОМАРНАЯ + FAIL-CLOSED запись с валидацией
    ПРОСПЕКТИВНОГО документа ДО os.replace (иначе программная ошибка могла заменить валидный файл
    невалидным, а потом вернуть ok=False — старый источник истины уже потерян). Порядок:
    validate(data) -> serialize -> validate(проспективный reparse) -> UNIQUE temp -> fsync ->
    [backup прежнего валидного] -> atomic replace -> fsync(dir) -> reread+validate -> cleanup temp.
    -> {ok} | {ok: False, error}."""
    import tempfile
    path = Path(path)
    # 1. валидируем ВХОД до любого касания целевого файла
    if not isinstance(data, dict):
        return {"ok": False, "error": "данные для записи не dict"}
    missing = [k for k in require_keys if k not in data]
    if missing:
        return {"ok": False, "error": f"перед записью отсутствуют ключи: {', '.join(missing)}"}
    try:
        text = serialize(data)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"сериализация не удалась: {type(e).__name__}: {e}"}
    # 2. проспективная валидация: сериализованное перечитывается в валидный dict — ДО замены старого файла
    try:
        prospective = parse(text)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"проспективный документ не парсится: {type(e).__name__}: {e}"}
    if not isinstance(prospective, dict) or [k for k in require_keys if k not in prospective]:
        return {"ok": False, "error": "проспективный документ невалиден — старый файл НЕ тронут"}
    tmp = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # 3. УНИКАЛЬНЫЙ temp (mkstemp) — конкурентные писатели не бьются об общий .tmp
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
        tmp = Path(tmp_name)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        # 4. backup прежнего валидного состояния (opt-in, для критических артефактов)
        if keep_backup and path.exists():
            try:
                path.with_suffix(path.suffix + ".bak").write_text(
                    path.read_text(encoding="utf-8"), encoding="utf-8")
            except OSError:
                pass
        # 5. атомарная замена + fsync каталога
        os.replace(str(tmp), str(path))
        tmp = None
        _fsync_dir(path.parent)
        # 6. повторная валидация ПОСЛЕ замены (defense-in-depth)
        back = parse(path.read_text(encoding="utf-8"))
        if not isinstance(back, dict) or [k for k in require_keys if k not in back]:
            return {"ok": False, "error": "перечитанный после замены документ невалиден"}
        return {"ok": True}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        if tmp is not None and Path(tmp).exists():
            try:
                Path(tmp).unlink()
            except OSError:
                pass


def durable_write(path, data, require_keys=(), keep_backup=False):
    """АТОМАРНАЯ + FAIL-CLOSED запись YAML-артефакта (LifecycleStore v1.1: validate-before-replace,
    unique temp, cleanup, opt-in backup). -> {ok} | {ok: False, error}. Вызывающий ОБЯЗАН остановиться
    при ok=False (нет источника истины)."""
    return _durable(path, data, lambda d: yaml.safe_dump(d, allow_unicode=True, sort_keys=False),
                    yaml.safe_load, require_keys, keep_backup)


def durable_write_json(path, data, require_keys=(), keep_backup=False):
    """v3.0.14/v3.0.15 (finding аудита #2/P1): durable JSON-запись (run-report/controller-report) с той же
    гарантией validate-before-replace, что durable_write. -> {ok} | {ok: False, error}."""
    import json as _json
    return _durable(path, data,
                    lambda d: _json.dumps(d, ensure_ascii=False, indent=2, default=str),
                    _json.loads, require_keys, keep_backup)


def _event_checksum(payload_str):
    import hashlib
    return hashlib.sha256(payload_str.encode("utf-8")).hexdigest()[:16]


def journal_append(journal_path, event):
    """v3.0.14 (finding аудита #3): bounded event journal (v0.1) — append-only JSONL с checksum-цепочкой.
    Каждое событие получает seq, prev-checksum (хэш предыдущей строки) и собственный checksum -> при
    чтении видно усечение/подмену/разрыв. Одна строка = атомарный append (open('a')+flush+fsync) —
    crash-boundary на уровне записи. event должен нести run/package/gate-связи (kind + ids). НЕ роняет
    вызывающего при сбое (журнал — наблюдаемость, не источник истины). -> {ok} | {ok: False, error}.

    ЧЕСТНЫЕ ОГРАНИЧЕНИЯ v0.1 (не полагаться на журнал для восстановления состояния или qualification-
    вердикта — это делают durable-артефакты): append НЕ под отдельной блокировкой (два процесса могут
    получить одинаковые seq/prev_checksum); удаление последней ЦЕЛОЙ строки оставляет валидный префикс и
    НЕ детектится как усечение; перед append НЕ проверяется вся существующая цепочка; сбой журнала
    сознательно НЕ блокирует прогон. Полный audit trail (лок, полная верификация цепочки, Run/Attempt/
    Package/Gate как первичный контракт) — event journal v0.2 (v3.1)."""
    import json as _json
    journal_path = Path(journal_path)
    try:
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        prev_checksum, seq = None, 0
        if journal_path.exists():
            lines = [ln for ln in journal_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
            if lines:
                try:
                    last = _json.loads(lines[-1])
                    prev_checksum = last.get("checksum")
                    seq = int(last.get("seq", len(lines) - 1)) + 1
                except (ValueError, TypeError):
                    seq = len(lines)
        rec = {**event, "seq": seq, "prev_checksum": prev_checksum}
        # checksum считается по канонической форме события БЕЗ поля checksum (детерминированно)
        rec["checksum"] = _event_checksum(_json.dumps(rec, sort_keys=True, ensure_ascii=False))
        line = _json.dumps(rec, ensure_ascii=False)
        with open(journal_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())
        return {"ok": True, "seq": seq}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def journal_read(journal_path):
    """Прочитать event journal и ПРОВЕРИТЬ целостность checksum-цепочки. -> {events:[...], ok:bool,
    broken_at?: seq}. ok=False -> усечение/подмена/разрыв цепочки (crash в середине записи, tamper)."""
    import json as _json
    journal_path = Path(journal_path)
    if not journal_path.exists():
        return {"events": [], "ok": True}
    events, ok, broken_at, prev = [], True, None, None
    for i, ln in enumerate(l for l in journal_path.read_text(encoding="utf-8").splitlines() if l.strip()):
        try:
            rec = _json.loads(ln)
        except ValueError:
            ok, broken_at = False, i
            break
        stored = rec.get("checksum")
        recomputed = _event_checksum(_json.dumps({k: v for k, v in rec.items() if k != "checksum"},
                                                 sort_keys=True, ensure_ascii=False))
        if stored != recomputed or rec.get("prev_checksum") != prev:
            ok, broken_at = False, rec.get("seq", i)
            break
        prev = stored
        events.append(rec)
    out = {"events": events, "ok": ok}
    if broken_at is not None:
        out["broken_at"] = broken_at
    return out


def _fsync_dir(directory):
    """fsync каталога — иначе питание сразу после os.replace могло потерять сам rename, хотя контент
    уже на диске. best-effort: не все ФС/платформы дают fsync каталога (Windows/некоторые сетевые ФС)."""
    try:
        dfd = os.open(str(directory), os.O_DIRECTORY)
    except (OSError, AttributeError):
        return
    try:
        os.fsync(dfd)
    except OSError:
        pass
    finally:
        os.close(dfd)


def load_guarded(path, required_keys=(), kind=None):
    """FAIL-CLOSED чтение. Различает три состояния (а не «пусто -> дефолт»):
      * absent  — файла нет (легитимно fresh);
      * corrupt — есть, но НЕЧИТАЕМ/пуст/не dict/не тот kind/нет обязательных ключей (оборванная запись,
                  внешнее усечение) -> вызывающий НЕ должен дефолтить/перезаписывать;
      * ok      — валиден, data приложена.
    -> {state, data?, reason?}."""
    path = Path(path)
    if not path.exists():
        return {"state": "absent"}
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        return {"state": "corrupt", "reason": f"не читается: {type(e).__name__}: {e}"}
    if raw.strip() == "":
        return {"state": "corrupt", "reason": "файл пуст (вероятно, оборванная запись)"}
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        return {"state": "corrupt", "reason": f"YAML не парсится: {str(e)[:160]}"}
    if not isinstance(data, dict):
        return {"state": "corrupt", "reason": f"не dict ({type(data).__name__})"}
    if kind is not None and data.get("kind") != kind:
        return {"state": "corrupt", "reason": f"kind != {kind} ({data.get('kind')})"}
    missing = [k for k in required_keys if data.get(k) in (None, "")]
    if missing:
        return {"state": "corrupt", "reason": f"нет обязательных полей: {', '.join(missing)}"}
    return {"state": "ok", "data": data}


def selftest():
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

    print("lifecycle_store selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv):
    ap = argparse.ArgumentParser(prog="lifecycle_store.py")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
