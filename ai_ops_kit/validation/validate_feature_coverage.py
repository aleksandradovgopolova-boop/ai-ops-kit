#!/usr/bin/env python3
"""Гейт охвата фич: сверка реестра фич дочки с поверхностями из кода, сила по confidence (W3).

Незадокументированная фича — поверхность в коде без сопоставленной фичи в реестре — обнаружимая
находка. СИЛА находки честна по УВЕРЕННОСТИ вывода поверхности:

  * verified-orphan → БЛОКИРУЮЩАЯ проблема (fail): вывод доказан детерминированно;
  * inferred-orphan → advisory (warn, не блокирует): предположение эвристики;
  * ghost (фича без следа в коде, кроме status=planned) → advisory (warn).

BOOTSTRAP / РАТЧЕТ: у пустого реестра или на первом прогоне все поверхности — сироты. Чтобы первая
установка не утонула в блокировках, вердикт fail наступает лишь когда verified-сирот СТАЛО БОЛЬШЕ
baseline (появилась НОВАЯ незадокументированная verified-поверхность). Ратчет ходит только вниз.

Проверяющая логика — в ПОСТАВЛЯЕМОМ модуле `ai_ops_kit.checks.feature_coverage` (слой primitives);
здесь — тонкий процессный вход (CI/gate), который тянет её ВНИЗ по слоям, без восходящего ребра. Так
же устроен `validate_capability_policy` → `checks.capability_policy`.

Вход — YAML с реестром и извлечёнными поверхностями (поверхности даёт извлечение W2, доставка в дочку —
W4). Судья их НЕ извлекает сам, поэтому не зависит от конкретного экстрактора:

    registry: {features: [...]}      # или плоско  features: [...]
    surfaces: [{kind, ref, confidence, extractor}, ...]
    baseline_verified_orphans: 0     # опц.: сколько verified-сирот заранее принято (ратчет вниз)

Использование:
  validate_feature_coverage.py [coverage-input.yaml] [--json]
Без аргумента входных данных нет (в самом ките нет реестра+поверхностей дочки) — проверять нечего,
возврат 0. С аргументом: 0 — блокирующих находок нет (pass/warn), 1 — есть verified-orphan сверх
baseline (fail). Как validate_surface_wiring, гейт осмыслен на child-ПРОДУКТЕ, не на самом ките.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:                                          # двурежимный, как соседние валидаторы
    from ai_ops_kit.validation import _bootstrap   # noqa: F401 — импорт пакетом (после pip install)
except ImportError:                                # запуск скриптом: корня на пути ещё нет,
    import _bootstrap                              # noqa: F401 — и положить его может только он сам

import yaml  # noqa: E402

from ai_ops_kit.checks import feature_coverage as fc  # noqa: E402


def load_input(path: Path) -> tuple[dict, list, int]:
    """Прочитать вход гейта: (registry, surfaces, baseline_verified_orphans)."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    registry = data.get("registry")
    if not isinstance(registry, dict):
        registry = {"features": data.get("features") or []}
    surfaces = data.get("surfaces") or []
    baseline = int(data.get("baseline_verified_orphans") or 0)
    return registry, surfaces, baseline


def blocking_problems(registry: dict, surfaces: list, baseline_verified_orphans: int = 0) -> list[str]:
    """Список БЛОКИРУЮЩИХ проблем (verified-сироты, когда их стало больше baseline).

    Пустой список = блокировать нечего. Advisory (inferred-сироты, ghost'ы) СЮДА НЕ входят — они
    возвращаются отдельно `advisory_warnings`, печатаются как предупреждения и код возврата не меняют.
    """
    verdict = fc.coverage_verdict(fc.build_coverage_report(registry, surfaces), baseline_verified_orphans)
    if verdict["status"] != "fail":
        return []
    report = fc.build_coverage_report(registry, surfaces)
    return [f"незадокументированная verified-поверхность без фичи в реестре: {o['surface'].get('ref')}"
            for o in fc.verified_orphans(report)]


def advisory_warnings(registry: dict, surfaces: list) -> list[str]:
    """Список НЕ блокирующих предупреждений: inferred-сироты и ghost-фичи."""
    report = fc.build_coverage_report(registry, surfaces)
    warns = [f"inferred-поверхность без фичи (предупреждение, не блок): {o['surface'].get('ref')}"
             for o in fc.inferred_orphans(report)]
    warns += [f"фича без следа в коде (ghost, предупреждение): {gid}" for gid in report["ghosts"]]
    return warns


def run(path: Path, as_json: bool = False) -> int:
    registry, surfaces, baseline = load_input(path)
    ev = fc.evaluate(registry, surfaces, baseline)
    blocking = blocking_problems(registry, surfaces, baseline)
    warns = advisory_warnings(registry, surfaces)
    if as_json:
        print(json.dumps({"schema_version": 1, "kind": "feature-coverage-report",
                          "file": str(path), "report": ev["report"], "verdict": ev["verdict"]},
                         ensure_ascii=False, indent=2))
        return 1 if blocking else 0
    for w in warns:
        print(f"  [WARN] {w}")
    if blocking:
        print(f"FEATURE-COVERAGE-FAIL: {len(blocking)} блокирующих находок (verified-orphan):")
        for b in blocking:
            print(f"  [FAIL] {b}")
        return 1
    r = ev["report"]
    print(f"FEATURE-COVERAGE-OK: покрыто {len(r['covered'])} поверхностей, verified-охват "
          f"{r['coverage_pct_verified']}%; предупреждений {len(warns)} (не блокируют).")
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in argv
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        print("охват фич: нет входных данных (реестр+поверхности дочки) — нечего проверять "
              "(это не ошибка).")
        return 0
    return run(Path(args[0]).resolve(), as_json=as_json)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
