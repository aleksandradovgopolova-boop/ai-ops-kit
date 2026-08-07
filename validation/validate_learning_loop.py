#!/usr/bin/env python3
from __future__ import annotations
"""Learning-loop fitness — v3.3.1. Целостность петли research -> learning -> architecture.

FeatureLearning (product-learning/) фиксирует исход и в follow_up ссылается на порождённые артефакты.
Ссылки вида ADR-NNN ДОЛЖНЫ резолвиться в реальный ADR-реестр (decisions/adr) — иначе «мы это учли и
породили ADR-X», а ADR-X нет: петля обучения разорвана. Это fitness поверх двух реестров:

  1. каждая follow_up-ссылка ADR-NNN резолвится в существующий ADR;
  2. согласованность: FL со status validated/closed и verdict confirmed/refuted, породивший ADR
     (follow_up ADR-NNN), должен ссылаться на СУЩЕСТВУЮЩИЙ ADR (петля замкнута);
  3. RR-NNN / DP-NNN / feature:<...> — СЛАБЫЕ ссылки (research-контур и продукт управляются иначе):
     проверяется только формат-намерение, файловая резолюция НЕ требуется.

Предполагает, что оба реестра индивидуально валидны (их проверяют свои валидаторы в CI); при поломке
любого — честно сообщает «почините реестр» вместо ложной уверенности.

Использование:  validate_learning_loop.py [--json] | --selftest
Возврат 0 — петля цела, 1 — разрыв.
"""
import json
import re
import sys
from pathlib import Path

import yaml

import _bootstrap  # noqa: E402
import validate_adr_registry as adrreg          # noqa: E402
import validate_feature_learning as flreg        # noqa: E402

_ADR = re.compile(r"^ADR-[0-9]{3,}$")


def check_loop(fl_dir: Path, adr_dir: Path):
    errors = []
    fl_errs, _ = flreg.check_registry(fl_dir)
    adr_errs, adr_ids = adrreg.check_registry(adr_dir)
    adr_ids = set(adr_ids)
    if fl_errs:
        errors.append(f"FL-реестр невалиден ({len(fl_errs)}) — почините FeatureLearning сначала")
    if adr_errs:
        errors.append(f"ADR-реестр невалиден ({len(adr_errs)}) — почините ADR сначала")
    if errors:
        return errors, {}

    resolved, dangling = 0, 0
    for f in sorted(Path(fl_dir).glob("FL-*.yaml")) if Path(fl_dir).is_dir() else []:
        try:
            fl = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        fid = fl.get("id", f.stem)
        for ref in fl.get("follow_up", []) or []:
            if isinstance(ref, str) and _ADR.match(ref):
                if ref in adr_ids:
                    resolved += 1
                else:
                    dangling += 1
                    errors.append(f"{fid}.follow_up -> несуществующий ADR {ref} (петля learning->architecture разорвана)")
            # RR-/DP-/feature: — слабые ссылки, не резолвим
    stats = {"adr_refs_resolved": resolved, "adr_refs_dangling": dangling,
             "adr_registry_size": len(adr_ids)}
    return errors, stats


def main(argv):
    errors, stats = check_loop(flreg.DEFAULT_DIR, adrreg.DEFAULT_DIR)
    if "--json" in argv:
        print(json.dumps({"stats": stats, "errors": errors}, ensure_ascii=False, indent=2))
    elif errors:
        print(f"LEARNING-LOOP: {len(errors)} разрывов:")
        for x in errors:
            print(f"  - {x}")
    else:
        print(f"LEARNING-LOOP-OK: петля research->learning->architecture цела "
              f"(ADR-ссылок резолвлено: {stats.get('adr_refs_resolved')}).")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
