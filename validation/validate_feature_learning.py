#!/usr/bin/env python3
"""Проверка FeatureLearning (product-learning/*.yaml) — v3.3 Product Learning.

FeatureLearning (schemas/feature-learning.schema.json) — мост research-решение (DecisionPackage) ->
продуктовый/архитектурный исход. Валидатор держит его честным структурно, семантически и как реестр:

  1. schema_version=1, kind=FeatureLearning; id формата FL-NNN; feature/hypothesis непусты;
  2. validation.status ∈ planned|running|done; outcome.verdict ∈ pending|confirmed|refuted|inconclusive;
  3. НЕЛЬЗЯ вынести вердикт (confirmed/refuted/inconclusive) без завершённой проверки:
     verdict != pending ТРЕБУЕТ validation.status=done И validation.result непуст;
  4. refuted ТРЕБУЕТ непустой learnings (опровержение без урока — потеря знания);
  5. status=validated требует validation.status=done; status=closed требует verdict != pending;
  6. decision_package — DP-NNN или null (СЛАБАЯ ссылка: файловой целостности к .research/ НЕ требуем,
     чтобы не привязываться к параллельно управляемому research-контуру);
  7. реестр: id уникальны, имя файла == id.

Использование:  validate_feature_learning.py [product-learning] [--json] | --selftest
Возврат 0 — валиден/целостен, 1 — ошибки.
"""
import json
import re
import sys
from pathlib import Path

import yaml

PKG = Path(__file__).resolve().parents[1]
SCHEMA = PKG / "schemas" / "feature-learning.schema.json"
DEFAULT_DIR = PKG / "product-learning"

VAL_STATUS = {"planned", "running", "done"}
VERDICT = {"pending", "confirmed", "refuted", "inconclusive"}
STATUS = {"open", "validated", "closed"}
_FL = re.compile(r"^FL-[0-9]{3,}$")
_DP = re.compile(r"^DP-[0-9]{3,}$")


def check(data: dict):
    e = []
    if not isinstance(data, dict):
        return ["FeatureLearning не объект"]
    if data.get("schema_version") != 1:
        e.append("schema_version должен быть 1")
    if data.get("kind") != "FeatureLearning":
        e.append("kind должен быть 'FeatureLearning'")
    if not (isinstance(data.get("id"), str) and _FL.match(data["id"])):
        e.append("id должен быть формата FL-NNN")
    for f in ("feature", "hypothesis"):
        if not (isinstance(data.get(f), str) and data[f].strip()):
            e.append(f"{f} обязателен и непуст")
    dp = data.get("decision_package")
    if dp is not None and not (isinstance(dp, str) and _DP.match(dp)):
        e.append("decision_package должен быть DP-NNN или null")

    val = data.get("validation")
    vstatus = None
    if not isinstance(val, dict):
        e.append("validation обязателен (объект method+status)")
    else:
        if not (isinstance(val.get("method"), str) and val["method"].strip()):
            e.append("validation.method обязателен и непуст")
        vstatus = val.get("status")
        if vstatus not in VAL_STATUS:
            e.append(f"validation.status ∉ {sorted(VAL_STATUS)}")

    out = data.get("outcome")
    verdict = None
    if not isinstance(out, dict):
        e.append("outcome обязателен (объект verdict)")
    else:
        verdict = out.get("verdict")
        if verdict not in VERDICT:
            e.append(f"outcome.verdict ∉ {sorted(VERDICT)}")

    status = data.get("status")
    if status not in STATUS:
        e.append(f"status ∉ {sorted(STATUS)}")

    # семантика: вердикт без завершённой проверки — нельзя
    if verdict in ("confirmed", "refuted", "inconclusive"):
        if vstatus != "done":
            e.append(f"verdict={verdict} требует validation.status=done (нет проверки — нет вердикта)")
        if not (isinstance(val, dict) and (val.get("result") or "").strip()):
            e.append(f"verdict={verdict} требует непустой validation.result")
    if verdict == "refuted" and not (data.get("learnings") or []):
        e.append("verdict=refuted требует непустой learnings (опровержение без урока — потеря знания)")
    if status == "validated" and vstatus != "done":
        e.append("status=validated требует validation.status=done")
    if status == "closed" and verdict == "pending":
        e.append("status=closed требует вынесенный verdict (не pending)")

    for f in ("learnings", "follow_up"):
        v = data.get(f)
        if v is not None and not (isinstance(v, list) and all(isinstance(x, str) for x in v)):
            e.append(f"{f} должен быть списком строк")
    return e


