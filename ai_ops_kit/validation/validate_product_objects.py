#!/usr/bin/env python3
"""Четыре управляющих объекта продукта: проверка СУЩЕСТВА, а не наличия разделов (2026-08-14).

ПОВОД. Кит уже умеет потребовать Problem Statement, JTBD, гипотезы и требования — и в этом же его
слабость: он проверяет, что раздел ЗАПОЛНЕН. Ровно из этой разницы вырос B2-14: `spec-coverage`
сообщал `acceptance_criteria: complete`, а критерий не был выполнен, потому что `complete` там
означает «раздел заполнен», а не «требование выполнено». Продуктовый слой рискует повторить это в
большем масштабе: хорошо оформленный, но слабый продуктовый пакет.

ЧЕТЫРЕ ОБЪЕКТА ВМЕСТО НОВЫХ ДОКУМЕНТОВ (решение владельца `ep-2026-08-14-product-os`). Существующие
шаблоны (`templates/discovery/*`, `templates/product/*`, `templates/analytics/*`) остаются входом и
никуда не деваются — они сворачиваются в четыре машиночитаемых объекта, у которых есть контракт:

  OpportunityBrief      — какую проблему решаем, чем это подтверждено и чего мы НЕ знаем;
  ProductDecisionRecord — какие варианты рассматривали, что выбрано, чего сознательно НЕ делаем;
  OutcomeContract       — baseline, target, guardrails и правило решения ДО работы;
  OutcomeReadout        — что произошло на самом деле и какое знание вернулось в discovery.

ЧТО ИМЕННО ПРОВЕРЯЕТСЯ (и почему именно это):
  * утверждение о продукте обязано НАЗЫВАТЬ основание. Нет доказательства — это законно, но тогда
    обязан быть назван ПРОБЕЛ (`evidence_gap`). «Не знаю» и «не сказал» — разные состояния, и
    первое полезно, второе опасно;
  * решение с ОДНИМ вариантом — не решение, а оформление уже принятого. Требуется ≥2 варианта с
    плюсами и минусами, названный выбор владельца и `not_doing`;
  * `revisit_when` обязателен: решение без условия пересмотра нельзя ни подтвердить, ни отменить;
  * baseline без даты и источника — не baseline, а число из головы;
  * readout без контракта — рассказ без базы сравнения, поэтому связь обязательна, а guardrails
    контракта обязаны быть отчитаны все до одного (`cross_check`).

Использование:  validate_product_objects.py <файл.yaml> [--against contract.yaml] [--json]
Возврат 0 — валиден, 1 — ошибки.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

KINDS = ("OpportunityBrief", "ProductDecisionRecord", "OutcomeContract", "OutcomeReadout")
CONFIDENCE = ("low", "medium", "high")
HYPOTHESIS = ("confirmed", "refuted", "inconclusive")
TARGET_MET = ("yes", "no", "unknown")


def _text(v) -> str:
    return str(v or "").strip()


def _need(data, keys, errors, where):
    for k in keys:
        if not _text(data.get(k)):
            errors.append(f"{where}: нет {k}")


def _check_brief(d, e):
    w = "OpportunityBrief"
    _need(d, ("user", "situation", "problem", "desired_outcome", "why_now"), e, w)
    ev = d.get("evidence")
    if ev is None:
        e.append(f"{w}: нет evidence — даже пустой список объявляется явно, вместе с `evidence_gap`")
    elif not isinstance(ev, list):
        e.append(f"{w}: evidence должен быть списком")
    else:
        for i, item in enumerate(ev, 1):
            if not isinstance(item, dict) or not _text(item.get("claim")):
                e.append(f"{w}: evidence[{i}] без claim"); continue
            if not _text(item.get("source")):
                e.append(f"{w}: evidence[{i}] «{_text(item['claim'])[:40]}…» без source — "
                         f"утверждение о продукте обязано называть основание")
        if not ev and not _text(d.get("evidence_gap")):
            e.append(f"{w}: доказательств нет и `evidence_gap` не назван — «не знаю» и «не сказал» "
                     f"это разные состояния, и второе опаснее")
    for k in ("unknowns", "assumptions"):
        if not isinstance(d.get(k), list):
            e.append(f"{w}: {k} должен быть списком (пустой — законно, отсутствующий — нет)")


def _check_decision(d, e):
    w = "ProductDecisionRecord"
    _need(d, ("question", "opportunity", "owner_decision", "not_doing", "revisit_when"), e, w)
    if d.get("confidence") not in CONFIDENCE:
        e.append(f"{w}: confidence '{d.get('confidence')}' не в {list(CONFIDENCE)}")
    opts = d.get("options")
    if not isinstance(opts, list) or len(opts) < 2:
        e.append(f"{w}: вариантов {len(opts) if isinstance(opts, list) else 0} — решение с одним "
                 f"вариантом это не решение, а оформление уже принятого")
        opts = opts if isinstance(opts, list) else []
    ids = []
    for i, o in enumerate(opts, 1):
        if not isinstance(o, dict) or not _text(o.get("id")):
            e.append(f"{w}: options[{i}] без id"); continue
        ids.append(_text(o["id"]))
        for k in ("pros", "cons"):
            if not (isinstance(o.get(k), list) and o[k]):
                e.append(f"{w}: вариант '{o['id']}' без {k} — вариант без минусов не рассматривали, "
                         f"а описывали")
    for k in ("recommendation", "owner_decision"):
        v = _text(d.get(k))
        if v and ids and v not in ids and v != "deferred":
            e.append(f"{w}: {k} '{v}' не соответствует ни одному варианту ({', '.join(ids)})")
    if _text(d.get("owner_decision")) == "deferred" and not _text(d.get("deferred_reason")):
        e.append(f"{w}: решение отложено без причины — отложенное решение тоже решение и требует "
                 f"названного основания")


def _check_contract(d, e):
    w = "OutcomeContract"
    _need(d, ("decision", "evaluation_period"), e, w)
    pm = d.get("primary_metric")
    if not isinstance(pm, dict) or not _text(pm.get("name")) or not _text(pm.get("source")):
        e.append(f"{w}: primary_metric требует name и source — метрика без источника не считается")
    base = d.get("baseline")
    if not isinstance(base, dict):
        e.append(f"{w}: нет baseline")
    else:
        for k in ("value", "measured_at", "source"):
            if base.get(k) in (None, ""):
                e.append(f"{w}: baseline без {k} — база без даты и источника это число из головы")
    tgt = d.get("target")
    if not isinstance(tgt, dict) or tgt.get("value") in (None, "") or not _text(tgt.get("by")):
        e.append(f"{w}: target требует value и by (к какому сроку)")
    gr = d.get("guardrails")
    if not isinstance(gr, list) or not gr:
        e.append(f"{w}: нет guardrails — без них «цель достигнута» может означать «сломали соседнее»")
    else:
        for i, g in enumerate(gr, 1):
            if not isinstance(g, dict) or not _text(g.get("name")):
                e.append(f"{w}: guardrails[{i}] без name"); continue
            if not any(_text(g.get(k)) for k in ("must_not_exceed", "must_not_drop_below")):
                e.append(f"{w}: guardrail '{g['name']}' без порога — что именно нельзя ухудшить?")
    if not (isinstance(d.get("events"), list) and d["events"]):
        e.append(f"{w}: нет events — нечем мерить: метрика объявлена, а сигнала нет")
    rules = d.get("decision_rules")
    if not isinstance(rules, dict) or not all(_text(rules.get(k)) for k in ("continue", "change", "stop")):
        e.append(f"{w}: decision_rules требует continue/change/stop — правило решения принимается ДО "
                 f"работы, иначе результат всегда толкуется в пользу сделанного")


def _check_readout(d, e):
    w = "OutcomeReadout"
    _need(d, ("contract", "next_decision", "back_to_discovery"), e, w)
    if d.get("target_met") not in TARGET_MET:
        e.append(f"{w}: target_met '{d.get('target_met')}' не в {list(TARGET_MET)}")
    elif d.get("target_met") == "unknown" and not _text(d.get("unknown_reason")):
        e.append(f"{w}: target_met=unknown без причины — неизмеренное обязано называть, почему")
    if d.get("hypothesis") not in HYPOTHESIS:
        e.append(f"{w}: hypothesis '{d.get('hypothesis')}' не в {list(HYPOTHESIS)}")
    m = d.get("measured")
    if not isinstance(m, dict) or m.get("value") in (None, "") or not _text(m.get("measured_at")):
        e.append(f"{w}: measured требует value и measured_at")
    for k in ("guardrails_observed", "unexpected_effects"):
        if not isinstance(d.get(k), list):
            e.append(f"{w}: {k} должен быть списком (пустой — законно, отсутствующий — нет)")


_CHECKERS = {"OpportunityBrief": _check_brief, "ProductDecisionRecord": _check_decision,
             "OutcomeContract": _check_contract, "OutcomeReadout": _check_readout}


def check(data: dict) -> list:
    """Ошибки объекта. Вид определяется полем `kind`; чужой артефакт отвергается."""
    if not isinstance(data, dict):
        return ["артефакт не является объектом"]
    errors = []
    if data.get("schema_version") is None:
        errors.append("нет schema_version")
    kind = data.get("kind")
    if kind not in KINDS:
        return errors + [f"kind '{kind}' не в {list(KINDS)}"]
    _CHECKERS[kind](data, errors)
    return errors


def cross_check(contract: dict, readout: dict) -> list:
    """Сверка readout с его контрактом. Отчёт обязан закрыть ВСЁ, что контракт объявил заранее.

    Без этой сверки readout честно заполняется по удобным метрикам: отчитались по цели, промолчали
    про guardrail, который просел. Тот же класс, что «раздел заполнен» вместо «критерий выполнен».
    """
    errors = []
    cname = _text((contract.get("primary_metric") or {}).get("name"))
    rname = _text((readout.get("measured") or {}).get("metric") or cname)
    if cname and rname and cname != rname:
        errors.append(f"readout измеряет '{rname}', а контракт объявлял '{cname}' — подмена метрики")
    declared = {_text(g.get("name")) for g in (contract.get("guardrails") or [])
                if isinstance(g, dict) and _text(g.get("name"))}
    reported = {_text(g.get("name")) for g in (readout.get("guardrails_observed") or [])
                if isinstance(g, dict) and _text(g.get("name"))}
    missing = sorted(declared - reported)
    if missing:
        errors.append(f"guardrails не отчитаны: {', '.join(missing)} — умолчание о том, что было "
                      f"объявлено заранее, читается как «всё в порядке»")
    return errors


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 1
    data = yaml.safe_load(Path(args[0]).read_text(encoding="utf-8")) or {}
    errors = check(data)
    against = next((a.split("=", 1)[1] for a in argv if a.startswith("--against=")), None)
    if against:
        other = yaml.safe_load(Path(against).read_text(encoding="utf-8")) or {}
        pair = ((other, data) if data.get("kind") == "OutcomeReadout" else (data, other))
        errors += cross_check(*pair)
    if "--json" in argv:
        print(json.dumps({"errors": errors}, ensure_ascii=False, indent=2))
    elif errors:
        print("PRODUCT-OBJECT: ошибки:")
        for e in errors:
            print(f"  - {e}")
    else:
        print(f"PRODUCT-OBJECT-OK: {data.get('kind')} валиден.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
