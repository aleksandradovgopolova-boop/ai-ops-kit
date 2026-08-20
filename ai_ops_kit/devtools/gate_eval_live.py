#!/usr/bin/env python3
"""Живой прогон корпуса gate-евалов — замер устойчивости СУДЬИ (C1, v3.37).

Корпус и производная цепочка живут в `ai_ops_kit/devtools/gate_evals.py` и гоняются офлайн на
каждом PR. Здесь — вторая половина замера, которая БЕЗ МОДЕЛИ невозможна: один и тот же вход
подаётся судье N раз, и согласие вердиктов записывается числом.

ПОЧЕМУ ОТДЕЛЬНОЙ ТОЧКОЙ ВХОДА, А НЕ ФЛАГОМ В КОРПУСЕ. Офлайн-прогон обязан оставаться
импортируемым БЕЗ стека провайдеров: его гоняет `tests/contracts` на каждом PR, и тянуть туда
оркестратор ради флага, который там никогда не включат, значило бы платить за живой путь в
проверке, которая живой моделью не пользуется. Разделение и по смыслу честное: корпус решает,
каким обязан быть вердикт; провайдер — кто его произносит.

ЧТО ЭТОТ ПРОГОН СТОИТ И КОГДА ОН ИДЁТ. Каждый повтор — живой вызов модели. Поэтому он НЕ входит в
PR-контур и не запускается ни одной джобой: это ручной запуск владельца или отдельная джоба,
которой сегодня нет (её добавление — правка `.github/`, вне границы этой ленты). Молчаливо
включать живую модель в каждый PR нельзя: контур, который иногда стоит денег и иногда падает по
сети, перестаёт быть проверкой и становится лотереей.

Использование:
  python3 -m ai_ops_kit.devtools.gate_eval_live --repeats 3
  python3 -m ai_ops_kit.devtools.gate_eval_live --case <id> --repeats 5 --record
  python3 -m ai_ops_kit.devtools.gate_eval_live --provider claude-cli --record

`--record` записывает ответы судьи и замеренное согласие обратно в файл кейса: после этого
офлайн-replay воспроизводит РАЗБОР этих ответов на каждом PR, уже без модели.

Возврат: 0 — все прогнанные кейсы дали ожидаемый вердикт и согласие не упало; 1 — иначе.
Требует pyyaml.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from ai_ops_kit.devtools.gate_evals import (
    CASES_DIR,
    TRANSCRIPTS_DIR,
    derive_verdict,
    load_cases,
)
from ai_ops_kit.gates.gate_executor import load_gates
from ai_ops_kit.providers.orchestrator import build_role_prompt
from ai_ops_kit.providers.orchestrator_providers import make_provider, resolve_provider

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
           Path(__file__).resolve().parents[2])


def _agents_index():
    ag = yaml.safe_load((PKG / "registry" / "agents.yaml").read_text(encoding="utf-8"))
    return {a["id"]: a for a in ag.get("agents", [])}


def _readable(text: str) -> str:
    """Снять хвостовые пробелы построчно — иначе PyYAML не даст блочный скаляр и запишет ответ
    судьи экранированной кашей. Вердикт замораживается ОТ ЭТОГО ЖЕ текста, поэтому replay остаётся
    точным: сравнивается то, что записано, с тем, что записано."""
    return "\n".join(line.rstrip() for line in (text or "").splitlines())


def judge_prompt(case, gate, agents_index) -> str:
    """Промпт судьи — ТОТ ЖЕ, что в прогоне (`orchestrator.build_role_prompt`).

    Свой промпт здесь мерил бы своего судью: guard про read-only и требование структурного
    `reviewer-result` — часть того, чем обеспечено «зелёное», и подменять их в замере нельзя."""
    stage = {"id": f"gate-eval-{case['id']}", "owner": gate.get("responsible_role"),
             "review_mode": "read-only"}
    published = {f"diff-{case['id']}.patch": case["input"]["diff"]}
    return build_role_prompt(stage, gate.get("responsible_role"), agents_index,
                             case["input"]["task"], published)


def run_case_live(case, provider_fn, repeats, gates=None, agents_index=None) -> dict:
    """N повторов одного кейса живым судьёй -> вердикты, согласие, сырые ответы."""
    gates = gates if gates is not None else load_gates()
    agents_index = agents_index if agents_index is not None else _agents_index()
    gate = gates[case["gate"]]
    prompt = judge_prompt(case, gate, agents_index)
    answers, verdicts, failures = [], [], []
    for i in range(repeats):
        try:
            text = provider_fn(prompt)
        except Exception as exc:  # noqa: BLE001 — отказ вызова НЕ равен вердикту судьи
            # Третье состояние: вызов не состоялся. Записать это как вердикт значило бы
            # объявить мнением то, чего никто не говорил.
            failures.append(f"повтор {i + 1}: вызов не состоялся — {type(exc).__name__}: {exc}")
            continue
        # нормализуем СРАЗУ: вердикт повтора и текст, который ляжет в кейс, обязаны быть одним
        # и тем же — иначе замеренное согласие относилось бы не к тому, что записано
        text = _readable(text)
        res = derive_verdict(case, text, gates)
        answers.append(text)
        verdicts.append(res["status"])
    agreement = (f"{verdicts.count(max(set(verdicts), key=verdicts.count))}/{len(verdicts)}"
                 if verdicts else "0/0")
    return {"case": case["id"], "gate": case["gate"], "expected": case["expected"]["status"],
            "verdicts": verdicts, "agreement": agreement, "answers": answers,
            "failures": failures,
            "matches_expected": bool(verdicts) and all(v == case["expected"]["status"]
                                                       for v in verdicts),
            "stable": len(set(verdicts)) <= 1 and bool(verdicts)}


# ---------------------------------------------------------------- запись в кейс

def _block_str_representer(dumper, data):
    """Многострочный текст — блочным скаляром: кейс должен оставаться читаемым человеком."""
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


class _CaseDumper(yaml.SafeDumper):
    pass


_CaseDumper.add_representer(str, _block_str_representer)

# Порядок ключей в файле кейса — фиксированный: кейсы читают глазами, и перетасовка полей при
# каждой записи превратила бы diff записи в diff всего файла.
_KEY_ORDER = ["schema_version", "kind", "id", "gate", "case_kind", "validator_control", "summary",
              "origin", "notes", "signals", "expected", "input", "stability", "recorded"]


def write_case(path: Path, case: dict):
    data = {k: case[k] for k in _KEY_ORDER if k in case}
    data.update({k: v for k, v in case.items() if k not in _KEY_ORDER and not k.startswith("_")})
    inp = data.get("input")
    if isinstance(inp, dict) and inp.get("diff_file"):
        # диф живёт соседним .patch-файлом; материализованный текст обратно в YAML не пишем
        data["input"] = {k: v for k, v in inp.items() if k != "diff"}
    path.write_text(yaml.dump(data, Dumper=_CaseDumper, allow_unicode=True, sort_keys=False,
                              width=100), encoding="utf-8")


def record_into_case(case, live, provider_name, model, cases_dir=None, gates=None,
                     transcripts_dir=None) -> Path:
    """Записать ответы судьи и замеренное согласие: кейс — в `evaluations/`, стенограммы —
    в каталог улик. Замороженный вердикт цепочки считается от ТОГО ЖЕ текста, что лёг в файл."""
    gates = gates if gates is not None else load_gates()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    tdir = Path(transcripts_dir or TRANSCRIPTS_DIR)
    tdir.mkdir(parents=True, exist_ok=True)
    recorded = []
    for i, text in enumerate(live["answers"], 1):
        name = f"{case['id']}-{i}.md"
        (tdir / name).write_text(text, encoding="utf-8")
        recorded.append({"recorded_at": now, "provider": provider_name, "model": model or "",
                         "derived_status": derive_verdict(case, text, gates)["status"],
                         "transcript": name})
    case = {k: v for k, v in case.items() if not k.startswith("_")}
    case["recorded"] = recorded
    case["stability"] = {"measured_at": now, "runs": len(live["verdicts"]),
                         "agreement": live["agreement"], "verdicts": live["verdicts"]}
    path = Path(cases_dir or CASES_DIR) / f"{case['id']}.yaml"
    write_case(path, case)
    return path


# ---------------------------------------------------------------- CLI

def format_live(rep) -> str:
    L = [f"GATE-EVAL [live] провайдер: {rep['provider']}"
         f"{' · модель ' + rep['model'] if rep['model'] else ''} · повторов на кейс: "
         f"{rep['repeats']}"]
    for r in rep["results"]:
        mark = "  ok  " if r["matches_expected"] and r["stable"] else " ПЛЫВЁТ"
        L.append(f"{mark} {r['case']} [{r['gate']}] ожидалось {r['expected']} · "
                 f"получено {r['verdicts']} · согласие {r['agreement']}")
        for f in r["failures"]:
            L.append(f"          НЕ СОСТОЯЛОСЬ: {f}")
    if rep["skipped"]:
        L.append(f"  пропущены (кейс без входа для судьи): {', '.join(rep['skipped'])}")
    L.append("  замер стареет: он верен для названного провайдера, модели и даты — и ни для чего "
             "другого.")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Живой замер устойчивости судейского вердикта")
    ap.add_argument("--repeats", type=int, default=3, help="повторов одного кейса (по умолчанию 3)")
    ap.add_argument("--case", help="один кейс по id")
    ap.add_argument("--provider", help="провайдер (по умолчанию — резолв как в прогоне)")
    ap.add_argument("--model", help="модель провайдера")
    ap.add_argument("--record", action="store_true", help="записать ответы и согласие в кейс")
    ap.add_argument("--cases-dir", help="каталог кейсов")
    ap.add_argument("--transcripts-dir",
                    help="каталог стенограмм (по умолчанию qualification/evidence/gate-evals)")
    ap.add_argument("--json", action="store_true", help="машиночитаемый отчёт")
    args = ap.parse_args(argv)

    cases, errors = load_cases(args.cases_dir, args.transcripts_dir)
    if errors:
        print("корпус битый — живой прогон не начат:\n  - " + "\n  - ".join(errors),
              file=sys.stderr)
        return 1
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
        if not cases:
            print(f"кейса '{args.case}' нет в корпусе", file=sys.stderr)
            return 1

    res = resolve_provider(args.provider)
    provider_name = res["provider"]
    if provider_name == "mock":
        # mock — детерминированная заглушка; замерять ею устойчивость судьи значит замерять
        # заглушку и записать результат как мнение модели.
        print("провайдер резолвится в mock — живой замер невозможен. "
              f"{res.get('warning') or res.get('reason')}", file=sys.stderr)
        return 1
    provider_fn = make_provider(provider_name, args.model)

    gates, agents_index = load_gates(), _agents_index()
    results, skipped = [], []
    for c in cases:
        if c["case_kind"] != "judge_output":
            skipped.append(c["id"])
            continue
        live = run_case_live(c, provider_fn, args.repeats, gates, agents_index)
        results.append(live)
        if args.record and live["answers"]:
            p = record_into_case(c, live, provider_name, args.model, args.cases_dir, gates,
                                 args.transcripts_dir)
            live["recorded_to"] = p.name

    rep = {"schema_version": 1, "kind": "gate-eval-report", "mode": "live",
           "provider": provider_name, "model": args.model or "", "repeats": args.repeats,
           "results": results, "skipped": skipped,
           "clean": all(r["matches_expected"] and r["stable"] for r in results) and bool(results)}
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print(format_live(rep))
    return 0 if rep["clean"] else 1


if __name__ == "__main__":
    sys.exit(main())
