"""Селфтест run_report, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from run_report import (  # noqa: F401 — имена, которые использует тело
    Path,
    build_report,
    ga,
    json,
    record_report,
    tempfile,
    yaml,
)


@pytest.mark.slow
def test_run_report_selftest():
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
        r = build_report(fdir, None)
        expect("незаполненные скелеты достигнутой стадии -> PROBLEM", r["verdict"], "PROBLEM")
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
        # запись истории: два среза -> две JSONL-строки
        hist = Path(td) / "hist"
        record_report(r, fdir, hist)
        record_report(r, fdir, hist)
        lines = (hist / "demo-r.jsonl").read_text(encoding="utf-8").strip().split("\n")
        expect("история: 2 записи JSONL", len(lines), 2)
        expect("запись содержит verdict", "verdict" in json.loads(lines[0]), True)

    assert ok, "перенесённый селфтест run_report: см. строки FAIL в выводе"
