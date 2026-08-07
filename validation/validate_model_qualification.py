#!/usr/bin/env python3
from __future__ import annotations
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


# v3.8.4: КАСКАДНЫЙ судья (detector→verifier→reducer, fail-closed) квалифицируется по РЕАЛЬНЫМ действиям
# (pass/fail/pending_human), а не по одному prompt. pending_human — НЕ false green (безопасно), но снижает
# автономность, поэтому coverage — часть порога: нельзя «сделать безопасным», отправляя человеку всё.
C_THRESH = {"clean_auto_pass_min": 0.90, "coverage_min": 0.90, "schema_min": 0.95, "pos_min": 52, "neg_min": 28}
_ABSTAIN_CM = ("true_positive", "false_negative", "true_negative", "false_positive",
               "positive_abstain", "negative_abstain")


def derive_cascade_status(m, counts, th=None):
    """Статус КАСКАДА из fail-closed метрик. m: {unsafe_passes|false_green, safe_handling_rate,
    clean_auto_pass_rate, auto_decision_coverage, schema_valid_rate}; counts: {positive, negative}.
    qualified — 0 unsafe-pass + полное безопасное покрытие позитивов + автономность/чистота по порогу."""
    th = th or C_THRESH
    unsafe = m.get("unsafe_passes", m.get("false_green", 1))
    if unsafe is None or unsafe > 0:
        return "not_qualified"           # хоть один unsafe pass -> НИКОГДА qualified (safety-first)
    shr = float(m.get("safe_handling_rate", 0) or 0)
    cap = float(m.get("clean_auto_pass_rate", 0) or 0)
    cov = float(m.get("auto_decision_coverage", 0) or 0)
    sv = float(m.get("schema_valid_rate", 0) or 0)
    pos = int((counts or {}).get("positive", 0) or 0); neg = int((counts or {}).get("negative", 0) or 0)
    if (shr >= 1.0 and cap >= th["clean_auto_pass_min"] and cov >= th["coverage_min"]
            and sv >= th["schema_min"] and pos >= th["pos_min"] and neg >= th["neg_min"]):
        return "qualified"
    return "conditional"                 # 0 unsafe, но не автономен/чист по порогу -> advisory/human


def cm_integrity_errors(cm, counts, m, tag):
    """Арифметическая целостность confusion matrix с abstain (fix метрик v3.8.4): нельзя «квалифицировать»
    модель, исключив abstain из знаменателя. Инварианты: TP+FN+pos_abstain=positive; TN+FP+neg_abstain=
    negative; unsafe_passes(=заявленный false_green)=FN. Проверяем ТОЛЬКО когда матрица несёт abstain-поля."""
    e = []
    if not isinstance(cm, dict) or not all(k in cm for k in _ABSTAIN_CM):
        return e  # старые (single-judge) матрицы без abstain — не трогаем (back-compat)
    if not isinstance(counts, dict):
        return [f"{tag}: confusion_matrix с abstain требует sample_counts{{positive,negative}}"]
    try:
        tp, fn, tn, fp = (int(cm[k]) for k in ("true_positive", "false_negative", "true_negative", "false_positive"))
        pa, na = int(cm["positive_abstain"]), int(cm["negative_abstain"])
        pos, neg = int(counts.get("positive", -1)), int(counts.get("negative", -1))
    except (TypeError, ValueError):
        return [f"{tag}: confusion_matrix/sample_counts должны быть целыми"]
    if tp + fn + pa != pos:
        e.append(f"{tag}: TP+FN+positive_abstain={tp + fn + pa} != positive={pos} (abstain нельзя терять из знаменателя)")
    if tn + fp + na != neg:
        e.append(f"{tag}: TN+FP+negative_abstain={tn + fp + na} != negative={neg} (abstain нельзя терять из знаменателя)")
    unsafe = (m or {}).get("unsafe_passes", (m or {}).get("false_green"))
    if unsafe is not None and int(unsafe) != fn:
        e.append(f"{tag}: unsafe_passes={unsafe} != FN={fn} (unsafe pass дефектного = false green, должны совпадать)")
    return e


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
        # v3.8.4: КАСКАДНЫЙ судья -> fail-closed метрики (pass/fail/pending_human) + abstain-целостность.
        if role in JUDGE_ROLES and q.get("judge_mode") == "cascade":
            _cneed = [k for k in ("unsafe_passes", "safe_handling_rate", "clean_auto_pass_rate",
                                  "auto_decision_coverage", "schema_valid_rate") if k not in m]
            if _cneed:
                e.append(f"{mid}/{role}: cascade-судья требует metrics{{unsafe_passes,safe_handling_rate,"
                         f"clean_auto_pass_rate,auto_decision_coverage,schema_valid_rate}} — нет {_cneed}"); continue
            counts = q.get("sample_counts")
            if q["status"] in ("qualified", "conditional"):
                if not isinstance(q.get("confusion_matrix"), dict) or not isinstance(counts, dict):
                    e.append(f"{mid}/{role}: cascade {q['status']} требует confusion_matrix(+abstain) + sample_counts"); continue
                for _h in ("corpus_version", "corpus_hash", "detector_prompt_hash", "verifier_prompt_hash", "policy_hash"):
                    if not q.get(_h):
                        e.append(f"{mid}/{role}: cascade {q['status']} требует {_h} (held-out провенанс каскада)")
            e += cm_integrity_errors(q.get("confusion_matrix"), counts, m, f"{mid}/{role}")
            derived = derive_cascade_status(m, counts)
            if q["status"] != derived:
                e.append(f"{mid}/{role}: заявлен status='{q['status']}', cascade-метрики дают '{derived}' "
                         f"(каскад не из held-out по fail-closed порогу — safety/автономность нарушены)")
            e += economics_errors(q.get("economics"), f"{mid}/{role}")
            continue
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


def main(argv):
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
