"""Базовая линия профиля стиля (#1183): существующее заморожено, рост краснеет, линия ходит вниз.

Три теста на capability (AGENTS.md):
  * positive     — без изменений -> зелено; исправленное -> зелено и линия ужимается;
  * fail-closed  — рост на ключе или новый файл с находкой -> красно; инструмента нет или линия не
                   заморожена -> «не проверено» (код 2), а не зелёное;
  * side-effect  — файл линии пишется на диск и ужимается там же; повторная заморозка его не трогает
                   (рост не «отмывается» пересборкой), осознанная (`force`) — перезаписывает.
"""
from __future__ import annotations

import json
import shutil

import pytest

from ai_ops_kit.checks import lint_baseline, lint_profile
from ai_ops_kit.cli import lint_profile_cli

pytestmark = pytest.mark.unit

RUFF = {"tool": "ruff", "config": ".ai/project/lint/ruff.toml", "rules": ["PLC2401", "PLC2403", "N"]}
ESLINT = {"tool": "eslint", "config": "eslint.ai-ops.config.mjs",
          "suppressions": ".ai/project/lint/eslint-suppressions.json", "rule_prefix": "ai-ops/",
          "rules": ["ai-ops/id-match"]}


# ── Сравнение. ────────────────────────────────────────────────────────────────────────────────
def test_same_counts_pass_without_changes():
    cmp = lint_baseline.compare({"a.py": {"N806": 2}}, {"a.py": {"N806": 2}})
    assert cmp["grown"] == [] and cmp["shrunk"] == [] and cmp["tightened"] == {"a.py": {"N806": 2}}


def test_growth_on_a_key_fails_with_address():
    cmp = lint_baseline.compare({"a.py": {"N806": 1}}, {"a.py": {"N806": 2}},
                                [("a.py", "N806", 3), ("a.py", "N806", 9)])
    assert cmp["grown"] == [{"file": "a.py", "rule": "N806", "was": 1, "now": 2, "lines": [3, 9]}]


def test_new_file_with_a_finding_is_growth_from_zero():
    cmp = lint_baseline.compare({}, {"new.py": {"PLC2401": 1}})
    assert cmp["grown"][0]["was"] == 0 and cmp["tightened"] == {}


def test_shrink_passes_and_tightens_the_line():
    cmp = lint_baseline.compare({"a.py": {"N806": 3}, "b.py": {"N806": 1}}, {"a.py": {"N806": 1}})
    assert cmp["grown"] == []
    assert {s["file"] for s in cmp["shrunk"]} == {"a.py", "b.py"}
    assert cmp["tightened"] == {"a.py": {"N806": 1}}


def test_tightened_line_never_absorbs_growth_elsewhere():
    cmp = lint_baseline.compare({"a.py": {"N806": 3}, "b.py": {"N806": 1}},
                                {"a.py": {"N806": 1}, "b.py": {"N806": 5}})
    assert cmp["tightened"] == {"a.py": {"N806": 1}, "b.py": {"N806": 1}}


# ── Разбор вывода инструментов. ───────────────────────────────────────────────────────────────
def test_parse_ruff_keeps_only_profile_rules(tmp_path):
    out = json.dumps([
        {"code": "PLC2401", "filename": str(tmp_path / "a.py"), "location": {"row": 1}},
        {"code": "N802", "filename": str(tmp_path / "a.py"), "location": {"row": 3}},
        {"code": "F401", "filename": str(tmp_path / "a.py"), "location": {"row": 2}}])
    assert lint_baseline.parse_ruff(out, tmp_path, RUFF["rules"]) == [
        ("a.py", "PLC2401", 1), ("a.py", "N802", 3)]


def test_parse_eslint_splits_suppressed_from_new(tmp_path):
    out = json.dumps([{"filePath": str(tmp_path / "src/x.ts"),
                       "messages": [{"ruleId": "ai-ops/id-match", "line": 4},
                                    {"ruleId": "no-undef", "line": 1}],
                       "suppressedMessages": [{"ruleId": "ai-ops/id-match", "line": 2}]}])
    found, supp = lint_baseline.parse_eslint(out, tmp_path)
    assert found == [("src/x.ts", "ai-ops/id-match", 4)]
    assert supp == {("src/x.ts", "ai-ops/id-match"): 1}


