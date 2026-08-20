#!/usr/bin/env python3
"""Gate evaluation corpus — устойчивость СУДЕЙСКОГО вердикта под регрессией (C1, v3.37).

ПОВОД — ЗАМЕР, А НЕ ОПАСЕНИЕ. Из 35 гейтов `quality/gates.yaml` **19 не имеют исполняемого
валидатора** (`closed_by: judge|writer`): их «зелёное» — не результат машины, а мнение. У агентов
контракт роли закреплён 52 eval-кейсами (`evaluations/agents/`), у гейтов не было ни одного. То
есть регрессия вердикта не измерялась ничем: тот же диф, поданный дважды, мог дать разные ответы,
и кит бы этого не заметил.

ЧТО ИМЕННО МЕРИТ ЭТОТ КОРПУС — и что НЕ мерит. Между дифом и «зелёным» стоят два звена, и они
ломаются по-разному:

  1. СУДЬЯ: модель читает диф и выдаёт заключение. Нестабильна по своей природе; замерить можно
     только живым прогоном — режим `live`, N повторов на кейс, согласие вердиктов как число.
  2. ПРОИЗВОДНАЯ ЦЕПОЧКА: заключение судьи -> evidence -> `evaluate_gate` -> статус гейта. Она
     ДЕТЕРМИНИРОВАНА и потому воспроизводима без модели — режим `replay`. Здесь живёт свой класс
     «тот же ответ -> другой вердикт»: разбор JSON-блока, регэкспы вердикта в прозе, дисциплина
     `required_evidence`. Регрессия в этом звене молча меняет смысл «зелёного» на КАЖДОМ гейте.

`replay` гоняется офлайн на каждом PR (`tests/contracts/test_gate_eval_corpus.py`). `live` требует
модели и НЕ входит в PR-контур: это ручной запуск `python3 -m ai_ops_kit.devtools.gate_eval_live`.
Называется это честно и в отчёте, и здесь: **корпус доказывает воспроизводимость производной
цепочки, а не то, что судья стабилен.** Стабильность судьи — число, замеренное в `live` и
записанное в кейс; оно стареет ровно как всякий замер.

ТРЕТЬЕ СОСТОЯНИЕ НЕ СВОРАЧИВАЕТСЯ ВО ВТОРОЕ. Кейс без записанного ответа судьи — `unavailable`
(«устойчивость не измерена»), а не `ok`. В сводке он считается отдельной строкой; выдать корпус за
«зелёный», когда часть кейсов не прогонялась, нельзя ни одним кодом возврата.

ПОЧЕМУ В `devtools`, А НЕ В `gates`. Корпус мерит судью КИТА на коммитах КИТА — это инструмент
разработки самого кита, как `mutation_probe` и харнессы квалификации рядом. Пакет `devtools`
объявлен dev-only в поставке (`installer/ai_ops.py -> DEV_ONLY_PREFIXES`), и решило это не
удобство, а ЗАМЕР: пока оба прогонщика лежали в `gates/` и `providers/`, они уезжали в каждый
child-репозиторий и пробили потолок объёма поставки — на базе оставалось 12,6 КиБ запаса при
потолке 3.7 МБ, а прогонщики весят 38 КиБ. Поднять потолок было бы неправдой по правилу,
записанному в самом установщике: он поднимается, когда в дочку едет то, что дочке НУЖНО. Данные
корпуса (`evaluations/`) и стенограммы (`qualification/`) в поставку не входили и так.
Продуктовый код от `devtools` не зависит и зависеть не вправе (`validate_layering`, правило
`no-product-depends-on-devtools`); зависимость идёт только вниз — в `gates`.

Формат кейса — `evaluations/gates/GateEvaluationCase.md`, кейсы — `evaluations/gates/cases/*.yaml`.

Использование:
  python3 -m ai_ops_kit.devtools.gate_evals            — прогон корпуса (replay)
  python3 -m ai_ops_kit.devtools.gate_evals --json     — то же машиночитаемо
  python3 -m ai_ops_kit.devtools.gate_evals --case ID  — один кейс

Возврат: 0 — расхождений нет; 1 — вердикт поплыл или корпус битый (кейсы названы поимённо).
Требует pyyaml.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from ai_ops_kit.gates.gate_executor import (
    evidence_from_judge_output,
    evaluate_gate,
    load_gates,
)

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
           Path(__file__).resolve().parents[2])
CASES_DIR = PKG / "evaluations" / "gates" / "cases"
# Стенограммы живых ответов судьи — УЛИКИ ПРОГОНА, а не описание кейса, и лежат там же, где
# остальные улики (`qualification/evidence/`). Причина в читаемости: 85 КБ судейской прозы внутри
# YAML превращают кейс в блоб, который человек не открывает, — то есть корпус перестаёт быть
# набором СЛУЧАЕВ и становится дампом. В поставку ни то, ни другое не входит.
TRANSCRIPTS_DIR = PKG / "qualification" / "evidence" / "gate-evals"

_STATUSES = ("pass", "warn", "fail")
_PROVENANCE = ("verbatim_run_report", "verbatim_commit", "class_repro", "contract_invariant")
# Кейс либо описывает отсутствие судьи (fail-closed), либо несёт его ответы. Третьего вида нет:
# «кейс с судьёй, но без ответов» — это незаполненный кейс, и он обязан быть виден как unavailable.
_KINDS = ("no_judge", "judge_output")


# ---------------------------------------------------------------- загрузка и форма

def case_form_errors(case, where: str) -> list:
    """Ошибки формы одного кейса. Пустой список = форма валидна.

    Форму проверяем ЗДЕСЬ, а не «оно же yaml»: корпус — это утверждение о том, каким обязан быть
    вердикт. Кейс с опечаткой в `expected.status` молча перестал бы что-либо утверждать, то есть
    стал бы ровно тем «зелёным без содержания», против которого корпус и заведён."""
    e = []
    if not isinstance(case, dict):
        return [f"{where}: верхний уровень должен быть mapping"]
    if case.get("kind") != "gate-evaluation-case":
        e.append(f"{where}: kind должен быть 'gate-evaluation-case'")
    if case.get("schema_version") != 1:
        e.append(f"{where}: schema_version должен быть 1")
    if not isinstance(case.get("id"), str) or not case["id"]:
        e.append(f"{where}: нужен непустой id")
    if not isinstance(case.get("gate"), str) or not case["gate"]:
        e.append(f"{where}: нужен gate (id из quality/gates.yaml)")
    if case.get("case_kind") not in _KINDS:
        e.append(f"{where}: case_kind должен быть одним из {list(_KINDS)}")
    if not isinstance(case.get("summary"), str) or not case["summary"].strip():
        e.append(f"{where}: нужен summary одной строкой")

    origin = case.get("origin")
    if not isinstance(origin, dict):
        e.append(f"{where}: нужен origin {{source, provenance}}")
    else:
        if not isinstance(origin.get("source"), str) or not origin["source"].strip():
            e.append(f"{where}.origin: нужен source — откуда взят кейс")
        if origin.get("provenance") not in _PROVENANCE:
            e.append(f"{where}.origin.provenance должен быть одним из {list(_PROVENANCE)}")

    exp = case.get("expected")
    if not isinstance(exp, dict):
        e.append(f"{where}: нужен expected {{status, ...}}")
    else:
        if exp.get("status") not in _STATUSES:
            e.append(f"{where}.expected.status: '{exp.get('status')}' вне {list(_STATUSES)}")
        bm = exp.get("reason_matches", [])
        if not isinstance(bm, list) or not all(isinstance(x, str) for x in bm):
            e.append(f"{where}.expected.reason_matches: список строк")
        if exp.get("status") == "fail" and not bm:
            e.append(f"{where}.expected: fail без reason_matches — «красное» без причины "
                     f"не отличимо от красного по другому поводу")
        if exp.get("status") == "pass" and case.get("case_kind") == "no_judge" and not bm:
            e.append(f"{where}.expected: pass без судьи и без reason_matches — «зелёное» без "
                     f"названного основания есть ровно то, против чего заведён корпус")

    sig = case.get("signals", {})
    if not isinstance(sig, dict):
        e.append(f"{where}.signals: mapping сигнал->bool")

    if case.get("case_kind") == "judge_output":
        rec = case.get("recorded")
        if rec is None:
            rec = []
        if not isinstance(rec, list):
            e.append(f"{where}.recorded: список записанных ответов судьи")
        else:
            for i, r in enumerate(rec):
                w = f"{where}.recorded[{i}]"
                if not isinstance(r, dict):
                    e.append(f"{w}: mapping"); continue
                if not (isinstance(r.get("transcript"), str) and r["transcript"].strip()):
                    e.append(f"{w}.transcript: имя файла стенограммы в "
                             f"qualification/evidence/gate-evals/")
                if r.get("derived_status") not in _STATUSES:
                    e.append(f"{w}.derived_status: '{r.get('derived_status')}' вне {list(_STATUSES)} "
                             f"— это ЗАМОРОЖЕННЫЙ вердикт цепочки на момент записи")
                for k in ("recorded_at", "provider"):
                    if not isinstance(r.get(k), str) or not r[k].strip():
                        e.append(f"{w}.{k}: нужен — иначе замер не привязан ни ко времени, "
                                 f"ни к исполнителю")
        inp = case.get("input")
        if not isinstance(inp, dict) or not isinstance(inp.get("task"), str) or not inp["task"].strip():
            e.append(f"{where}.input.task: нужен текст задачи для судьи (режим live)")
        elif not (isinstance(inp.get("diff_file"), str) and inp["diff_file"].strip()):
            # Диф лежит СОСЕДНИМ .patch-файлом, а не строкой в YAML. Причина механическая и
            # существенная: в unified diff пустая строка контекста — это строка из одного пробела,
            # и PyYAML на таком тексте отказывается от блочного скаляра. Кейс с дифом внутри
            # превращался в экранированную кашу, которую человек не читает — то есть перестал бы
            # быть закреплённым СЛУЧАЕМ и стал бы блобом.
            e.append(f"{where}.input.diff_file: нужен файл дифа рядом с кейсом (режим live)")
    return e


def load_cases(cases_dir=None, transcripts_dir=None):
    """(cases, errors). Ошибка формы КЕЙСА — это ошибка корпуса, а не пропуск кейса."""
    d = Path(cases_dir or CASES_DIR)
    cases, errors, seen = [], [], {}
    if not d.is_dir():
        return [], [f"каталог кейсов не найден: {d}"]
    for p in sorted(d.glob("*.yaml")):
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            errors.append(f"{p.name}: не разобран YAML — {exc}")
            continue
        errs = case_form_errors(data, p.name)
        if errs:
            errors.extend(errs)
            continue
        df = ((data.get("input") or {}).get("diff_file")) if data.get("case_kind") == "judge_output" else None
        if df:
            dp = d / df
            if not dp.is_file():
                errors.append(f"{p.name}: файла дифа '{df}' нет рядом с кейсом")
                continue
            data["input"]["diff"] = dp.read_text(encoding="utf-8")
        # Стенограммы подтягиваются из каталога улик. Отсутствие файла — НЕ ошибка корпуса:
        # в поставке дочки улик нет по построению, и кейс обязан честно стать «не измерено»,
        # а не уронить прогон и не притвориться пройденным.
        missing = []
        for r in (data.get("recorded") or []):
            tp = Path(transcripts_dir or TRANSCRIPTS_DIR) / r["transcript"]
            if tp.is_file():
                r["text"] = tp.read_text(encoding="utf-8")
            else:
                missing.append(r["transcript"])
        if missing:
            data["recorded"] = [r for r in data["recorded"] if r.get("text")]
            data["_missing_transcripts"] = missing
        cid = data["id"]
        if cid in seen:
            errors.append(f"{p.name}: id '{cid}' уже занят кейсом {seen[cid]}")
            continue
        seen[cid] = p.name
        data["_file"] = p.name
        cases.append(data)
    return cases, errors


def corpus_registry_errors(cases, gates=None) -> list:
    """Кейс ссылается на существующий гейт, и гейт этот закрывается НЕ валидатором.

    Второе — не формальность. Корпус заведён под 19 гейтов, чьё «зелёное» — мнение; кейс на
    валидаторный гейт мерил бы машину, которая и так измеряется своим прогоном, и раздувал бы
    охват на бумаге."""
    gates = gates if gates is not None else load_gates()
    errs = []
    for c in cases:
        g = gates.get(c["gate"])
        if g is None:
            errs.append(f"{c['id']}: гейта '{c['gate']}' нет в quality/gates.yaml")
            continue
        if g.get("closed_by") == "validator" and not c.get("validator_control"):
            errs.append(f"{c['id']}: гейт '{c['gate']}' закрывается валидатором — "
                        f"для контрольного кейса объявите validator_control: true")
    return errs


# ---------------------------------------------------------------- производная цепочка

def derive_verdict(case, judge_text, gates=None) -> dict:
    """Ответ судьи (или его отсутствие) -> gate-result ТОЙ ЖЕ цепочкой, что в бою.

    Никакой своей логики решения здесь нет намеренно: `evidence_from_judge_output` и
    `evaluate_gate` — это ровно то, что исполняется в прогоне. Корпус, считающий вердикт
    по-своему, мерил бы себя."""
    gates = gates if gates is not None else load_gates()
    gate = gates[case["gate"]]
    evidence = {}
    if judge_text is not None:
        ev = evidence_from_judge_output(gate, judge_text, source=f"gate-eval:{case['id']}")
        if ev is not None:
            evidence[case["gate"]] = ev
    return evaluate_gate(case["gate"], gate, evidence,
                         tested_revision=case.get("tested_revision"),
                         signals=case.get("signals") or {})


def _reasons_missing(result, patterns) -> list:
    """Какие из ожидаемых причин НЕ нашлись среди blockers/warnings (подстрока, регистр не важен).

    Смотрим и туда, и туда намеренно: у блокирующего гейта причина ложится в `blockers`, у
    advisory — в `warnings`, и кейс не должен знать, каким гейт объявлен сегодня."""
    hay = " | ".join(list(result.get("blockers") or []) + list(result.get("warnings") or [])).lower()
    return [p for p in patterns if p.lower() not in hay]


# ---------------------------------------------------------------- прогон корпуса

def replay_case(case, gates=None) -> dict:
    """Один кейс в режиме replay. Ключи: outcome ∈ ok|drift|unavailable."""
    gates = gates if gates is not None else load_gates()
    exp = case["expected"]
    out = {"case": case["id"], "gate": case["gate"], "case_kind": case["case_kind"],
           "expected": exp["status"], "runs": [], "outcome": "ok", "detail": []}

    if case["case_kind"] == "no_judge":
        r = derive_verdict(case, None, gates)
        out["runs"].append({"source": "no-judge", "status": r["status"]})
        if r["status"] != exp["status"]:
            out["outcome"] = "drift"
            out["detail"].append(f"вердикт без судьи: {r['status']} != ожидаемого {exp['status']}")
        missing = _reasons_missing(r, exp.get("reason_matches", []))
        if missing:
            out["outcome"] = "drift"
            out["detail"].append(f"причина не названа: не нашлось {missing} "
                                 f"в blockers/warnings {r.get('blockers')} / {r.get('warnings')}")
        return out

    recorded = case.get("recorded") or []
    if not recorded:
        out["outcome"] = "unavailable"
        miss = case.get("_missing_transcripts")
        out["detail"].append(
            f"стенограмм нет на месте ({', '.join(miss)}) — устойчивость вердикта НЕ измерена"
            if miss else
            "ответов судьи не записано — устойчивость вердикта НЕ измерена (это не «в порядке»)")
        return out
    if case.get("_missing_transcripts"):
        out["detail"].append("часть стенограмм не найдена: "
                             + ", ".join(case["_missing_transcripts"]))

    statuses = []
    for i, r in enumerate(recorded):
        res = derive_verdict(case, r["text"], gates)
        statuses.append(res["status"])
        out["runs"].append({"source": f"recorded[{i}] {r.get('recorded_at')} {r.get('provider')}",
                            "status": res["status"], "frozen": r["derived_status"]})
        if res["status"] != r["derived_status"]:
            out["outcome"] = "drift"
            out["detail"].append(
                f"recorded[{i}]: цепочка теперь даёт '{res['status']}', заморожено "
                f"'{r['derived_status']}' — при неизменном ответе судьи изменился РАЗБОР")
        if res["status"] != exp["status"]:
            out["outcome"] = "drift"
            out["detail"].append(
                f"recorded[{i}]: вердикт '{res['status']}' != ожидаемого '{exp['status']}'")
        else:
            missing = _reasons_missing(res, exp.get("reason_matches", []))
            if missing:
                out["outcome"] = "drift"
                out["detail"].append(f"recorded[{i}]: причина не названа — не нашлось {missing}")

    out["agreement"] = f"{statuses.count(max(set(statuses), key=statuses.count))}/{len(statuses)}"
    frozen_agreement = (case.get("stability") or {}).get("agreement")
    if frozen_agreement and out["agreement"] != frozen_agreement:
        out["outcome"] = "drift"
        out["detail"].append(f"согласие вердиктов {out['agreement']} != замеренного "
                             f"{frozen_agreement}")
    return out


def run_corpus(cases=None, gates=None, cases_dir=None, transcripts_dir=None) -> dict:
    """Прогон корпуса в режиме replay -> машиночитаемый отчёт."""
    gates = gates if gates is not None else load_gates()
    errors = []
    if cases is None:
        cases, errors = load_cases(cases_dir, transcripts_dir)
    errors = list(errors) + corpus_registry_errors(cases, gates)
    results = [replay_case(c, gates) for c in cases]
    counts = {k: sum(1 for r in results if r["outcome"] == k) for k in ("ok", "drift", "unavailable")}
    judged = sorted({r["gate"] for r in results
                     if (gates.get(r["gate"]) or {}).get("closed_by") in ("judge", "writer")})
    all_judged = sorted(g for g, v in gates.items() if v.get("closed_by") in ("judge", "writer"))
    return {
        "schema_version": 1, "kind": "gate-eval-report", "mode": "replay",
        "cases": len(results), "counts": counts, "errors": errors, "results": results,
        # Охват называется числом, а не словом «покрыто»: 19 гейтов без валидатора — знаменатель,
        # который не даёт корпусу выглядеть полным, пока он неполон.
        "coverage": {"judged_gates_total": len(all_judged),
                     "judged_gates_with_cases": len(judged),
                     "gates_with_cases": judged,
                     "gates_without_cases": [g for g in all_judged if g not in judged]},
        "clean": not errors and counts["drift"] == 0,
    }


def format_report(rep) -> str:
    L = []
    cov = rep["coverage"]
    L.append(f"GATE-EVAL [{rep['mode']}] кейсов: {rep['cases']} · "
             f"совпало {rep['counts']['ok']} · поплыло {rep['counts']['drift']} · "
             f"не измерено {rep['counts']['unavailable']}")
    L.append(f"  охват: {cov['judged_gates_with_cases']} из {cov['judged_gates_total']} гейтов, "
             f"чьё «зелёное» — мнение (без исполняемого валидатора)")
    for r in rep["results"]:
        mark = {"ok": "  ok  ", "drift": " ПЛЫВЁТ", "unavailable": " НЕ ИЗМЕРЕНО"}[r["outcome"]]
        agree = f" согласие {r['agreement']}" if r.get("agreement") else ""
        L.append(f"{mark} {r['case']} [{r['gate']}] ожидалось {r['expected']}{agree}")
        for d in r["detail"]:
            L.append(f"          {d}")
    for e in rep["errors"]:
        L.append(f"  ОШИБКА КОРПУСА: {e}")
    if rep["counts"]["unavailable"]:
        L.append("  «не измерено» — это НЕ «в порядке»: у кейса нет ни одного записанного ответа "
                 "судьи. Записать: python3 -m ai_ops_kit.devtools.gate_eval_live --record")
    L.append("  replay доказывает воспроизводимость РАЗБОРА вердикта без модели; устойчивость "
             "самого судьи меряет только live-прогон.")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Прогон корпуса gate-евалов (replay, без модели)")
    ap.add_argument("--json", action="store_true", help="машиночитаемый отчёт")
    ap.add_argument("--case", help="прогнать один кейс по id")
    ap.add_argument("--cases-dir", help="каталог кейсов (по умолчанию evaluations/gates/cases)")
    args = ap.parse_args(argv)

    cases, errors = load_cases(args.cases_dir)
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
        if not cases:
            print(f"кейса '{args.case}' нет в корпусе", file=sys.stderr)
            return 1
    rep = run_corpus(cases, cases_dir=args.cases_dir)
    rep["errors"] = list(errors) + [e for e in rep["errors"] if e not in errors]
    rep["clean"] = not rep["errors"] and rep["counts"]["drift"] == 0
    print(json.dumps(rep, ensure_ascii=False, indent=2) if args.json else format_report(rep))
    return 0 if rep["clean"] else 1


if __name__ == "__main__":
    sys.exit(main())
