#!/usr/bin/env python3
"""Stack-aware evidence collector (v2.44, Execution Engine — детерминированный сбор evidence).

Замыкает Project Detector -> gate. RepositoryProfile (tools/project_detector.py) знает команды
build/lint/typecheck/test конкретного репо; этот коллектор ИСПОЛНЯЕТ их через Tool Broker
(уровень execution) и превращает результат в структурный evidence для гейта
`implementation_verification` — ровно по его evidence_schema (build/lint/typecheck/tests с
command/exit_code/revision). Никакого LLM: вердикт = exit_code реальной команды.

Инвариант честности:
  - в `provided` попадают ТОЛЬКО флаги проверок, которые реально запущены и прошли (exit 0);
  - команда не определена в профиле (None) -> проверка `not_run`, флаг НЕ выдаётся (гейт честно
    останется невыполненным, пока человек не задаст команду) — коллектор не фабрикует pass;
  - исполнение идёт исключительно через tool_broker.execute (policy.decide первым): деструктивные
    команды в профиле будут отклонены Policy, а не выполнены.

Использование:
  evidence_collector.py collect [root] [--policy-level execution] [--json]
      -> детектит профиль, гоняет команды, печатает {collection, gate_evidence}
  evidence_collector.py --selftest
"""

import argparse
import json
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
for _p in (PKG / "tools",):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import tool_broker            # noqa: E402
import project_detector       # noqa: E402

# проверка -> (флаг required_evidence, ключ в evidence_schema гейта)
CHECK_MAP = {
    "build":     ("build_passed",     "build"),
    "lint":      ("lint_passed",      "lint"),
    "typecheck": ("typecheck_passed", "typecheck"),
    "test":      ("tests_passed",     "tests"),
}
CHECK_ORDER = ["build", "lint", "typecheck", "test"]


def _commands_by_check(profile):
    """Собрать {check: [(language, command), ...]} по всем стекам профиля (None пропускаем)."""
    out = {c: [] for c in CHECK_ORDER}
    for stack in profile.get("stacks", []) or []:
        lang = stack.get("language", "?")
        for check, cmd in (stack.get("commands") or {}).items():
            if check in out and cmd:
                out[check].append((lang, cmd))
    return out


def collect(profile, root, policy):
    """Прогнать команды профиля через Tool Broker и собрать evidence для implementation_verification."""
    root = Path(root)
    by_check = _commands_by_check(profile)
    revision = tool_broker._revision(root)
    checks_report, schema_evidence, provided, blockers = {}, {}, [], []

    for check in CHECK_ORDER:
        flag, schema_key = CHECK_MAP[check]
        cmds = by_check[check]
        if not cmds:
            checks_report[check] = {"status": "not_run",
                                    "reason": "команда не определена в профиле (undetermined)"}
            continue
        runs, all_ok, any_denied = [], True, False
        for lang, cmd in cmds:
            ev = tool_broker.execute({"op": "shell", "command": cmd}, root, policy)
            if not ev["allowed"]:
                any_denied = True; all_ok = False
                runs.append({"language": lang, "command": cmd, "denied": True, "reason": ev["reason"]})
                continue
            ok = ev.get("ok", False)
            all_ok = all_ok and ok
            runs.append({"language": lang, "command": cmd,
                         "exit_code": ev.get("exit_code"), "ok": ok,
                         "output_tail": ev.get("output_tail", "")})
        # honest (finding живого прогона): pytest exit 5 = «нет собранных тестов», это НЕ
        # проваленный тест. Такой прогон -> warn (no_tests): флаг tests_passed НЕ выдаём
        # (тестов не было), но и hard-fail не ставим (нечему было падать).
        no_tests = (check == "test" and not any_denied
                    and all(("pytest" in (r.get("command") or "") and r.get("exit_code") == 5)
                            for r in runs))
        if no_tests:
            checks_report[check] = {"status": "warn", "reason": "нет собранных тестов (pytest exit 5)",
                                    "runs": runs}
        else:
            status = "pass" if all_ok else "fail"
            checks_report[check] = {"status": status, "runs": runs}
        # структурный evidence по evidence_schema гейта (первый стек репрезентативен)
        first = runs[0]
        schema_evidence[schema_key] = {"command": first.get("command"),
                                       "exit_code": first.get("exit_code"),
                                       "revision": revision}
        if all_ok and not no_tests:
            provided.append(flag)
        elif not no_tests:
            reason = "отклонено policy" if any_denied else "команда завершилась с ненулевым кодом"
            blockers.append(f"{check}: {reason}")

    if revision:
        provided.append("tested_revision")

    # статус гейта: fail, если хоть одна запущенная проверка провалилась; иначе pass
    # (полнота required_evidence — на стороне gate_executor.evaluate_gate: чего нет в provided,
    #  то не закрыто; коллектор не выдаёт не-запущенное за выполненное).
    gate_status = "fail" if blockers else "pass"
    # evidence-вход гейта (schemas/gate-evidence.schema.json): ревизия идёт строкой в evidence,
    # а факт «ревизия зафиксирована» — флагом tested_revision в provided (required_evidence).
    ev_strings = [f"{k}:exit={v.get('exit_code')}" for k, v in schema_evidence.items()]
    if revision:
        ev_strings.append(f"tested_revision:{revision}")
    gate_evidence = {
        "implementation_verification": {
            "status": gate_status,
            "provided": provided,
            "evidence": ev_strings,
        }
    }
    if blockers:
        gate_evidence["implementation_verification"]["blockers"] = blockers

    return {
        "schema_version": 1, "kind": "evidence-collection",
        "revision": revision, "checks": checks_report,
        "schema_evidence": schema_evidence,
        "gate_evidence": gate_evidence,
    }