def test_parse_golangci_ast_grep_and_import_linter(tmp_path):
    go = json.dumps({"Issues": [{"FromLinter": "asciicheck", "Pos": {"Filename": "a.go", "Line": 2}},
                                {"FromLinter": "errcheck", "Pos": {"Filename": "a.go", "Line": 3}}]})
    assert lint_baseline.parse_golangci(go, tmp_path, ["asciicheck"]) == [("a.go", "asciicheck", 2)]
    ag = json.dumps([{"file": "m.rs", "ruleId": "ai-ops-latin-identifiers-rust",
                      "range": {"start": {"line": 0}}}])
    assert lint_baseline.parse_ast_grep(ag, tmp_path) == [("m.rs", "ai-ops-latin-identifiers-rust", 1)]
    il = ("app.domain is not allowed to import app.api:\n\n"
          "-   app.domain.x -> app.api.y (l.3)\n\nContracts: 0 kept, 1 broken.\n")
    assert lint_baseline.parse_import_linter(il) == [
        ("app.domain.x", "import-linter:app.domain->app.api", 3)]


# ── Заморозка и проверка (инструмент подменён — логика линии настоящая). ─────────────────────
@pytest.fixture
def fake_tool(monkeypatch):
    """Подделка запуска инструмента: логика линии настоящая, процесса нет. Та же подмена — в команде."""
    state = {"found": [], "calls": []}

    def measure(root, spec, extra=()):
        state["calls"].append(list(extra))
        return (None, {}, "ruff не найден — проверить нечем") if state.get("missing") \
            else (list(state["found"]), {}, None)
    state["measure"] = measure
    monkeypatch.setattr(lint_profile_cli, "measure", measure)
    return state


def test_freeze_writes_the_line_to_disk(tmp_path, fake_tool):
    fake_tool["found"] = [("a.py", "PLC2401", 1), ("a.py", "PLC2401", 2)]
    res = lint_baseline.freeze(tmp_path, [RUFF], fake_tool["measure"])
    assert res[0]["status"] == "frozen" and res[0]["frozen"] == 2
    data = json.loads((tmp_path / lint_baseline.BASELINE_REL).read_text())
    assert data["tools"]["ruff"] == {"a.py": {"PLC2401": {"count": 2}}}


def test_second_freeze_keeps_the_line_so_growth_cannot_be_laundered(tmp_path, fake_tool):
    fake_tool["found"] = [("a.py", "PLC2401", 1)]
    lint_baseline.freeze(tmp_path, [RUFF], fake_tool["measure"])
    fake_tool["found"] = [("a.py", "PLC2401", 1), ("b.py", "PLC2401", 1)]
    assert lint_baseline.freeze(tmp_path, [RUFF], fake_tool["measure"])[0]["status"] == "kept"
    assert lint_baseline.check(tmp_path, [RUFF], fake_tool["measure"])["status"] == lint_baseline.GREW


def test_forced_freeze_rewrites_the_line(tmp_path, fake_tool):
    fake_tool["found"] = [("a.py", "PLC2401", 1)]
    lint_baseline.freeze(tmp_path, [RUFF], fake_tool["measure"])
    fake_tool["found"] = []
    lint_baseline.freeze(tmp_path, [RUFF], fake_tool["measure"], force=True)
    assert json.loads((tmp_path / lint_baseline.BASELINE_REL).read_text())["tools"]["ruff"] == {}


def test_check_tighten_lowers_the_line_on_disk(tmp_path, fake_tool):
    fake_tool["found"] = [("a.py", "N806", 1), ("a.py", "N806", 2)]
    lint_baseline.freeze(tmp_path, [RUFF], fake_tool["measure"])
    fake_tool["found"] = [("a.py", "N806", 1)]
    res = lint_baseline.check(tmp_path, [RUFF], fake_tool["measure"], tighten=True)
    assert res["status"] == lint_baseline.OK and res["tools"][0]["tightened_applied"]
    assert lint_baseline.load(tmp_path)["tools"]["ruff"] == {"a.py": {"N806": {"count": 1}}}


def test_check_without_frozen_line_is_not_checked(tmp_path, fake_tool):
    assert lint_baseline.check(tmp_path, [RUFF], fake_tool["measure"])["status"] == lint_baseline.NOT_CHECKED


def test_missing_tool_is_not_checked_not_green(tmp_path, fake_tool):
    fake_tool["missing"] = True
    assert lint_baseline.freeze(tmp_path, [RUFF], fake_tool["measure"])[0]["status"] == lint_baseline.NOT_CHECKED
    assert not (tmp_path / lint_baseline.BASELINE_REL).exists()


def test_native_eslint_counts_suppressed_plus_new_and_prunes(tmp_path, monkeypatch):
    supp = tmp_path / ESLINT["suppressions"]
    supp.parent.mkdir(parents=True)
    supp.write_text(json.dumps({"src/x.ts": {"ai-ops/id-match": {"count": 3}}}))
    monkeypatch.setattr(lint_baseline, "eslint_version", lambda root: (10, 0))
    calls = []

    def measure(root, spec, extra=()):
        calls.append(list(extra))
        return [], {("src/x.ts", "ai-ops/id-match"): 2}, None
    res = lint_baseline.check(tmp_path, [ESLINT], measure, tighten=True)
    row = res["tools"][0]
    assert row["native"] and row["shrunk"] == [
        {"file": "src/x.ts", "rule": "ai-ops/id-match", "was": 3, "now": 2}]
    assert "--pass-on-unpruned-suppressions" in calls[0] and "--prune-suppressions" in calls[1]


