"""Unit-тесты доказательства исправления (v3.30) — tools/regression_evidence.py + проводка.

Находка раунда C живой квалификации (ии-среда, 2026-08-06): на задачах T1/T2/T4 writer правил код,
тесты и ДО правки проходили, `implementation_verification` вставал зелёным — и доказательства того,
что починилось именно то, что чинили, не производилось нигде. Кит ловил только регрессии.

Доказательство: тест из коммита переносится на БАЗОВУЮ ревизию и обязан там упасть.

Три обязательных теста на capability (AGENTS.md):
  * positive     — тест, падающий на базе, даёт proven и закрывает гейт;
  * fail-closed  — тест, проходящий на базе, НЕ доказывает ничего; нет теста — not_proven;
                   нечем прогнать — unverifiable, а не «доказано»;
  * side-effect  — на реальном прогоне движка вердикт РЕАЛЬНО попадает в отчёт и в гейт.
"""
from __future__ import annotations

import subprocess
import sys

import pytest

import ai_ops_run
import regression_evidence as re_


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


def _repo_with_bug(root):
    """База с ошибкой (add вычитает), затем фикс + тест. -> (base_sha, head_sha)."""
    for a in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        _git(root, *a)
    (root / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    # живой набор тестов на базе — обязательное предусловие доказательства
    (root / "test_existing.py").write_text("def test_existing():\n    assert True\n", encoding="utf-8")
    _git(root, "add", "-A"); _git(root, "commit", "-qm", "база с ошибкой")
    base = _git(root, "rev-parse", "HEAD").stdout.strip()
    (root / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (root / "test_calc.py").write_text(
        "from calc import add\n\ndef test_add():\n    assert add(2, 2) == 4\n", encoding="utf-8")
    _git(root, "add", "-A"); _git(root, "commit", "-qm", "фикс + тест")
    return base, _git(root, "rev-parse", "HEAD").stdout.strip()


def _profile(target=""):
    """Команда прогоняет ВЕСЬ набор — как в реальном репозитории (`npm run test`, `pytest`)."""
    return {"stacks": [{"commands": {"test": f"{sys.executable} -m pytest -q {target}".strip()}}]}


# --------------------------------------------------- классификация путей ---
# Перенесено из монолитного test_regression_evidence_selftest (прополка): гранулярный файл не
# проверял чистые функции is_test_path/classify_changed, на которых стоит вся ветвящаяся логика prove.

@pytest.mark.unit
class TestPathClassification:

    def test_is_test_path_recognises_tests_by_dir_and_name(self):
        assert re_.is_test_path("tests/test_a.py")
        assert re_.is_test_path("src/a.test.ts")
        assert re_.is_test_path("pkg/__tests__/b.spec.ts")
        assert re_.is_test_path("x/foo_test.go")

    def test_is_test_path_rejects_ordinary_code(self):
        assert not re_.is_test_path("src/parse.ts")
        assert not re_.is_test_path("tools/run.py")

    def test_classify_changed_splits_tests_docs_code(self):
        sp = re_.classify_changed(["src/a.ts", "src/a.test.ts", "README.md", "config/app.yaml"])
        assert sp["tests"] == ["src/a.test.ts"]
        assert sp["docs"] == ["README.md"]
        assert sp["code"] == ["src/a.ts", "config/app.yaml"]


# ---------------------------------------------------------------- positive ---

@pytest.mark.unit
class TestProofOfFix:

    def test_test_failing_on_base_proves_the_fix(self, tmp_path):
        base, head = _repo_with_bug(tmp_path)
        proof = re_.prove(tmp_path, base, head, _profile(), ["calc.py", "test_calc.py"])
        assert proof["status"] == "proven", proof.get("reason")
        ids = [c["id"] for c in proof["checks"]]
        assert ids == ["suite_runs_on_base", "test_fails_on_base"], \
            "порядок проверок важен: сначала среда, потом вывод о падении"

    def test_proven_closes_the_gate(self, tmp_path):
        base, head = _repo_with_bug(tmp_path)
        ev = re_.gate_evidence(re_.prove(tmp_path, base, head, _profile(),
                                         ["calc.py", "test_calc.py"]))
        assert ev["status"] == "pass"
        assert "regression_proven" in ev["provided"]

    def test_docs_only_change_needs_no_proof(self):
        proof = re_.prove(".", "a", "b", {}, ["README.md", "docs/guide.md"])
        assert proof["status"] == "not_applicable"
        assert re_.gate_evidence(proof)["status"] == "pass"


# ------------------------------------------------------------- fail-closed ---

@pytest.mark.unit
class TestUnprovenIsNotAccepted:

    def test_test_passing_on_base_proves_nothing(self, tmp_path):
        """Тест, зелёный и без исправления, не покрывает то, что чинили (побочно — off-scope)."""
        base, _ = _repo_with_bug(tmp_path)
        (tmp_path / "test_noop.py").write_text("def test_noop():\n    assert True\n", encoding="utf-8")
        _git(tmp_path, "add", "-A"); _git(tmp_path, "commit", "-qm", "пустой тест")
        head = _git(tmp_path, "rev-parse", "HEAD").stdout.strip()

        proof = re_.prove(tmp_path, base, head, _profile(),
                          ["calc.py", "test_noop.py"])

        assert proof["status"] == "not_proven"
        assert re_.gate_evidence(proof)["status"] == "fail"

    def test_code_without_any_test_is_not_proven(self):
        proof = re_.prove(".", "a", "b", _profile(), ["src/parse.ts"])
        assert proof["status"] == "not_proven"
        assert "ничем не подтверждено" in proof["reason"]

    def test_missing_test_command_is_unverifiable_not_proven(self):
        """Нечем проверить — это не «доказано». Отсутствие проверки != пройденная проверка."""
        proof = re_.prove(".", "a", "b", {"stacks": [{"commands": {}}]},
                          ["src/a.ts", "src/a.test.ts"])
        assert proof["status"] == "unverifiable"
        assert re_.gate_evidence(proof)["status"] == "fail"

    def test_config_counts_as_code(self):
        """«Это же просто конфиг» — типовая обёртка непроверенной правки поведения."""
        assert re_.prove(".", "a", "b", _profile(), ["config/app.yaml"])["status"] == "not_proven"

    def test_broken_environment_is_unverifiable_not_proven(self, tmp_path):
        """Живая находка: во временном дереве не было node_modules, `npm run test` вернул 127
        «command not found», и это засчиталось за «тест падает на базе» — сфабрикованное
        доказательство. Теперь набор обязан отработать на базе САМ ПО СЕБЕ."""
        base, head = _repo_with_bug(tmp_path)
        broken = {"stacks": [{"commands": {"test": "definitely-not-a-command-xyz"}}]}

        proof = re_.prove(tmp_path, base, head, broken, ["calc.py", "test_calc.py"])

        assert proof["status"] == "unverifiable", proof.get("reason")
        assert "сам по себе" in proof["reason"]
        assert re_.gate_evidence(proof)["status"] == "fail"
        assert proof["checks"][0]["id"] == "suite_runs_on_base"

    def test_blocker_names_the_way_out(self):
        blockers = re_.gate_evidence({"status": "not_proven", "reason": "нет теста"})["blockers"]
        assert any("behavior_unchanged" in b for b in blockers), \
            "гейт блокирует, но не говорит, как закрыть законный рефакторинг"


@pytest.mark.unit
class TestRefactorExemption:

    def test_declaration_closes_the_gate_loudly(self):
        ev = re_.gate_evidence({"status": "not_proven", "reason": "нет теста"},
                               behavior_unchanged="переименование без смены поведения")
        assert ev["status"] == "pass"
        assert any("переименование" in w for w in ev["warnings"]), \
            "объявление закрыло гейт молча — обход перестал быть видимым"

    def test_empty_declaration_is_not_a_declaration(self):
        assert re_.gate_evidence({"status": "not_proven"}, behavior_unchanged="")["status"] == "fail"
        assert re_.gate_evidence({"status": "not_proven"}, behavior_unchanged=None)["status"] == "fail"


# -------------------------------------------------------- side-effect proof ---

@pytest.mark.unit
def test_verdict_really_reaches_the_run_report(tmp_path, monkeypatch):
    """Прогон движка: доказательство лежит в отчёте, а не только внутри гейта."""
    monkeypatch.setenv("AI_OPS_PROVIDER_AUTORESOLVE", "0")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\n\n[tool.pytest.ini_options]\naddopts = '-q'\n", encoding="utf-8")
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_existing.py").write_text(
        "def test_existing():\n    assert True\n", encoding="utf-8")
    for a in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"],
              ["add", "-A"], ["commit", "-qm", "база"]):
        _git(tmp_path, *a)

    script = iter([
        {"op": "write", "path": "calc.py", "content": "def add(a, b):\n    return a + b\n"},
        {"op": "write", "path": "tests/test_calc.py",
         "content": "import sys\nsys.path.insert(0, '.')\nfrom calc import add\n\n"
                    "def test_add():\n    assert add(2, 2) == 4\n"},
        {"done": True, "summary": "фикс + тест"},
    ])
    rep = ai_ops_run.run("починить сложение",
                         {"task_type": "QUICK", "size": "small", "risk": "low",
                          "affected_areas": ["core"]},
                         tmp_path, provider_name="mock", engine="pipeline", execute=True,
                         proposer=lambda c: next(script))

    assert (rep.get("regression") or {}).get("status") == "proven", rep.get("regression")
    assert "regression_test_evidence" not in ((rep.get("gates") or {}).get("unmet") or [])
