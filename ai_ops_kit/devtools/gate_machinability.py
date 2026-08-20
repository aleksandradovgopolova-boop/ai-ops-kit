#!/usr/bin/env python3
"""Разбор «зелёного по мнению»: что может стать машинным, а что нет (C3, v3.37).

Карта `closed_by` в `quality/gates.yaml` отвечает, КТО закрывает гейт сегодня. Этот модуль читает
`quality/gate-machinability.yaml` — ответ на следующий вопрос: у кого это положение вещей
временное, а у кого по существу, и что конкретно нужно, чтобы перевести.

ПОЧЕМУ ЭТО КОД, А НЕ ДОКУМЕНТ. Разбор, лежащий прозой, расходится с реестром в первый же день:
гейт перевели — строка осталась, гейт добавили — строки нет. Здесь связь проверяется: покрыты
РОВНО те гейты, что закрываются не валидатором, ни одного лишнего и ни одного забытого. Плюс
ратчет: переведённый гейт обязан быть отмечен `status: done`, иначе карта хвалится тем, чего не
делала, — а нехватка записи о новом гейте краснеет сразу.

Использование:
  python3 -m ai_ops_kit.devtools.gate_machinability          — разбор, человекочитаемо
  python3 -m ai_ops_kit.devtools.gate_machinability --json   — машиночитаемо

Возврат: 0 — карта сходится с реестром; 1 — разошлась (расхождения названы поимённо).
Требует pyyaml.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from ai_ops_kit.gates.gate_executor import load_gates

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
           Path(__file__).resolve().parents[2])
# ПОЧЕМУ В `devtools`, А НЕ В `gates`. Это АНАЛИЗ реестра гейтов — отчёт для того, кто его
# развивает, а не проверка, исполняемая в прогоне. `devtools` объявлен dev-only в поставке, и это
# по существу: данные разбора (`quality/gate-machinability.yaml`) в дочку не едут тоже (манифест
# поставляет из `quality/` только `gates.yaml`), так что оставить сам отчёт в поставляемом `gates/`
# значило бы отправить дочке модуль без его данных — мёртвый груз, класс F-030/F-032. Сам ПЕРЕВОД
# гейта в машинный живёт отдельно, в поставляемом `gates/documentation_evidence.py`.
REGISTRY = PKG / "quality" / "gate-machinability.yaml"

VERDICTS = ("mechanizable", "partly", "human_by_nature")
# Гейт, чьё «зелёное» — не результат машины. Ровно эти обязан покрывать разбор.
OPINION_CLOSURES = ("judge", "writer")


def load_registry(path=None) -> dict:
    return yaml.safe_load(Path(path or REGISTRY).read_text(encoding="utf-8"))


def opinion_gates(gates=None) -> set:
    gates = gates if gates is not None else load_gates()
    return {gid for gid, g in gates.items() if g.get("closed_by") in OPINION_CLOSURES}


def coverage_errors(registry=None, gates=None) -> list:
    """Разбор сошёлся с реестром? Пустой список = сошёлся.

    Проверяется в обе стороны намеренно. Забытый гейт — дыра в разборе; лишний — след гейта,
    который уже перевели, и он завышает картину «сколько ещё осталось»."""
    registry = registry if registry is not None else load_registry()
    gates = gates if gates is not None else load_gates()
    entries = registry.get("gates") or {}
    errs = []

    opinion = opinion_gates(gates)
    # Переведённые (`status: done`) остаются в разборе как история перевода — они уже машинные,
    # и в множестве «мнение» их нет. Это не лишние записи, а закрытые.
    done = {gid for gid, e in entries.items() if (e or {}).get("status") == "done"}

    for gid in sorted(opinion - set(entries)):
        errs.append(f"{gid}: закрывается мнением, но в разборе machinability его нет")
    for gid in sorted(set(entries) - opinion - done):
        errs.append(f"{gid}: есть в разборе, но мнением уже не закрывается — "
                    f"пометьте `status: done`, если он переведён")
    for gid in sorted(done & opinion):
        errs.append(f"{gid}: помечен `status: done`, но всё ещё закрывается мнением "
                    f"({gates[gid].get('closed_by')}) — карта хвалится тем, чего не сделала")

    for gid, e in sorted(entries.items()):
        if not isinstance(e, dict):
            errs.append(f"{gid}: запись должна быть mapping"); continue
        if e.get("verdict") not in VERDICTS:
            errs.append(f"{gid}.verdict: '{e.get('verdict')}' вне {list(VERDICTS)}")
        if not (e.get("reason") or "").strip():
            errs.append(f"{gid}: вердикт без причины — это мнение о мнении")
        if not (e.get("needs") or "").strip():
            errs.append(f"{gid}: нет `needs` — разбор без «что для этого нужно» неисполним")
        g = gates.get(gid) or {}
        declared = set((e.get("machine_evidence") or []) + (e.get("judge_evidence") or []))
        actual = set(g.get("required_evidence") or [])
        unknown = declared - actual
        if unknown:
            errs.append(f"{gid}: доказательства {sorted(unknown)} нет в quality/gates.yaml")
    return errs


def split(registry=None, gates=None) -> dict:
    """Разбор -> три группы плюс числа. Числа — то, ради чего разбор существует."""
    registry = registry if registry is not None else load_registry()
    gates = gates if gates is not None else load_gates()
    entries = registry.get("gates") or {}
    groups = {v: sorted(gid for gid, e in entries.items() if (e or {}).get("verdict") == v)
              for v in VERDICTS}
    done = sorted(gid for gid, e in entries.items() if (e or {}).get("status") == "done")
    opinion = opinion_gates(gates)
    machine = sorted(gid for gid, g in gates.items() if g.get("closed_by") == "validator")
    return {
        "schema_version": 1, "kind": "gate-machinability-report",
        "measured_at": registry.get("measured_at"),
        "gates_total": len(gates), "closed_by_machine": len(machine),
        "closed_by_opinion": len(opinion),
        "groups": groups, "counts": {v: len(groups[v]) for v in VERDICTS},
        "already_mechanized": done,
        "errors": coverage_errors(registry, gates),
    }


def format_report(rep) -> str:
    L = [f"РАЗБОР «ЗЕЛЁНОГО ПО МНЕНИЮ» (замер {rep['measured_at']})",
         f"  гейтов всего {rep['gates_total']}: машиной {rep['closed_by_machine']}, "
         f"мнением {rep['closed_by_opinion']}"]
    titles = {"mechanizable": "может стать машинным (доказательства фактические)",
              "partly": "частично: машина закроет часть и сузит мнение до остатка",
              "human_by_nature": "по существу человеческое: машинной остаётся только форма"}
    for v in VERDICTS:
        L.append(f"  {rep['counts'][v]:>2} · {titles[v]}")
        for gid in rep["groups"][v]:
            L.append(f"       {gid}")
    if rep["already_mechanized"]:
        L.append(f"  переведено: {', '.join(rep['already_mechanized'])}")
    for e in rep["errors"]:
        L.append(f"  РАСХОЖДЕНИЕ: {e}")
    L.append("  «Может стать машинным» — не обещание перевести, а утверждение о природе "
             "доказательств. Что для этого нужно, у каждого записано в `needs`.")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Разбор машинизуемости судейских гейтов")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    rep = split()
    print(json.dumps(rep, ensure_ascii=False, indent=2) if args.json else format_report(rep))
    return 0 if not rep["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
