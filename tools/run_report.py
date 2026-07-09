#!/usr/bin/env python3
"""Оценка прогона фичи (v2.2) — «хорошо это или плохо» одной командой.

Собирает по каталогу функции честный отчёт:
  1. валидность blueprint (validate_feature_blueprint);
  2. покрытие стадий: заполнено / draft / planned / declined (с причинами) / файла нет;
  3. скелеты-пустышки: артефакт помечен done/draft, но содержимое не менялось
     после генерации (.generation.json);
  4. сверка с knowledge graph: если у feature-узла есть ребро delivered-by (релиз),
     а current_stage раньше release — реальность обогнала blueprint;
  5. retrospective и memory: закрыт ли цикл уроков.

Вердикт: PROBLEM-находки -> exit 1 (процесс не пройден честно), WARN — сигналы
для внимания, OK — прогон чист по форме. Качество СОДЕРЖАНИЯ артефактов оценивают
ревьюеры (gates), не скрипт.

Использование:  run_report.py <feature-dir> [--graph <graph.yaml>] [--json]
                run_report.py --selftest
Требует pyyaml.
"""

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

import yaml

PKG = Path(__file__).resolve().parents[1]
STAGES = ["discovery", "definition", "ux", "architecture", "delivery",
          "analytics", "documentation", "release", "monitoring", "adoption", "retrospective"]

_spec = importlib.util.spec_from_file_location(
    "vfb", PKG / "validation" / "validate_feature_blueprint.py")
vfb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vfb)

_ga_spec = importlib.util.spec_from_file_location("ga", PKG / "tools" / "generate_artifacts.py")
ga = importlib.util.module_from_spec(_ga_spec)
_ga_spec.loader.exec_module(ga)

_ca_spec = importlib.util.spec_from_file_location(
    "vca", PKG / "validation" / "validate_cross_artifacts.py")
vca = importlib.util.module_from_spec(_ca_spec)
_ca_spec.loader.exec_module(vca)


