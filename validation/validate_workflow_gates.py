#!/usr/bin/env python3
"""Согласованность workflow ↔ gate (v2.16; track-aware + orphan-guard v2.67).

Раньше валидаторы проверяли только существование gate/agent id и обязательные поля,
но не то, что гейт, включённый в workflow.quality_gates, ВООБЩЕ применим к этому
workflow. Так VISUAL/ANALYTICS ссылались на implementation_verification, чьё
applicability их не включало — контракт сам себе противоречил, а CI молчал.

v2.67 (self-audit против видения): валидатор стал track-aware. Гейт может попадать в
прогон двумя путями — статически (workflow.quality_gates) ИЛИ динамически (registry/
tracks.yaml добавляет гейты по сигналам задачи, механика RunPlan). Прежняя проверка не
знала про треки и сыпала ложными WARN (ux_review/ai_eval и т.п. «пропущены», хотя их
даёт трек). Теперь: track-провайд считается достижимостью, а недостижимый MVP-blocking
гейт — это уже не WARN, а ERROR (гарантия «8 MVP-blocking» обязана быть исполнимой).

Проверки:
  1. ERROR: гейт в workflow.quality_gates обязан числить этот workflow в
     `applicability` (или applicability=[all]);
  2. ERROR: гейт из quality_gates существует в quality/gates.yaml;
  3. ERROR: gate.applicability ссылается на НЕсуществующий workflow (кроме 'all') —
     иначе гейт «применим» к тому, чего нет (класс security→INCIDENT);
  4. ERROR: MVP-blocking гейт применим к workflow, но НЕдостижим ни статически, ни
     через трек — обещанная блокировка не сработает (orphan-guard);
  5. WARN: прочий blocking-гейт применим, но не включён и не покрыт треком —
     возможный пропуск (информационно).

Использование:  validate_workflow_gates.py [--json] | --selftest
Возврат 0 — согласовано (возможны WARN), 1 — есть ERROR.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
            Path(__file__).resolve().parents[1])
def load():
    gdoc = yaml.safe_load((PKG / "quality" / "gates.yaml").read_text(encoding="utf-8"))
    gates = gdoc.get("gates", {})
    mvp = set(gdoc.get("mvp_blocking_gates", []) or [])
    wfs = yaml.safe_load((PKG / "registry" / "workflows.yaml").read_text(encoding="utf-8")).get("workflows", {})
    try:
        tdoc = yaml.safe_load((PKG / "registry" / "tracks.yaml").read_text(encoding="utf-8"))
        tracks = tdoc.get("tracks", {}) or {}
    except FileNotFoundError:
        tracks = {}
    track_gates = set()
    for t in tracks.values():
        track_gates.update(t.get("gates") or [])
    return gates, wfs, mvp, track_gates


def check(gates: dict, wfs: dict, mvp=None, track_gates=None):
    mvp = mvp or set()
    track_gates = track_gates or set()
    known_wf = set(wfs.keys())
    errors, warns = [], []

    # 3. gate.applicability не должен ссылаться на несуществующий workflow
    for gid, g in gates.items():
        for wid in (g.get("applicability", []) or []):
            if wid != "all" and wid not in known_wf:
                errors.append(f"гейт '{gid}': applicability ссылается на неизвестный workflow "
                              f"'{wid}' (нет в registry/workflows.yaml)")

    for wid, w in wfs.items():
        used = w.get("quality_gates", []) or []
        for gid in used:
            g = gates.get(gid)
            if g is None:
                errors.append(f"{wid}: гейт '{gid}' отсутствует в quality/gates.yaml")
                continue
            appl = g.get("applicability", []) or []
            if "all" not in appl and wid not in appl:
                errors.append(f"{wid}: использует гейт '{gid}', но его applicability={appl} "
                              f"не включает {wid}")
        # применимые blocking-гейты, не включённые статически
        for gid, g in gates.items():
            appl = g.get("applicability", []) or []
            applicable = ("all" in appl) or (wid in appl)
            if not (g.get("blocking") and applicable and gid not in used):
                continue
            # достижимость: через трек ИЛИ через внешний путь enforcement (enforced_by),
            # напр. детерминированный OpenSpec CI-guard — тогда per-task wiring не требуется.
            via_track = gid in track_gates
            via_external = bool(g.get("enforced_by"))
            if via_track or via_external:
                continue
            if gid in mvp:
                # 4. MVP-blocking гейт недостижим (нет ни статически, ни через трек, ни enforced_by)
                errors.append(f"{wid}: MVP-blocking гейт '{gid}' применим, но НЕдостижим "
                              f"(нет в quality_gates, не даётся треком, не enforced_by) — "
                              f"обещанная блокировка не сработает")
            else:
                # 5. прочий blocking-гейт: возможный пропуск
                warns.append(f"{wid}: blocking-гейт '{gid}' применим, но не включён в "
                             f"quality_gates, не покрыт треком и без enforced_by — возможный пропуск")
    return errors, warns


def run(as_json=False):
    gates, wfs, mvp, track_gates = load()
    errors, warns = check(gates, wfs, mvp, track_gates)
    if as_json:
        print(json.dumps({"schema_version": 1, "kind": "workflow-gate-consistency",
                          "errors": errors, "warns": warns}, ensure_ascii=False, indent=2))
    else:
        for w in warns:
            print(f"  WARN {w}")
        if errors:
            print(f"WORKFLOW-GATES: {len(errors)} ошибок согласованности:")
            for e in errors:
                print(f"  - {e}")
        else:
            print(f"WORKFLOW-GATES-OK: все quality_gates применимы к своим workflow"
                  + (f" ({len(warns)} WARN о возможных пропусках)." if warns else "."))
    return 1 if errors else 0


def main(argv):
    return run(as_json="--json" in argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
