#!/usr/bin/env python3
"""Atomic Planning и Context Budget -> WorkPackagePlan (v2.100, эпик Context Engineering, этап 4).

Размер рабочего пакета должен соответствовать способности модели выполнить его ДО деградации
контекста. Оцениваем пакет и предлагаем декомпозицию, когда он слишком велик.

Оценка пакета: предполагаемый объём контекста (из ContextBundle), число файлов, число системных
границ (подсистем), зависимости, ожидаемые model calls, риск, критерий завершения.

Декомпозиция предлагается, если:
  * контекст превышает бюджет;
  * затрагивается слишком много подсистем (системных границ);
  * задача помечена как несколько независимых результатов;
  * требуется больше одного логически завершённого commit;
  * план нельзя проверить одним набором критериев;
  * размер задачи large/xl.

Ограничение (инвариант): автодекомпозиция НЕ меняет продуктовый смысл — она лишь называет ОСИ
разбиения (по подсистемам / по результатам), а не выдумывает новые бизнес-решения ради удобства
модели. Итоговое разбиение подтверждает человек.

Использование:
  atomic_planner.py assess <child_root> --signals '{...}' [--budget N] [--json]
  atomic_planner.py --selftest
Возврат 0 — пакет атомарен; 1 — нужна декомпозиция (или ошибка).
"""

import argparse
import json
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
for _p in (PKG / "tools",):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

MAX_SUBSYSTEMS = 2          # больше системных границ на пакет -> кандидат на разбиение
SIZE_FILES = {"small": 3, "medium": 8, "large": 20, "xl": 40}


def estimate(signals, child_root=None, bundle=None):
    """Оценка рабочего пакета. Детерминированно; бюджет/токены — из ContextBundle, если доступен."""
    signals = dict(signals or {})
    subsystems = sorted(set(signals.get("affected_areas") or []))
    size = (signals.get("size") or "medium").lower()

    context_tokens, budget = None, None
    if bundle is None and child_root is not None:
        try:
            import context_compiler
            bundle = context_compiler.compile_bundle(signals, child_root)
        except Exception:  # noqa: BLE001
            bundle = None
    if bundle:
        context_tokens = bundle.get("estimated_tokens")
        budget = bundle.get("context_budget")

    files_estimate = len(bundle["included"]["files"]) if bundle and bundle["included"]["files"] \
        else SIZE_FILES.get(size, 8)
    return {
        "estimated_context_tokens": context_tokens,
        "context_budget": budget,
        "files_estimate": files_estimate,
        "subsystems": subsystems,
        "dependencies": list(signals.get("depends_on") or []),
        "expected_model_calls": signals.get("expected_model_calls"),
        "risk": (signals.get("risk") or "").lower() or None,
        "completion_criterion": signals.get("completion_criterion")
                                or "один проверяемый результат (уточнить)",
    }


def assess(signals, child_root=None, bundle=None, budget=None):
    """Собрать WorkPackagePlan: оценка + нужна ли декомпозиция + оси разбиения. Детерминированно."""
    signals = dict(signals or {})
    est = estimate(signals, child_root=child_root, bundle=bundle)
    size = (signals.get("size") or "medium").lower()
    reasons, axes = [], []

    eff_budget = budget or est.get("context_budget")
    tok = est.get("estimated_context_tokens")
    if tok is not None and eff_budget and tok > eff_budget:
        reasons.append(f"контекст {tok} ток. превышает бюджет {eff_budget} — разбить по объёму")
        axes.append("by-context-budget")
    if len(est["subsystems"]) > MAX_SUBSYSTEMS:
        reasons.append(f"{len(est['subsystems'])} системных границ ({', '.join(est['subsystems'])}) "
                       f"> {MAX_SUBSYSTEMS} — разбить по подсистемам")
        axes.append("by-subsystem")
    if int(signals.get("independent_results") or 1) > 1:
        reasons.append(f"{signals['independent_results']} независимых результата(ов) — разбить по результатам")
        axes.append("by-result")
    if signals.get("multiple_commits") is True:
        reasons.append("требуется больше одного логически завершённого commit — по одному пакету на commit")
        axes.append("by-commit")
    if signals.get("single_criteria_verifiable") is False:
        reasons.append("план нельзя проверить одним набором критериев — разбить до проверяемых единиц")
        axes.append("by-verifiable-unit")
    if size in ("large", "xl"):
        reasons.append(f"размер задачи {size} — кандидат на разбиение до атомарных пакетов")
        axes.append("by-size")

    should = bool(reasons)
    # уникальные оси, стабильный порядок
    seen, uniq_axes = set(), []
    for a in axes:
        if a not in seen:
            seen.add(a); uniq_axes.append(a)

    return {
        "schema_version": 1, "kind": "WorkPackagePlan",
        "estimate": est,
        "should_decompose": should,
        "decomposition_reasons": reasons,
        "decomposition_axes": uniq_axes,
        "atomic": not should,
        "constraint_note": "декомпозиция называет ОСИ разбиения, но НЕ меняет продуктовый смысл и "
                           "не принимает новых бизнес-решений ради удобства модели; итог подтверждает человек",
        "acceptance": [
            "один проверяемый результат на пакет",
            "каждый пакет — отдельный commit",
            "зависимости между пакетами явные; пакет не стартует без подтверждённой зависимости",
        ],
    }


def selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "package.json").write_text('{"dependencies":{"react":"^18"}}', encoding="utf-8")

        # атомарный: один subsystem, small -> не декомпозировать
        a = assess({"task_type": "QUICK", "size": "small", "affected_areas": ["core"]}, child_root=root)
        expect("атомарный QUICK -> should_decompose=False", a["should_decompose"] is False and a["atomic"])
        expect("оценка несёт подсистемы и критерий", a["estimate"]["subsystems"] == ["core"]
               and a["estimate"]["completion_criterion"])

        # много подсистем -> by-subsystem
        b = assess({"task_type": "ENGINEERING", "size": "medium",
                    "affected_areas": ["catalog", "orders", "billing", "search"]}, child_root=root)
        expect("4 подсистемы -> декомпозиция by-subsystem", b["should_decompose"]
               and "by-subsystem" in b["decomposition_axes"])

        # несколько независимых результатов -> by-result
        c = assess({"task_type": "ENGINEERING", "size": "medium", "affected_areas": ["core"],
                    "independent_results": 3}, child_root=root)
        expect("independent_results=3 -> by-result", "by-result" in c["decomposition_axes"])

        # large -> by-size
        d = assess({"task_type": "ENGINEERING", "size": "large", "affected_areas": ["core"]}, child_root=root)
        expect("size=large -> by-size", "by-size" in d["decomposition_axes"])

        # превышение бюджета -> by-context-budget
        e = assess({"task_type": "ENGINEERING", "size": "small", "affected_areas": ["core"]},
                   child_root=root, budget=10)
        expect("бюджет 10 превышен -> by-context-budget", "by-context-budget" in e["decomposition_axes"])

        # не одним критерием -> by-verifiable-unit
        f = assess({"task_type": "ENGINEERING", "size": "medium", "affected_areas": ["core"],
                    "single_criteria_verifiable": False}, child_root=root)
        expect("не проверяемо одним критерием -> by-verifiable-unit",
               "by-verifiable-unit" in f["decomposition_axes"])

        # инвариант: constraint_note про сохранение смысла присутствует
        expect("constraint: не меняем продуктовый смысл", "продуктовый смысл" in a["constraint_note"])
        # acceptance-критерии есть
        expect("acceptance: один результат + отдельный commit + явные зависимости",
               len(a["acceptance"]) == 3)

    print("atomic_planner selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    ap = argparse.ArgumentParser(prog="atomic_planner.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a_ = sub.add_parser("assess")
    a_.add_argument("child_root", nargs="?", default=".")
    a_.add_argument("--signals", default="{}")
    a_.add_argument("--budget", type=int)
    a_.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "assess":
        wp = assess(json.loads(a.signals), child_root=Path(a.child_root), budget=a.budget)
        if a.json:
            print(json.dumps(wp, ensure_ascii=False, indent=2))
        else:
            est = wp["estimate"]
            print(f"WORK-PACKAGE: atomic={wp['atomic']} · подсистем {len(est['subsystems'])} · "
                  f"~{est['estimated_context_tokens']}/{est['context_budget']} ток. · файлов ~{est['files_estimate']}")
            for r in wp["decomposition_reasons"]:
                print(f"  ⚠ {r}")
            if wp["should_decompose"]:
                print(f"  оси разбиения: {', '.join(wp['decomposition_axes'])}")
        return 1 if wp["should_decompose"] else 0
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
