#!/usr/bin/env python3
"""Validate model-qualification registry (ДОКАЗАТЕЛЬНЫЙ допуск model×revision×role, ADR-004).

Ревью: матрица допуска была class×role и вручную вписана — слишком грубо и не из Bench. Здесь допуск
привязан к КОНКРЕТНОЙ ревизии модели по роли, а СТАТУС ВЫВОДИТСЯ ИЗ МЕТРИК (не декларируется свободно):
  - false_green>0                                   -> not_qualified (safety-first, НИКОГДА иначе);
  - qualified   := false_green==0 & success>=0.8 & schema_valid>=0.9;
  - conditional := false_green==0 & success>=0.5 & не qualified;
  - experimental:= false_green==0 & success>0 & не conditional;
  - иначе       -> not_qualified.
Валидатор ПРИНУЖДАЕТ: заявленный status == выведенный из метрик (нельзя объявить qualified при
false_green>0 или низком success). Плюс: model_id есть в models.yaml, provider совпадает, роль известна.

  validate_model_qualification.py [registry/model-qualification.yaml] | --selftest
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

PKG = Path(__file__).resolve().parents[1]
DEFAULT = PKG / "registry" / "model-qualification.yaml"
ROLES = {"implementation", "code_review", "security_review", "integration_judge"}
STATUS = {"qualified", "conditional", "experimental", "not_qualified"}
Q_SUCCESS, Q_SCHEMA, C_SUCCESS = 0.8, 0.9, 0.5


def derive_status(m):
    """Статус ИЗ метрик (safety-first). m: {false_green, success_rate, schema_valid_rate}."""
    fg = m.get("false_green", 1)
    sr = float(m.get("success_rate", 0) or 0)
    sv = float(m.get("schema_valid_rate", 0) or 0)
    if fg is None or fg > 0:
        return "not_qualified"
    if sr >= Q_SUCCESS and sv >= Q_SCHEMA:
        return "qualified"
    if sr >= C_SUCCESS:
        return "conditional"
    if sr > 0:
        return "experimental"
    return "not_qualified"


def _model_index(pkg=PKG):
    try:
        d = yaml.safe_load((pkg / "registry" / "models.yaml").read_text(encoding="utf-8"))
        return {m["id"]: m for m in d.get("models", []) if m.get("id")}
    except OSError:
        return {}


def check(data, pkg=PKG):
    e = []
    if not isinstance(data, dict) or data.get("registry_type") != "model-qualification":
        return ["registry_type должен быть model-qualification"]
    models = _model_index(pkg)
    quals = data.get("qualifications")
    if not isinstance(quals, list) or not quals:
        return e + ["qualifications непустой список обязателен"]
    seen = set()
    for q in quals:
        if not isinstance(q, dict):
            e.append("qualification не объект"); continue
        mid, role = q.get("model_id"), q.get("role")
        key = (mid, q.get("revision"), role)
        if key in seen:
            e.append(f"дубликат допуска {key}")
        seen.add(key)
        if role not in ROLES:
            e.append(f"{mid}: роль '{role}' ∉ {sorted(ROLES)}")
        if models and mid not in models:
            e.append(f"model_id '{mid}' нет в models.yaml")
        elif models and q.get("provider") and models[mid].get("provider") != q.get("provider"):
            e.append(f"{mid}: provider '{q.get('provider')}' != models.yaml '{models[mid].get('provider')}'")
        if not q.get("revision"):
            e.append(f"{mid}/{role}: нет revision (допуск по КОНКРЕТНОЙ ревизии)")
        if not q.get("corpus_version"):
            e.append(f"{mid}/{role}: нет corpus_version (из какого Bench)")
        m = q.get("metrics")
        if not isinstance(m, dict) or "false_green" not in m or "success_rate" not in m:
            e.append(f"{mid}/{role}: metrics обязаны нести хотя бы false_green + success_rate")
            continue
        if q.get("status") not in STATUS:
            e.append(f"{mid}/{role}: status ∉ {sorted(STATUS)}")
            continue
        derived = derive_status(m)
        if q["status"] != derived:
            e.append(f"{mid}/{role}: заявлен status='{q['status']}', но метрики дают '{derived}' "
                     f"(допуск не из Bench — safety нарушен)")
    return e


def selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    expect("derive: false_green>0 -> not_qualified (safety)", derive_status({"false_green": 1, "success_rate": 0.99, "schema_valid_rate": 0.99}) == "not_qualified")
    expect("derive: 0 fg + high -> qualified", derive_status({"false_green": 0, "success_rate": 0.85, "schema_valid_rate": 0.95}) == "qualified")
    expect("derive: 0 fg + средний -> conditional", derive_status({"false_green": 0, "success_rate": 0.6, "schema_valid_rate": 0.8}) == "conditional")
    expect("derive: 0 fg + низкий -> experimental", derive_status({"false_green": 0, "success_rate": 0.2, "schema_valid_rate": 0.4}) == "experimental")

    base = {"registry_type": "model-qualification", "qualifications": [
        {"model_id": "kimi-k3", "provider": "kimi", "revision": "kimi-k3", "role": "implementation",
         "corpus_version": "t", "metrics": {"false_green": 0, "success_rate": 0.85, "schema_valid_rate": 0.95},
         "status": "qualified"}]}
    expect("валидный (status из метрик) проходит", check(base) == [])
    lie = {**base, "qualifications": [{**base["qualifications"][0], "status": "qualified",
           "metrics": {"false_green": 1, "success_rate": 0.9, "schema_valid_rate": 0.9}}]}
    expect("qualified при false_green>0 -> ошибка (safety-first)",
           any("safety" in x or "метрики дают" in x for x in check(lie)))
    lie2 = {**base, "qualifications": [{**base["qualifications"][0], "status": "qualified",
            "metrics": {"false_green": 0, "success_rate": 0.3, "schema_valid_rate": 0.4}}]}
    expect("qualified при низком success -> ошибка (не из Bench)",
           any("метрики дают" in x for x in check(lie2)))
    expect("несуществующий model_id -> ошибка",
           any("нет в models.yaml" in x for x in check({**base, "qualifications": [{**base["qualifications"][0], "model_id": "ghost-model"}]})))

    if DEFAULT.exists():
        errs = check(yaml.safe_load(DEFAULT.read_text(encoding="utf-8")))
        expect("реальный model-qualification.yaml валиден (status из метрик)", errs == [])
        for x in errs:
            print("   -", x)

    print("validate_model_qualification selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    args = [a for a in argv if not a.startswith("--")]
    path = Path(args[0]) if args else DEFAULT
    errs = check(yaml.safe_load(path.read_text(encoding="utf-8")))
    if errs:
        print(f"MODEL-QUALIFICATION {path.name}: ошибки:")
        for x in errs:
            print(f"  - {x}")
        return 1
    print(f"MODEL-QUALIFICATION-OK: {path.name} — допуск согласован с Bench-метриками.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