def graph_findings(feature_dir: Path, graph_path: Path, current_stage: str):
    """Реальность vs blueprint: релиз в графе при ранней стадии blueprint."""
    findings = []
    try:
        g = yaml.safe_load(graph_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return [("WARN", f"knowledge graph не читается: {exc}")]
    nodes = {n["id"]: n for n in g.get("nodes") or [] if isinstance(n, dict) and n.get("id")}
    my_node = None
    for n in nodes.values():
        bp = n.get("blueprint")
        if n.get("type") == "feature" and bp:
            if (graph_path.parent / bp).resolve() == (feature_dir / "blueprint.yaml").resolve():
                my_node = n
                break
    if my_node is None:
        return [("WARN", "feature не привязана к knowledge graph (нет узла с blueprint на этот каталог)")]
    released = any(e.get("from") == my_node["id"] and e.get("type") == "delivered-by"
                   for e in g.get("edges") or [])
    if released and current_stage in STAGES and STAGES.index(current_stage) < STAGES.index("release"):
        findings.append(("PROBLEM",
                         f"реальность обогнала blueprint: в графе фича delivered-by (выпущена), "
                         f"а current_stage='{current_stage}' — стадии между "
                         f"{current_stage} и release не заполнены и не declined"))
    return findings


def build_report(feature_dir: Path, graph_path: Path | None):
    report = {"feature_dir": str(feature_dir), "blueprint_errors": [],
              "stages": {}, "findings": [], "verdict": None}

    report["blueprint_errors"] = vfb.validate_dir(feature_dir)
    for e in report["blueprint_errors"]:
        report["findings"].append(("PROBLEM", f"blueprint: {e}"))

    bp = {}
    bp_path = feature_dir / "blueprint.yaml"
    if bp_path.exists():
        try:
            bp = yaml.safe_load(bp_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            bp = {}
    current = ((bp.get("feature") or {}).get("current_stage")) or "?"
    report["current_stage"] = current
    gen = ga.load_generation(feature_dir).get("artifacts", {})

    filled = declined = missing = skeletons = total = 0
    for st in STAGES:
        entries = (bp.get("artifacts") or {}).get(st) or []
        row = {"filled": 0, "draft_or_done_untouched": 0, "planned": 0, "declined": 0, "missing": 0}
        for e in entries:
            if not isinstance(e, dict) or not e.get("path"):
                continue
            total += 1
            status = e.get("status", "planned")
            path = feature_dir / e["path"]
            if status == "declined":
                declined += 1
                row["declined"] += 1
                continue
            if not path.exists():
                missing += 1
                row["missing" if status != "planned" else "planned"] += 1
                if status in ("done", "draft"):
                    report["findings"].append(
                        ("PROBLEM", f"{st}/{e['path']}: status={status}, но файла нет"))
                continue
            rec = gen.get(e["path"])
            untouched = bool(rec) and ga.sha(path.read_bytes()) == rec.get("generated_sha")
            if untouched:
                skeletons += 1
                row["draft_or_done_untouched" if status in ("done", "draft") else "planned"] += 1
                if status in ("done", "draft"):
                    report["findings"].append(
                        ("PROBLEM", f"{st}/{e['path']}: помечен {status}, но это незаполненный скелет"))
            else:
                filled += 1
                row["filled"] += 1
        report["stages"][st] = row

    report["coverage"] = {"total": total, "filled": filled, "declined": declined,
                          "skeletons": skeletons, "missing_or_planned": total - filled - declined - skeletons}

    if graph_path and graph_path.exists():
        report["findings"] += graph_findings(feature_dir, graph_path, current)

    # кросс-артефактная консистентность (v2.3): tracking-plan <-> dashboard-spec
    ca_problems, ca_warns, _skip = vca.check_feature(feature_dir)
    report["findings"] += [("PROBLEM", p) for p in ca_problems]
    report["findings"] += [("WARN", w) for w in ca_warns]

    retro = (bp.get("artifacts") or {}).get("retrospective") or []
    retro_done = any(isinstance(e, dict) and e.get("status") in ("done", "draft")
                     and (feature_dir / e.get("path", "")).exists() for e in retro)
    if not retro_done:
        report["findings"].append(("WARN", "retrospective не заполнена — уроки прогона не зафиксированы"))

    problems = [f for lvl, f in report["findings"] if lvl == "PROBLEM"]
    report["verdict"] = "PROBLEM" if problems else ("WARN" if report["findings"] else "OK")
    return report


def print_report(r):
    print(f"=== Оценка прогона: {Path(r['feature_dir']).name} "
          f"(current_stage={r['current_stage']}) ===")
    c = r["coverage"]
    print(f"покрытие артефактов: {c['filled']} заполнено, {c['declined']} declined (осознанно), "
          f"{c['skeletons']} скелетов, {c['missing_or_planned']} не начато — из {c['total']}")
    reached = STAGES[:STAGES.index(r["current_stage"]) + 1] if r["current_stage"] in STAGES else []
    for st in STAGES:
        row = r["stages"].get(st, {})
        if not any(row.values()):
            continue
        mark = "*" if st in reached else " "
        print(f"  {mark} {st:14} заполнено={row['filled']} declined={row['declined']} "
              f"planned={row['planned']} проблемных={row['draft_or_done_untouched'] + row['missing']}")
    if r["findings"]:
        print("находки:")
        for lvl, f in r["findings"]:
            print(f"  [{lvl}] {f}")
    print(f"ВЕРДИКТ: {r['verdict']}"
          + ("" if r["verdict"] == "OK" else " — детали выше; качество содержания оценивают ревьюеры (gates)"))


def selftest():
    ok = True

    def expect(name, got, want):
        nonlocal ok
        good = got == want
        ok = ok and good
        print(f"{'PASS' if good else 'FAIL'} {name}" + ("" if good else f" (got {got})"))

    with tempfile.TemporaryDirectory() as td:
        feats = Path(td) / "features"
        ga.cmd_new(feats, "demo-r", "Demo R")
        fdir = feats / "demo-r"
        ga.cmd_scaffold(fdir, "discovery")
        # заполняем discovery по-настоящему
        for f in ("problem-statement", "hypotheses"):
            p = fdir / "discovery" / f"{f}.md"
            p.write_text(p.read_text(encoding="utf-8") + "\nсодержание\n", encoding="utf-8")
        r = build_report(fdir, None)
        expect("честный discovery -> без PROBLEM", r["verdict"] in ("OK", "WARN"), True)
        expect("retro не заполнена -> WARN присутствует",
               any("retrospective" in f for _, f in r["findings"]), True)

        # артефакт помечен done, но остался скелетом
        bp = yaml.safe_load((fdir / "blueprint.yaml").read_text(encoding="utf-8"))
        ga.cmd_scaffold(fdir, "definition")
        for e in bp["artifacts"]["definition"]:
            e["status"] = "done"
        bp["feature"]["current_stage"] = "definition"
        (fdir / "blueprint.yaml").write_text(yaml.safe_dump(bp, allow_unicode=True, sort_keys=False),
                                             encoding="utf-8")
        r = build_report(fdir, None)
        expect("done-скелет -> PROBLEM", r["verdict"], "PROBLEM")

        # реальность обогнала blueprint (граф говорит released)
        graph = Path(td) / "knowledge" / "graph.yaml"
        graph.parent.mkdir()
        graph.write_text(yaml.safe_dump({
            "schema_version": 1, "kind": "knowledge-graph",
            "nodes": [{"id": "f1", "type": "feature",
                       "blueprint": "../features/demo-r/blueprint.yaml"},
                      {"id": "r1", "type": "release"}],
            "edges": [{"from": "f1", "type": "delivered-by", "to": "r1"}],
        }, allow_unicode=True), encoding="utf-8")
        r = build_report(fdir, graph)
        expect("delivered-by при ранней стадии -> PROBLEM 'реальность обогнала'",
               any("обогнала" in f for _, f in r["findings"]), True)
    print("run-report selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    if not argv:
        print(__doc__)
        return 1
    feature_dir = Path(argv[0]).resolve()
    graph = Path(argv[argv.index("--graph") + 1]).resolve() if "--graph" in argv else None
    r = build_report(feature_dir, graph)
    if "--json" in argv:
        print(json.dumps({**r, "findings": [list(f) for f in r["findings"]]},
                         ensure_ascii=False, indent=2))
    else:
        print_report(r)
    return 1 if r["verdict"] == "PROBLEM" else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
