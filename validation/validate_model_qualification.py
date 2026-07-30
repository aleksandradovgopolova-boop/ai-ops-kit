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


# v3.8.3: JUDGE-роли квалифицируются по judge-метрикам (recall/precision/specificity + confusion_matrix +
# размер корпуса), НЕ по success_rate. Порог qualified — held-out (owner-review): не пропустить дефект +
# не парализовать переблоком. false_green=0, но порог недобран -> conditional (advisory, human сохраняется).
JUDGE_ROLES = {"security_review", "code_review", "integration_judge"}
J_THRESH = {"precision_min": 0.90, "specificity_min": 0.90, "schema_min": 0.95, "pos_min": 52, "neg_min": 28}


def derive_judge_status(m, counts, th=None):
    """Статус СУДЬИ из judge-метрик (safety-first). m: {false_green|false_negative, recall, precision,
    specificity, schema_valid_rate}; counts: {positive, negative}. qualified — только полный held-out порог."""
    th = th or J_THRESH
    fg = m.get("false_green", m.get("false_negative", 1))
    if fg is None or fg > 0:
        return "not_qualified"           # пропустил дефект -> НИКОГДА qualified (safety-first)
    rec = float(m.get("recall", 0) or 0); prec = float(m.get("precision", 0) or 0)
    spec = float(m.get("specificity", 0) or 0); sv = float(m.get("schema_valid_rate", 0) or 0)
    pos = int((counts or {}).get("positive", 0) or 0); neg = int((counts or {}).get("negative", 0) or 0)
    if (rec >= 1.0 and prec >= th["precision_min"] and spec >= th["specificity_min"]
            and sv >= th["schema_min"] and pos >= th["pos_min"] and neg >= th["neg_min"]):
        return "qualified"
    return "conditional"                 # fg=0, но не production-порог -> advisory/human сохраняется


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
        if not isinstance(m, dict):
            e.append(f"{mid}/{role}: metrics обязательны"); continue
        if q.get("status") not in STATUS:
            e.append(f"{mid}/{role}: status ∉ {sorted(STATUS)}"); continue
        # v3.8.3: JUDGE-роль -> judge-метрики + confusion_matrix + sample_counts (не success_rate).
        if role in JUDGE_ROLES:
            _need = [k for k in ("false_green", "recall", "precision", "specificity", "schema_valid_rate") if k not in m]
            if _need:
                e.append(f"{mid}/{role}: judge-роль требует metrics{{false_green,recall,precision,specificity,schema_valid_rate}} — нет {_need}"); continue
            counts = q.get("sample_counts")
            if q["status"] in ("qualified", "conditional"):
                if not isinstance(q.get("confusion_matrix"), dict) or not isinstance(counts, dict):
                    e.append(f"{mid}/{role}: judge {q['status']} требует confusion_matrix + sample_counts{{positive,negative}}"); continue
                for _h in ("corpus_version", "corpus_hash", "prompt_hash", "policy_hash"):
                    if not q.get(_h):
                        e.append(f"{mid}/{role}: judge {q['status']} требует {_h} (held-out провенанс, без подгонки)")
            derived = derive_judge_status(m, counts)
            if q["status"] != derived:
                e.append(f"{mid}/{role}: заявлен status='{q['status']}', judge-метрики дают '{derived}' "
                         f"(судья не из held-out Bench по порогу — safety/полезность нарушены)")
            e += economics_errors(q.get("economics"), f"{mid}/{role}")
            continue
        # writer-роль: прежняя логика (success_rate)
        if "false_green" not in m or "success_rate" not in m:
            e.append(f"{mid}/{role}: metrics обязаны нести хотя бы false_green + success_rate")
            continue
        derived = derive_status(m)
        if q["status"] != derived:
            e.append(f"{mid}/{role}: заявлен status='{q['status']}', но метрики дают '{derived}' "
                     f"(допуск не из Bench — safety нарушен)")
        e += economics_errors(q.get("economics"), f"{mid}/{role}")
    return e