def test_native_eslint_growth_over_the_counter_fails(tmp_path, monkeypatch):
    supp = tmp_path / ESLINT["suppressions"]
    supp.parent.mkdir(parents=True)
    supp.write_text(json.dumps({"src/x.ts": {"ai-ops/id-match": {"count": 1}}}))
    monkeypatch.setattr(lint_baseline, "eslint_version", lambda root: (10, 0))
    def grown(root, spec, extra=()):
        return [("src/x.ts", "ai-ops/id-match", 1), ("src/x.ts", "ai-ops/id-match", 7)], {}, None
    assert lint_baseline.check(tmp_path, [ESLINT], grown)["status"] == lint_baseline.GREW


def test_old_eslint_falls_back_to_the_kit_line(tmp_path, monkeypatch):
    monkeypatch.setattr(lint_baseline, "eslint_version", lambda root: (8, 57))
    lint_baseline.freeze(tmp_path, [ESLINT], lambda root, spec, extra=(): (
        [("src/x.ts", "ai-ops/id-match", 1)], {}, None))
    assert "eslint" in lint_baseline.load(tmp_path)["tools"]


# ── Настоящий Ruff (если стоит): заморозка -> рост красный -> исправление зелёное. ────────────
def test_real_ruff_ratchet_end_to_end(tmp_path):
    if not shutil.which("ruff"):
        pytest.skip("ruff не установлен в этом окружении")
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\n")
    old = "имя = 1\n"                       # имя = 1
    (tmp_path / "a.py").write_text(old)
    prof = lint_profile.render(tmp_path, {})
    lint_profile.apply(tmp_path, prof)
    run = lint_profile_cli.measure
    assert lint_baseline.freeze(tmp_path, prof["tools"], run)[0]["frozen"] == 1
    assert lint_baseline.check(tmp_path, prof["tools"], run)["status"] == lint_baseline.OK
    (tmp_path / "b.py").write_text("новое = 2\n")   # новое = 2
    assert lint_baseline.check(tmp_path, prof["tools"], run)["status"] == lint_baseline.GREW
    (tmp_path / "b.py").unlink()
    (tmp_path / "a.py").write_text("name = 1\n")
    res = lint_baseline.check(tmp_path, prof["tools"], run, tighten=True)
    assert res["status"] == lint_baseline.OK and lint_baseline.load(tmp_path)["tools"]["ruff"] == {}


# ── Команда. ──────────────────────────────────────────────────────────────────────────────────
def _py(tmp_path):
    (tmp_path / "pyproject.toml").write_text("")
    return tmp_path


def test_cli_dry_run_writes_nothing(tmp_path, capsys):
    repo = _py(tmp_path)
    assert lint_profile_cli.run_lint_profile(repo) == 0
    assert not (repo / ".ai").exists()
    assert "Пока ничего не записано" in capsys.readouterr().out


def test_cli_unknown_verb_is_refused(tmp_path, capsys):
    assert lint_profile_cli.run_lint_profile(_py(tmp_path), verb="fix") == 2


def test_cli_check_before_apply_is_not_checked(tmp_path, fake_tool, capsys):
    assert lint_profile_cli.run_lint_profile(_py(tmp_path), verb="check") == 2
    assert "нечем" in capsys.readouterr().out


def test_cli_apply_then_growth_fails_with_address(tmp_path, fake_tool, capsys):
    repo = _py(tmp_path)
    assert lint_profile_cli.run_lint_profile(repo, apply=True) == 0
    assert (repo / lint_baseline.BASELINE_REL).is_file()
    fake_tool["found"] = [("a.py", "PLC2401", 5)]
    assert lint_profile_cli.run_lint_profile(repo, verb="check") == 1
    out = capsys.readouterr().out
    assert "a.py:5" in out and "имя не латиницей" in out


def test_cli_apply_with_missing_tool_is_not_ready(tmp_path, fake_tool, capsys):
    fake_tool["missing"] = True
    assert lint_profile_cli.run_lint_profile(_py(tmp_path), apply=True) == 1
    out = capsys.readouterr().out
    assert "проверено не всё" in out and "ruff не найден" in out


def test_cli_json_check_reports_status(tmp_path, fake_tool, capsys):
    repo = _py(tmp_path)
    lint_profile_cli.run_lint_profile(repo, apply=True, js=True)
    capsys.readouterr()
    assert lint_profile_cli.run_lint_profile(repo, verb="check", js=True) == 0
    assert json.loads(capsys.readouterr().out)["check"]["status"] == lint_baseline.OK
