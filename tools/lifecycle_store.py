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


def durable_write(path, data, require_keys=()):
    """АТОМАРНАЯ + FAIL-CLOSED запись YAML-артефакта. tmp -> flush+fsync(файл) -> atomic os.replace ->
    fsync(каталог, чтобы rename пережил потерю питания) -> ПЕРЕЧИТАТЬ и провалидировать (dict + ключи).
    -> {ok: True} | {ok: False, error}. Вызывающий ОБЯЗАН остановиться при ok=False (нет источника истины)."""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)                      # атомарно на том же ФС
        _fsync_dir(path.parent)                     # durability самого rename
        back = yaml.safe_load(path.read_text(encoding="utf-8"))   # перечитать и проверить
        if not isinstance(back, dict):
            return {"ok": False, "error": "перечитанный артефакт не dict"}
        missing = [k for k in require_keys if k not in back]
        if missing:
            return {"ok": False, "error": f"после записи отсутствуют ключи: {', '.join(missing)}"}
        return {"ok": True}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


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
