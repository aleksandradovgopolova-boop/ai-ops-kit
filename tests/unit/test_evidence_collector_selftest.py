"""Селфтест evidence_collector, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from evidence_collector import (  # noqa: F401 — имена, которые использует тело
    Path,
    collect,
    project_detector,
    tool_broker,
)


@pytest.mark.slow
def test_evidence_collector_selftest():
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

        # adversarial-review: полиглот — реальный проходящий тест + pytest exit5 рядом ->
        # tests_passed ВЫДАН (реальный прогон прошёл), а pytest-exit5 не роняет весь check.
        prof_poly = {"stacks": [
            {"language": "node", "commands": {"build": None, "lint": None, "typecheck": None, "test": "true"}},
            {"language": "python", "commands": {"build": None, "lint": None, "typecheck": None,
                                                "test": "bash -c 'exit 5'  # pytest"}}]}
        r6 = collect(prof_poly, root, pol)
        ge6 = r6["gate_evidence"]["implementation_verification"]
        expect("полиглот: реальный тест прошёл рядом с pytest-exit5 -> tests_passed выдан, check pass",
               "tests_passed" in ge6["provided"] and r6["checks"]["test"]["status"] == "pass")

        # v3.26.0: Progressive Verification — changed_files -> targeted test command
        # Создаём репо с двумя модулями и тестами
        (root / "module_a.py").write_text("def func_a(): return 1\n", encoding="utf-8")
        (root / "module_b.py").write_text("def func_b(): return 2\n", encoding="utf-8")
        (root / "tests").mkdir(exist_ok=True)
        (root / "tests" / "test_a.py").write_text("import module_a\ndef test_a(): assert module_a.func_a() == 1\n", encoding="utf-8")
        (root / "tests" / "test_b.py").write_text("import module_b\ndef test_b(): assert module_b.func_b() == 2\n", encoding="utf-8")
        prof_multi = {"stacks": [{"language": "python", "commands": {
            "build": None, "lint": None, "typecheck": None,
            "test": "python3 -m pytest tests/"}}]}
        # Без changed_files — полный прогон
        r7 = collect(prof_multi, root, pol)
        expect("без changed_files: verification=None", r7.get("verification") is None)
        # С changed_files — targeted прогон
        r8 = collect(prof_multi, root, pol, changed_files=["module_a.py"])
        v8 = r8.get("verification")
        expect("с changed_files: verification info заполнен", v8 is not None)
        expect("с changed_files: tier=affected (один файл)", v8.get("tier") == "affected")
        expect("с changed_files: test_a.py в affected_tests",
               "tests/test_a.py" in (v8.get("affected_tests") or []))

    assert ok, "перенесённый селфтест evidence_collector: см. строки FAIL в выводе"
