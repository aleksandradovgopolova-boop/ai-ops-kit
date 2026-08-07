"""Селфтест regression_evidence, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from regression_evidence import (  # noqa: F401 — имена, которые использует тело
    Path,
    _git,
    classify_changed,
    gate_evidence,
    is_test_path,
    prove,
    sys,
)


@pytest.mark.slow
def test_regression_evidence_selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    # --- классификация путей ---
    expect("тесты распознаются по каталогу и по имени",
           is_test_path("tests/test_a.py") and is_test_path("src/a.test.ts")
           and is_test_path("pkg/__tests__/b.spec.ts") and is_test_path("x/foo_test.go"))
    expect("обычный код тестом не считается",
           not is_test_path("src/parse.ts") and not is_test_path("tools/run.py"))
    sp = classify_changed(["src/a.ts", "src/a.test.ts", "README.md", "config/app.yaml"])
    expect("classify_changed делит на тесты, документацию и код",
           sp["tests"] == ["src/a.test.ts"] and sp["docs"] == ["README.md"]
           and sp["code"] == ["src/a.ts", "config/app.yaml"])

    # --- ветки без прогона ---
    expect("только документация -> not_applicable",
           prove(".", "a", "b", {}, ["docs/x.md", "README.md"])["status"] == "not_applicable")
    expect("конфиг считается кодом (поведение менять умеет)",
           prove(".", "a", "b", {}, ["config/app.yaml"])["status"] == "not_proven")
    r_nt = prove(".", "a", "b", {}, ["src/a.ts"])
    expect("код без теста -> not_proven с причиной",
           r_nt["status"] == "not_proven" and "ничем не подтверждено" in r_nt["reason"])
    r_nc = prove(".", "a", "b", {"stacks": [{"commands": {}}]}, ["src/a.ts", "src/a.test.ts"])
    expect("нет команды тестов -> unverifiable (не «доказано»)",
           r_nc["status"] == "unverifiable")

    # --- реальный git: тест падает на базе -> proven ---
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for a in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
            _git(root, *a)
        (root / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
        # на базе ОБЯЗАН быть живой набор тестов: иначе проверка «набор отрабатывает сам по себе»
        # честно скажет unverifiable, и это правильно — доказывать не от чего
        (root / "test_existing.py").write_text("def test_existing():\n    assert True\n", encoding="utf-8")
        _git(root, "add", "-A"); _git(root, "commit", "-qm", "база с ошибкой")
        base = _git(root, "rev-parse", "HEAD")[1]
        (root / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        (root / "test_calc.py").write_text(
            "from calc import add\n\ndef test_add():\n    assert add(2, 2) == 4\n", encoding="utf-8")
        _git(root, "add", "-A"); _git(root, "commit", "-qm", "фикс + тест")
        head = _git(root, "rev-parse", "HEAD")[1]
        prof = {"stacks": [{"commands": {"test": f"{sys.executable} -m pytest -q"}}]}
        pr = prove(root, base, head, prof, ["calc.py", "test_calc.py"])
        expect("тест падает на базе -> proven", pr["status"] == "proven")
        expect("proven даёт pass гейта", gate_evidence(pr)["status"] == "pass")

        # тест, который проходит и на базе, ничего не доказывает
        (root / "test_noop.py").write_text("def test_noop():\n    assert True\n", encoding="utf-8")
        _git(root, "add", "-A"); _git(root, "commit", "-qm", "пустой тест")
        head2 = _git(root, "rev-parse", "HEAD")[1]
        prof2 = {"stacks": [{"commands": {"test": f"{sys.executable} -m pytest -q"}}]}
        pr2 = prove(root, base, head2, prof2, ["calc.py", "test_noop.py"])
        expect("тест проходит на базе -> not_proven", pr2["status"] == "not_proven")
        ge = gate_evidence(pr2)
        expect("not_proven блокирует и подсказывает выход",
               ge["status"] == "fail" and any("behavior_unchanged" in b for b in ge["blockers"]))
        ge2 = gate_evidence(pr2, behavior_unchanged="чистый рефакторинг импортов")
        expect("объявление закрывает гейт, но ГРОМКО",
               ge2["status"] == "pass" and any("рефакторинг импортов" in w for w in ge2["warnings"]))

        # среда не готова (команды нет) -> unverifiable, а НЕ «доказано»
        prof_broken = {"stacks": [{"commands": {"test": "definitely-not-a-command-xyz"}}]}
        pr3 = prove(root, base, head, prof_broken, ["calc.py", "test_calc.py"])
        expect("набор не отрабатывает на базе -> unverifiable (не «доказано»)",
               pr3["status"] == "unverifiable" and "сам по себе" in pr3["reason"])
        expect("unverifiable не закрывает гейт", gate_evidence(pr3)["status"] == "fail")

    assert ok, "перенесённый селфтест regression_evidence: см. строки FAIL в выводе"