def selftest():
    import tempfile
    import subprocess
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        subprocess.run(["git", "-C", td, "init", "-q"])
        subprocess.run(["git", "-C", td, "config", "user.email", "t@t"])
        subprocess.run(["git", "-C", td, "config", "user.name", "t"])
        (root / "f").write_text("x", encoding="utf-8")
        subprocess.run(["git", "-C", td, "add", "-A"])
        subprocess.run(["git", "-C", td, "commit", "-q", "-m", "i"])
        pol = tool_broker.Policy(level="execution")

        # профиль, где всё проходит, а typecheck не определён (None -> not_run)
        prof_ok = {"stacks": [{"language": "demo", "commands": {
            "build": "true", "lint": "true", "typecheck": None, "test": "python3 -c \"pass\""}}]}
        r = collect(prof_ok, root, pol)
        ge = r["gate_evidence"]["implementation_verification"]
        expect("всё запущенное прошло -> gate pass", ge["status"] == "pass")
        expect("provided содержит прошедшие флаги", {"build_passed", "lint_passed", "tests_passed"} <= set(ge["provided"]))
        expect("tested_revision-флаг в provided, ревизия непуста",
               "tested_revision" in ge["provided"] and r["revision"])
        expect("typecheck без команды -> not_run (флаг НЕ выдан)",
               r["checks"]["typecheck"]["status"] == "not_run"
               and "typecheck_passed" not in ge["provided"])
        expect("структурный evidence по schema (command+exit_code+revision)",
               r["schema_evidence"]["build"]["exit_code"] == 0
               and r["schema_evidence"]["build"]["command"] == "true"
               and r["schema_evidence"]["build"]["revision"] == r["revision"])

        # провал команды -> gate fail + blocker, флаг не выдан
        prof_fail = {"stacks": [{"language": "demo", "commands": {
            "build": "true", "lint": "false", "typecheck": None, "test": "true"}}]}
        r2 = collect(prof_fail, root, pol)
        ge2 = r2["gate_evidence"]["implementation_verification"]
        expect("падение команды -> gate fail", ge2["status"] == "fail")
        expect("провал lint -> нет lint_passed + есть blocker",
               "lint_passed" not in ge2["provided"]
               and any("lint" in b for b in ge2.get("blockers", [])))

        # evidence коллектора проходит форму gate-evidence (валидатор gate_executor)
        import gate_executor
        expect("gate_evidence валиден по схеме", gate_executor.validate_evidence(r["gate_evidence"]) == [])

        # деструктивная команда в профиле -> отклонена Policy, НЕ исполнена
        prof_destr = {"stacks": [{"language": "demo", "commands": {
            "build": "rm -rf /", "lint": None, "typecheck": None, "test": None}}]}
        r3 = collect(prof_destr, root, pol)
        expect("деструктивная команда отклонена Policy (не исполнена)",
               r3["checks"]["build"]["status"] == "fail"
               and any(run.get("denied") for run in r3["checks"]["build"]["runs"]))

        # интеграция с реальным детектором: python-репо -> команды выведены, коллектор гоняет
        (root / "pyproject.toml").write_text(
            "[tool.poetry]\nname='x'\n[tool.poetry.dependencies]\npytest='*'\n", encoding="utf-8")
        (root / "tests").mkdir()
        prof_detected = project_detector.detect(root)
        r4 = collect(prof_detected, root, pol)
        expect("detect->collect: test-проверка запущена (есть runs)",
               r4["checks"]["test"]["status"] in ("pass", "fail", "warn")
               and r4["checks"]["test"].get("runs"))

        # finding живого прогона: pytest exit 5 (нет тестов) -> warn, НЕ fail; tests_passed не выдан,
        # но и hard-fail нет (нечему падать). Команда содержит 'pytest' и возвращает 5.
        prof_notest = {"stacks": [{"language": "demo", "commands": {
            "build": "true", "lint": None, "typecheck": None,
            "test": "bash -c 'exit 5'  # pytest"}}]}
        r5 = collect(prof_notest, root, pol)
        ge5 = r5["gate_evidence"]["implementation_verification"]
        expect("нет тестов (pytest exit 5) -> warn, не fail",
               r5["checks"]["test"]["status"] == "warn")
        expect("нет тестов -> tests_passed НЕ выдан и НЕ hard-fail",
               "tests_passed" not in ge5["provided"]
               and not any("test" in b for b in ge5.get("blockers", [])))

    print("evidence_collector selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    ap = argparse.ArgumentParser(prog="evidence_collector.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("root", nargs="?", default=".")
    c.add_argument("--policy-level", default="execution")
    c.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "collect":
        profile = project_detector.detect(a.root)
        policy = tool_broker.Policy(level=a.policy_level)
        r = collect(profile, a.root, policy)
        if a.json:
            print(json.dumps(r, ensure_ascii=False, indent=2))
        else:
            import yaml
            print(yaml.safe_dump(r, allow_unicode=True, sort_keys=False))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
