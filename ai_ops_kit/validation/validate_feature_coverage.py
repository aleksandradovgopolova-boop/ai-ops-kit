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
  # готовый вход (реестр+поверхности уже собраны):
  validate_feature_coverage.py [coverage-input.yaml] [--json]
  # РЕЖИМ ДОЧКИ (W4): собрать вход ИЗ КОДА дочки и вынести вердикт под ПЕРСИСТЕНТНЫМ baseline —
  # это и есть внешний путь enforcement, который гоняет доставленный child-CI:
  validate_feature_coverage.py --child-root . [--registry registry/features.yaml] \
      [--baseline .ai/feature-coverage-baseline.yaml] [--seed] [--json]

Без аргумента входных данных нет (в самом ките нет реестра+поверхностей дочки) — проверять нечего,
возврат 0. С готовым входом: 0 — блокирующих находок нет (pass/warn), 1 — есть verified-orphan сверх
baseline (fail). В режиме дочки: реестр читается из `--registry`, поверхности извлекаются
`extract_surfaces` (W2), baseline verified-сирот ЖИВЁТ в файле дочки `--baseline` (ратчет ВНИЗ):
`--seed` засеивает его при первом прогоне и переписывает при снижении; РОСТ verified-сирот сверх
baseline → возврат 1 (реальная блокировка). Как validate_surface_wiring, гейт осмыслен на
child-ПРОДУКТЕ, не на самом ките.
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
from ai_ops_kit.checks.surface_extraction import extract_surfaces  # noqa: E402

# Путь реестра фич В ДОЧКЕ по умолчанию (стандарт FEAT: «её registry/features.yaml или эквивалент»)
# и путь ПЕРСИСТЕНТНОГО baseline verified-сирот — файл живёт В ДОЧКЕ, переживает прогон и коммитится.
DEFAULT_CHILD_REGISTRY = "registry/features.yaml"
DEFAULT_BASELINE_PATH = ".ai/feature-coverage-baseline.yaml"


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


# ─── ПЕРСИСТЕНТНЫЙ baseline verified-сирот В ДОЧКЕ (ратчет вниз) ──────────────────────────────────