def economics_errors(ec, tag):
    """v3.7.10: экономика РАЗДЕЛЯЕТ измеренные токены и ДЕКЛАРИРУЕМЫЕ цены. Деньги (total_cost) —
    только когда есть обе цены, и обязаны быть согласованы с токенами×цена. Без цены total_cost=null
    (нельзя посчитать деньги без тарифа — роутер по этой роли откатится на tokens)."""
    if ec is None:
        return []  # экономика необязательна (но у измеренных implementation-записей есть)
    e = []
    if not isinstance(ec, dict):
        return [f"{tag}: economics не объект"]
    for k in ("input_tokens_per_change", "output_tokens_per_change", "tokens_per_verified_change"):
        v = ec.get(k)
        if v is not None and not (isinstance(v, int) and v > 0):
            e.append(f"{tag}: economics.{k} должен быть положительным целым (токены измеряются)")
    ip, op = ec.get("input_price_per_mtok"), ec.get("output_price_per_mtok")
    tc = ec.get("total_cost_per_verified_change")
    priced = ip is not None and op is not None
    if priced:
        if not (isinstance(ip, (int, float)) and isinstance(op, (int, float)) and ip >= 0 and op >= 0):
            e.append(f"{tag}: цены должны быть неотрицательными числами")
        for k in ("currency", "price_snapshot_at", "price_source"):
            if not (isinstance(ec.get(k), str) and ec[k].strip()):
                e.append(f"{tag}: при заданных ценах обязателен economics.{k} (провенанс тарифа)")
        it, ot = ec.get("input_tokens_per_change"), ec.get("output_tokens_per_change")
        if isinstance(it, int) and isinstance(ot, int) and isinstance(ip, (int, float)) and isinstance(op, (int, float)):
            expect = it / 1e6 * ip + ot / 1e6 * op
            if not (isinstance(tc, (int, float)) and abs(tc - expect) <= max(0.001, expect * 0.02)):
                e.append(f"{tag}: total_cost_per_verified_change={tc} != токены×цена≈{expect:.4f} "
                         f"(деньги не сходятся с измерением)")
    else:
        # без полной пары цен деньги посчитать нельзя -> total_cost обязан быть null (не выдумываем)
        if tc is not None:
            e.append(f"{tag}: цены не заданы, но total_cost_per_verified_change={tc} — деньги без тарифа "
                     f"(должно быть null; роутер откатится на tokens)")
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
    # v3.8.3 JUDGE-derivation: safety + полезность (не только false_green)
    _full = {"false_green": 0, "recall": 1.0, "precision": 0.93, "specificity": 0.92, "schema_valid_rate": 0.97}
    expect("judge: полный held-out порог -> qualified",
           derive_judge_status(_full, {"positive": 52, "negative": 28}) == "qualified")
    expect("judge: пропустил дефект (fg>0) -> not_qualified (safety)",
           derive_judge_status({**_full, "false_green": 1}, {"positive": 52, "negative": 28}) == "not_qualified")
    expect("judge: fg=0 но specificity низкая (qwen-переблок) -> conditional, НЕ qualified",
           derive_judge_status({**_full, "specificity": 0.125}, {"positive": 52, "negative": 28}) == "conditional")
    expect("judge: fg=0 но корпус мал (21<52) -> conditional (сигнал, не production)",
           derive_judge_status(_full, {"positive": 13, "negative": 8}) == "conditional")
    # check(): judge qualified без confusion_matrix/hashes -> ошибка
    _bad_judge = {"registry_type": "model-qualification", "qualifications": [
        {"model_id": "deepseek-v4-flash", "revision": "r", "provider": "deepseek", "role": "security_review",
         "corpus_version": "c", "status": "qualified",
         "metrics": {"false_green": 0, "recall": 1.0, "precision": 0.93, "specificity": 0.92, "schema_valid_rate": 0.97}}]}
    _err = check(_bad_judge, pkg=PKG)
    expect("check: judge qualified без confusion_matrix/hashes -> ошибка",
           any("confusion_matrix" in x or "prompt_hash" in x for x in _err))

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

    # v3.7.10 economics: деньги согласованы с токенами×цена; цены требуют провенанс; без цены total_cost=null
    good_ec = {"input_tokens_per_change": 100000, "output_tokens_per_change": 20000,
               "tokens_per_verified_change": 120000, "input_price_per_mtok": 2.0, "output_price_per_mtok": 8.0,
               "currency": "USD", "price_snapshot_at": "2026-07-28", "price_source": "http://x",
               "total_cost_per_verified_change": 0.36}  # 0.1*2 + 0.02*8 = 0.36
    expect("economics согласована (деньги=токены×цена) -> ok", economics_errors(good_ec, "t") == [])
    expect("total_cost != токены×цена -> ошибка",
           any("не сходятся" in x for x in economics_errors({**good_ec, "total_cost_per_verified_change": 9.9}, "t")))
    expect("цена без snapshot/source -> ошибка",
           any("провенанс" in x for x in economics_errors({**good_ec, "price_snapshot_at": None}, "t")))
    expect("цена null, но total_cost задан -> ошибка (деньги без тарифа)",
           any("деньги без тарифа" in x for x in economics_errors(
               {"input_tokens_per_change": 1, "output_tokens_per_change": 1, "tokens_per_verified_change": 2,
                "input_price_per_mtok": None, "output_price_per_mtok": None, "total_cost_per_verified_change": 0.5}, "t")))
    expect("цена null + total_cost null -> ok (tokens-fallback честно)",
           economics_errors({"input_tokens_per_change": 100, "output_tokens_per_change": 100,
                             "tokens_per_verified_change": 200, "input_price_per_mtok": None,
                             "output_price_per_mtok": None, "total_cost_per_verified_change": None,
                             "verification_required": True}, "t") == [])

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
