#!/usr/bin/env python3
"""Проверка реестра решений (v2.10) — Decision Intelligence из team-os-toolkit.

Реестр (decisions/registry.yaml) хранит принципы (способ мышления), эпизоды
(конкретные решения) и исходы. Валидатор проверяет целостность и калибровку —
чтобы decisions не превратился в свалку личных привычек:

  1. id принципов/эпизодов уникальны; обязательные поля на месте;
  2. status ∈ {proposed, ratified, retired}; retired обязан иметь retired_reason;
  3. confidence ∈ {low, medium, high}; recurrence_count >= 0; review_date парсится;
  4. supersedes ссылается на существующий принцип (или null);
  5. derived_from ссылается на существующие эпизоды;
  6. reversibility эпизода ∈ {two-way, one-way}; date парсится; опционально у эпизода
     confidence ∈ {low, medium, high}, review_at парсится и expected_outcome — объект
     с непустыми metric/baseline/target (все три поля необязательны, отсутствие — норма);
  7. outcomes.decision ссылается на существующий эпизод;
  8. предупреждение (не ошибка): ratified-принцип с recurrence_count < 2 и без
     контрпримеров — «принцип из одного случая» (калибровка из скилла decision-support).

Использование:  validate_decisions.py [registry.yaml] [--json]   (default: decisions/registry.yaml)
                validate_decisions.py --selftest
Возврат 0 — валиден (возможны WARN), 1 — есть ошибки целостности.
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import yaml

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
            Path(__file__).resolve().parents[1])
STATUS = {"proposed", "ratified", "retired"}
CONFIDENCE = {"low", "medium", "high"}
REVERSIBILITY = {"two-way", "one-way"}


def parse_date(s):
    try:
        datetime.strptime(str(s), "%Y-%m-%d")
        return True
    except (ValueError, TypeError):
        return False


def check(data: dict):
    errors, warns = [], []
    principles = data.get("principles") or []
    episodes = data.get("episodes") or []
    outcomes = data.get("outcomes") or []
    ep_ids = {e.get("id") for e in episodes}
    pr_ids = {p.get("id") for p in principles}

    seen = set()
    for e in episodes:
        eid = e.get("id")
        if eid in seen:
            errors.append(f"эпизод: дублирующийся id {eid}")
        seen.add(eid)
        for f in ("id", "question", "decision", "reason", "reversibility", "date"):
            if not e.get(f):
                errors.append(f"эпизод {eid}: нет поля {f}")
        if e.get("reversibility") not in REVERSIBILITY:
            errors.append(f"эпизод {eid}: reversibility '{e.get('reversibility')}' не в {REVERSIBILITY}")
        if not parse_date(e.get("date")):
            errors.append(f"эпизод {eid}: date не парсится (YYYY-MM-DD)")
        # опциональная калибровка эпизода — проверяем форму, только если поле присутствует.
        # Отсутствие любого из полей — норма (обратная совместимость со старыми эпизодами).
        conf = e.get("confidence")
        if conf is not None and conf not in CONFIDENCE:
            errors.append(f"эпизод {eid}: confidence '{conf}' не в {CONFIDENCE}")
        if e.get("review_at") is not None and not parse_date(e.get("review_at")):
            errors.append(f"эпизод {eid}: review_at не парсится (YYYY-MM-DD)")
        exp = e.get("expected_outcome")
        if exp is not None:
            if not isinstance(exp, dict):
                errors.append(f"эпизод {eid}: expected_outcome должен быть объектом (metric/baseline/target)")
            else:
                for f in ("metric", "baseline", "target"):
                    if exp.get(f) in (None, ""):
                        errors.append(f"эпизод {eid}: expected_outcome.{f} пусто")

    seen = set()
    for p in principles:
        pid = p.get("id")
        if pid in seen:
            errors.append(f"принцип: дублирующийся id {pid}")
        seen.add(pid)
        for f in ("id", "principle", "scope", "status", "confidence", "recurrence_count", "review_date", "derived_from"):
            if p.get(f) in (None, ""):
                errors.append(f"принцип {pid}: нет поля {f}")
        if p.get("status") not in STATUS:
            errors.append(f"принцип {pid}: status '{p.get('status')}' не в {STATUS}")
        if p.get("confidence") not in CONFIDENCE:
            errors.append(f"принцип {pid}: confidence '{p.get('confidence')}' не в {CONFIDENCE}")
        if not isinstance(p.get("recurrence_count"), int) or p.get("recurrence_count", -1) < 0:
            errors.append(f"принцип {pid}: recurrence_count должен быть int >= 0")
        if not parse_date(p.get("review_date")):
            errors.append(f"принцип {pid}: review_date не парсится (YYYY-MM-DD)")
        if p.get("status") == "retired" and not p.get("retired_reason"):
            errors.append(f"принцип {pid}: status retired требует retired_reason")
        sup = p.get("supersedes")
        if sup and sup not in pr_ids:
            errors.append(f"принцип {pid}: supersedes '{sup}' — нет такого принципа")
        for d in (p.get("derived_from") or []):
            if d not in ep_ids:
                errors.append(f"принцип {pid}: derived_from '{d}' — нет такого эпизода")
        # калибровка (WARN)
        if p.get("status") == "ratified" and isinstance(p.get("recurrence_count"), int) \
                and p["recurrence_count"] < 2 and not (p.get("counterexamples")):
            warns.append(f"принцип {pid}: ratified при recurrence_count<2 — принцип из одного случая?")

    for o in outcomes:
        if o.get("decision") not in ep_ids:
            errors.append(f"outcome: decision '{o.get('decision')}' — нет такого эпизода")

    return errors, warns


def run(reg: Path, as_json=False):
    if not reg.exists():
        print(f"реестр решений не найден: {reg} — нечего проверять (это не ошибка).")
        return 0
    data = yaml.safe_load(reg.read_text(encoding="utf-8")) or {}
    errors, warns = check(data)
    if as_json:
        print(json.dumps({"schema_version": 1, "kind": "decisions-report",
                          "file": str(reg), "errors": errors, "warns": warns},
                         ensure_ascii=False, indent=2))
    else:
        for w in warns:
            print(f"  WARN {w}")
        if errors:
            print(f"DECISIONS: {len(errors)} ошибок целостности:")
            for e in errors:
                print(f"  - {e}")
        else:
            n = len(data.get('principles') or [])
            print(f"DECISIONS-OK: реестр валиден ({n} принципов, "
                  f"{len(data.get('episodes') or [])} эпизодов)" +
                  (f", {len(warns)} предупреждений по калибровке." if warns else "."))
    return 1 if errors else 0


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    reg = Path(args[0]).resolve() if args else (PKG / "decisions" / "registry.yaml")
    return run(reg, as_json="--json" in argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