def check_registry(fl_dir: Path):
    errors, ids = [], set()
    files = sorted(Path(fl_dir).glob("FL-*.yaml")) if Path(fl_dir).is_dir() else []
    for f in files:
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
        except yaml.YAMLError as ex:
            errors.append(f"{f.name}: не парсится YAML ({ex})")
            continue
        for x in check(data):
            errors.append(f"{f.name}: {x}")
        aid = (data or {}).get("id")
        if isinstance(aid, str):
            if f.stem != aid:
                errors.append(f"{f.name}: имя файла != id ({aid})")
            if aid in ids:
                errors.append(f"дубликат id {aid}")
            ids.add(aid)
    return errors, ids


def selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    ex = json.loads(SCHEMA.read_text(encoding="utf-8"))["examples"][0]
    expect("пример из схемы валиден", check(ex) == [])

    # реальный реестр product-learning целостен
    reg_errs, ids = check_registry(DEFAULT_DIR)
    expect(f"реальный product-learning реестр целостен ({len(ids)} FL)", reg_errs == [])

    expect("verdict без validation.done -> ошибка",
           any("validation.status=done" in x for x in check({**ex,
               "validation": {"method": "m", "status": "running", "result": None},
               "status": "open"})))
    expect("verdict без result -> ошибка",
           any("result" in x for x in check({**ex,
               "validation": {"method": "m", "status": "done", "result": ""}})))
    expect("refuted без learnings -> ошибка",
           any("learnings" in x for x in check({**ex,
               "outcome": {"verdict": "refuted", "expected": "e", "actual": "a"}, "learnings": []})))
    expect("status=validated при незавершённой проверке -> ошибка",
           any("validated" in x for x in check({**ex, "status": "validated",
               "validation": {"method": "m", "status": "planned", "result": None},
               "outcome": {"verdict": "pending"}})))
    expect("status=closed при pending verdict -> ошибка",
           any("closed" in x for x in check({**ex, "status": "closed",
               "outcome": {"verdict": "pending"}})))
    expect("битый id -> ошибка", any("id" in x for x in check({**ex, "id": "FL1"})))
    expect("битый decision_package -> ошибка",
           any("decision_package" in x for x in check({**ex, "decision_package": "108"})))
    expect("decision_package=null валиден", check({**ex, "decision_package": None}) == [])

    # реестр: имя файла != id
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "FL-050.yaml").write_text(yaml.safe_dump({**ex, "id": "FL-777"}), encoding="utf-8")
        e, _ = check_registry(Path(td))
        expect("реестр ловит имя файла != id", any("имя файла" in x for x in e))

    # drift-guard enum
    sch = json.loads(SCHEMA.read_text(encoding="utf-8"))
    expect("enum verdict == схема",
           set(sch["properties"]["outcome"]["properties"]["verdict"]["enum"]) == VERDICT)

    print("validate_feature_learning selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    args = [a for a in argv if not a.startswith("--")]
    fl_dir = Path(args[0]) if args else DEFAULT_DIR
    errors, ids = check_registry(fl_dir)
    if "--json" in argv:
        print(json.dumps({"count": len(ids), "errors": errors}, ensure_ascii=False, indent=2))
    elif errors:
        print(f"FEATURE-LEARNING: {len(errors)} нарушений:")
        for x in errors:
            print(f"  - {x}")
    else:
        print(f"FEATURE-LEARNING-OK: {len(ids)} FL, реестр целостен.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