def read_baseline(path: Path):
    """Прочитать сохранённый baseline verified-сирот. -> int, либо None если файла ещё нет.

    None означает ПЕРВЫЙ прогон (baseline ещё не засеян) — его отличают от 0 (принято ноль дедов),
    поэтому именно None, а не 0: `reconcile_baseline` по None сидирует, по 0 — блокирует любую
    появившуюся verified-сироту. Битый/пустой файл читается как None (сидируем заново), а не падаем.
    """
    p = Path(path)
    if not p.is_file():
        return None
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    val = data.get("verified_orphans") if isinstance(data, dict) else None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def write_baseline(path: Path, verified_orphans: int) -> None:
    """Записать baseline В ДОЧКУ (down-only контролирует вызывающий через reconcile_baseline)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "# feature-coverage baseline — принятое число verified-сирот (ратчет ВНИЗ).\n"
        "# Сидируется CI при первом прогоне; растёт молча не может (рост = красный гейт), снижение\n"
        "# опускает его. Правит CI (validate_feature_coverage --seed), не человек. Живёт В ДОЧКЕ.\n"
        "schema_version: 1\n"
        "kind: feature-coverage-baseline\n"
        f"verified_orphans: {int(verified_orphans)}\n",
        encoding="utf-8",
    )


def load_child_registry(child_root: Path, registry_rel: str) -> dict:
    """Прочитать реестр фич ДОЧКИ (её registry/features.yaml или эквивалент). Нет файла → пусто."""
    p = Path(child_root) / registry_rel
    if not p.is_file():
        return {"features": []}
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if isinstance(data, dict) and isinstance(data.get("registry"), dict):
        return data["registry"]
    if isinstance(data, dict) and "features" in data:
        return {"features": data.get("features") or []}
    return {"features": []}


def run_child(child_root, registry_rel=DEFAULT_CHILD_REGISTRY, baseline_rel=DEFAULT_BASELINE_PATH,
              seed: bool = False, as_json: bool = False) -> int:
    """Собрать вход гейта В ДОЧКЕ и вынести вердикт с персистентным baseline (внешний путь enforcement).

    Это тот контур, который доставленный child-CI (`templates/ci/ai-ops-feature-coverage.yml`) гоняет
    в репозитории продукта: реестр фич дочки + поверхности, ИЗВЛЕЧЁННЫЕ из её кода (`extract_surfaces`,
    W2), + судья (W3) под персистентным baseline. Baseline читается из файла дочки; при `seed` его
    первый прогон засеивает и снижение переписывает (ратчет ВНИЗ) — рост verified-сирот блокирует
    (возврат 1). Так verified-orphan становится РЕАЛЬНО блокирующим на внешнем пути, а не на бумаге.
    """
    root = Path(child_root).resolve()
    baseline_path = root / baseline_rel
    registry = load_child_registry(root, registry_rel)
    surfaces = extract_surfaces(root)

    report = fc.build_coverage_report(registry, surfaces)
    current = len(fc.verified_orphans(report))
    stored = read_baseline(baseline_path)
    rec = fc.reconcile_baseline(current, stored)
    verdict = fc.coverage_verdict(report, rec["baseline"])
    warns = advisory_warnings(registry, surfaces)

    if seed and rec["changed"]:
        write_baseline(baseline_path, rec["baseline"])

    if as_json:
        print(json.dumps({"schema_version": 1, "kind": "feature-coverage-report",
                          "child_root": str(root), "report": report, "verdict": verdict,
                          "baseline": {"stored": stored, "current_verified_orphans": current,
                                       "reconciled": rec}},
                         ensure_ascii=False, indent=2))
        return 1 if rec["blocked"] else 0

    for w in warns:
        print(f"  [WARN] {w}")
    if rec["seeded"]:
        print(f"FEATURE-COVERAGE-SEED: засеян baseline verified-сирот = {rec['baseline']} "
              f"(первый прогон — приняты как деды, не блокируют).")
        return 0
    if rec["blocked"]:
        print(f"FEATURE-COVERAGE-FAIL: verified-сирот стало {current} — на {rec['regressed']} больше "
              f"принятого baseline={stored}. Новая незадокументированная verified-поверхность:")
        for o in fc.verified_orphans(report):
            print(f"  [FAIL] {o['surface'].get('ref')}")
        print("Заведите фичу в реестре или свяжите поверхность — молча растить охват нельзя.")
        return 1
    moved = f" (baseline опущен {stored} -> {rec['baseline']})" if rec["changed"] else ""
    print(f"FEATURE-COVERAGE-OK: покрыто {len(report['covered'])} поверхностей, verified-охват "
          f"{report['coverage_pct_verified']}%; verified-сирот {current} в пределах baseline"
          f"{moved}; предупреждений {len(warns)} (не блокируют).")
    return 0


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


def _opt(argv: list[str], name: str, default=None):
    """Достать значение опции `--name value` или `--name=value`; нет — default."""
    for i, a in enumerate(argv):
        if a == name and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return default


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in argv

    # ── Режим ДОЧКИ: собрать вход из её кода и вынести вердикт под персистентным baseline (W4). ──
    child_root = _opt(argv, "--child-root")
    if child_root is not None:
        return run_child(
            child_root,
            registry_rel=_opt(argv, "--registry", DEFAULT_CHILD_REGISTRY),
            baseline_rel=_opt(argv, "--baseline", DEFAULT_BASELINE_PATH),
            seed="--seed" in argv,
            as_json=as_json,
        )

    # ── Режим готового входа: coverage-input.yaml (реестр+поверхности уже собраны). ──
    opt_names = {"--json", "--seed", "--child-root", "--registry", "--baseline"}
    args, skip = [], False
    for i, a in enumerate(argv):
        if skip:
            skip = False
            continue
        if a in opt_names:
            skip = a in {"--child-root", "--registry", "--baseline"}
            continue
        if a.startswith("--"):
            continue
        args.append(a)
    if not args:
        print("охват фич: нет входных данных (реестр+поверхности дочки) — нечего проверять "
              "(это не ошибка).")
        return 0
    return run(Path(args[0]).resolve(), as_json=as_json)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
