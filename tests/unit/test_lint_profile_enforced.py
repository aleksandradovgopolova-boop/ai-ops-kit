"""Профиль стиля держат все три точки принуждения, а не одна ручная команда (#1183).

Работа `lint-profile-enforced-everywhere`. Прежде включённый профиль (`./ai-ops lint-profile --apply`)
сверялся только командой `lint-profile check`: хук правки агента, шаг child-CI и доказательство
`lint_passed` прогона кита гоняли линтер дочки и профиля не видели. Три теста на capability:
  * positive     — новое имя не латиницей: хук -> код 2 с адресом, CI -> красный, гейт -> `lint_passed`
                   снят и адрес в блокере; существующее (в пределах линии) — не в счёт;
  * fail-closed  — профиль включён, а проверить нечем (нет ESLint) -> «проверено не всё», а не
                   «пройдено»; время хука вышло -> сказано, а не молча;
  * side-effect  — профиль не включён -> все три точки ведут себя как прежде; хук зовёт инструмент
                   ТОЛЬКО на изменённом файле, и чужие файлы в сравнение не попадают.

ESLint фальшивый (python-скрипт в `node_modules/.bin`), но повторяет РОДНЫЕ подавления ESLint 10:
счётчик файла × правила в пределах — все находки подавлены, сверх — возвращаются все.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from ai_ops_kit.checks import lint_baseline, lint_profile, lint_profile_js
from ai_ops_kit.engine import tool_broker
from ai_ops_kit.gates import evidence_collector

pytestmark = pytest.mark.unit

KIT = Path(__file__).resolve().parents[2]
HOOK = KIT / "templates" / "runtime" / "lint_hook.py"


@pytest.fixture(scope="module")
def lh():
    spec = importlib.util.spec_from_file_location("_lint_hook_profile_under_test", HOOK)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    saved, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = saved
    return mod


# Фальшивый ESLint. Без `-c` — «линтер проекта»: всегда чисто. С `-c` — профиль: каждая строка с
# `ИМЯ` — находка `ai-ops/id-match`; подавления читаются из `--suppressions-location`.
_FAKE_ESLINT = r'''#!{py}
import json, os, sys
a = sys.argv[1:]
with open({log!r}, "a", encoding="utf-8") as fh:
    fh.write(" ".join(a) + "\n")
if "-c" not in a:
    sys.exit(0)
out = a[a.index("-o") + 1]
supp = {{}}
if "--suppressions-location" in a:
    p = a[a.index("--suppressions-location") + 1]
    supp = json.load(open(p)) if os.path.isfile(p) else {{}}
skip = {{"-c", "-f", "-o", "--suppressions-location"}}
targets, i = [], 0
while i < len(a):
    if a[i] in skip:
        i += 2
        continue
    if not a[i].startswith("--"):
        targets.append(a[i])
    i += 1
files = []
for t in targets:
    if os.path.isdir(t):
        for d, dn, fn in os.walk(t):
            dn[:] = [x for x in dn if x not in ("node_modules", ".ai")]
            files += [os.path.join(d, f) for f in fn if f.endswith((".ts", ".tsx"))]
    else:
        files.append(t)
res = []
for f in sorted(files):
    rel = os.path.relpath(f).replace(os.sep, "/")
    lines = [n + 1 for n, ln in enumerate(open(f, encoding="utf-8")) if "ИМЯ" in ln]
    msgs = [{{"ruleId": "ai-ops/id-match", "line": n}} for n in lines]
    cap = ((supp.get(rel) or {{}}).get("ai-ops/id-match") or {{}}).get("count", 0)
    within = len(msgs) <= cap
    res.append({{"filePath": os.path.abspath(f), "messages": [] if within else msgs,
                "suppressedMessages": msgs if within else []}})
json.dump(res, open(out, "w"))
sys.exit(1 if any(r["messages"] for r in res) else 0)
'''


def _child(tmp_path: Path, frozen: dict | None = None, eslint: bool = True) -> Path:
    """TS-дочка с ВКЛЮЧЁННЫМ профилем: конфиг профиля записан, линия заморожена."""
    root = tmp_path / "child"
    (root / "src").mkdir(parents=True)
    (root / "package.json").write_text(json.dumps({"scripts": {"lint": "eslint ."},
                                                   "devDependencies": {"eslint": "10"}}))
    (root / "src" / "old.ts").write_text("const ИМЯ = 1;\n")         # существующее, заморожено
    (root / "src" / "clean.ts").write_text("export const ok = 1;\n")
    (root / ".ai").mkdir(exist_ok=True)
    (root / ".ai" / "repository-profile.yaml").write_text(json.dumps(
        {"stacks": [{"language": "node", "commands": {"lint": "npm run lint"}}]}))
    if eslint:
        ver = root / "node_modules" / "eslint" / "package.json"
        ver.parent.mkdir(parents=True)
        ver.write_text(json.dumps({"version": "10.0.0"}))
        bin_ = root / "node_modules" / ".bin" / "eslint"
        bin_.parent.mkdir(parents=True)
        bin_.write_text(_FAKE_ESLINT.format(py=sys.executable, log=str(tmp_path / "eslint.log")))
        bin_.chmod(0o755)
    lint_profile.apply(root, lint_profile.render(root, {}))
    supp = root / lint_profile_js.SUPPRESSIONS
    supp.parent.mkdir(parents=True, exist_ok=True)
    supp.write_text(json.dumps(frozen if frozen is not None
                               else {"src/old.ts": {"ai-ops/id-match": {"count": 1}}}))
    return root


def _event(path: Path) -> dict:
    return {"tool_name": "Write", "tool_input": {"file_path": str(path)}}


def _profile_calls(tmp_path: Path) -> list:
    log = tmp_path / "eslint.log"
    lines = log.read_text(encoding="utf-8").splitlines() if log.is_file() else []
    return [ln for ln in lines if "-c " in ln]


# ── какой профиль включён: по файлам на диске ────────────────────────────────────────────────────

def test_no_profile_on_disk_means_nothing_to_enforce(tmp_path):
    (tmp_path / "package.json").write_text("{}")
    assert lint_profile.applied_tools(tmp_path) == []


def test_written_eslint_profile_is_enforced_with_its_suppressions(tmp_path):
    root = _child(tmp_path)
    (spec,) = lint_profile.applied_tools(root)
    assert spec["tool"] == "eslint" and spec["config"] == lint_profile_js.OUT
    assert spec["suppressions"] == lint_profile_js.SUPPRESSIONS


def test_ruff_profile_rules_follow_the_identifiers_policy(tmp_path):
    (tmp_path / lint_profile.RUFF_OUT).parent.mkdir(parents=True)
    (tmp_path / lint_profile.RUFF_OUT).write_text("[lint]\n")
    assert lint_profile.applied_tools(tmp_path)[0]["rules"] == ["PLC2401", "PLC2403", "N"]
    (tmp_path / ".ai-ops.yaml").write_text("standard:\n  identifiers: any\n")
    assert lint_profile.applied_tools(tmp_path)[0]["rules"] == ["N"]


def test_file_is_judged_only_by_tools_of_its_language():
    tools = [{"tool": "eslint"}, {"tool": "ruff"}, {"tool": "import-linter"}]
    assert [t["tool"] for t in lint_profile.tools_for_file(tools, "src/App.tsx")] == ["eslint"]
    assert [t["tool"] for t in lint_profile.tools_for_file(tools, "a/b.py")] == ["ruff", "import-linter"]
    assert lint_profile.tools_for_file(tools, "README.md") == []


# ── командная строка и разбор — одни на все точки ────────────────────────────────────────────────

ESLINT = {"tool": "eslint", "config": "eslint.ai-ops.config.mjs"}


def test_eslint_argv_lints_only_the_given_files():
    argv = lint_baseline.tool_argv(ESLINT, "eslint", "/tmp/o.json", ["--x"], ["src/a.ts"])
    assert argv == ["eslint", "-c", "eslint.ai-ops.config.mjs", "-f", "json", "-o", "/tmp/o.json",
                    "--x", "src/a.ts"]
    assert lint_baseline.tool_argv(ESLINT, "eslint", "o", [], None)[-1] == "."


def test_dash_named_target_reaches_the_tool_as_a_path():
    assert lint_baseline.tool_argv(ESLINT, "eslint", "o", [], ["-rf.ts"])[-1] == "./-rf.ts"


def test_ruff_result_goes_to_a_file_not_to_the_limited_stdout():
    argv = lint_baseline.tool_argv({"tool": "ruff", "config": "r.toml"}, "ruff", "o.json", [], ["a.py"])
    assert argv[argv.index("--output-file") + 1] == "o.json" and argv[-1] == "a.py"


def test_golangci_checks_the_package_of_the_file():
    spec = {"tool": "golangci-lint", "config": "g.yml"}
    argv = lint_baseline.tool_argv(spec, "golangci-lint", "o", [], ["internal/api/h.go", "main.go"])
    assert argv[-2:] == [".", "./internal/api"]


def test_import_linter_is_whole_project_only():
    spec = {"tool": "import-linter", "config": "i.ini"}
    assert lint_baseline.tool_argv(spec, "lint-imports", "o", [], ["a.py"]) is None
    assert lint_baseline.tool_argv(spec, "lint-imports", "o", [], None) == ["lint-imports", "--config", "i.ini"]


def test_run_tool_reads_the_result_file_written_by_the_tool(tmp_path):
    root = _child(tmp_path)
    seen = []

    def run(argv, cwd):
        seen.append(argv)
        out = argv[argv.index("-o") + 1]
        Path(out).write_text(json.dumps([{"filePath": str(root / "src/a.ts"), "messages": [
            {"ruleId": "ai-ops/id-match", "line": 3}, {"ruleId": "no-var", "line": 4}]}]))
        return 1, ""
    found, supp, why = lint_baseline.run_tool(root, ESLINT, run, [], ["src/a.ts"])
    assert why is None and found == [("src/a.ts", "ai-ops/id-match", 3)], (found, why)
    assert seen[0][-1] == "src/a.ts"


def test_run_tool_names_a_missing_tool(tmp_path):
    found, _, why = lint_baseline.run_tool(tmp_path, {"tool": "eslint-nope-xyz", "config": "c"},
                                           lambda a, c: (0, ""))
    assert found is None and "не найден" in why


# ── сверка по одному файлу ───────────────────────────────────────────────────────────────────────

RUFF = {"tool": "ruff", "config": ".ai/project/lint/ruff.toml", "rules": ["PLC2401"]}


def test_check_of_one_file_ignores_growth_elsewhere(tmp_path):
    lint_baseline.save(tmp_path, {"ruff": {"a.py": {"PLC2401": 1}}})
    calls = []

    def measure(root, spec, extra=(), targets=None):
        calls.append(targets)
        return [("a.py", "PLC2401", 1), ("b.py", "PLC2401", 1), ("b.py", "PLC2401", 2)], {}, None
    res = lint_baseline.check(tmp_path, [RUFF], measure, files=["a.py"])
    assert calls == [["a.py"]], "инструмент обязан получить только изменённый файл"
    assert res["status"] == lint_baseline.OK and res["tools"][0]["shrunk"] == []


def test_check_of_one_file_catches_its_own_growth(tmp_path):
    lint_baseline.save(tmp_path, {"ruff": {"a.py": {"PLC2401": 1}}})
    res = lint_baseline.check(tmp_path, [RUFF], lambda r, s, e=(), targets=None: (
        [("a.py", "PLC2401", 1), ("a.py", "PLC2401", 9)], {}, None), files=["a.py"])
    assert res["status"] == lint_baseline.GREW
    assert lint_baseline.address(lint_baseline.grown(res)[0]) == \
        "a.py:1 — имя не латиницей (было 1, стало 2)"


def test_check_of_one_file_never_rewrites_the_line(tmp_path):
    lint_baseline.save(tmp_path, {"ruff": {"a.py": {"PLC2401": 2}}})
    lint_baseline.check(tmp_path, [RUFF], lambda r, s, e=(), targets=None: ([], {}, None),
                        tighten=True, files=["a.py"])
    assert lint_baseline.load(tmp_path)["tools"]["ruff"] == {"a.py": {"PLC2401": {"count": 2}}}


# ── (a) хук правки ───────────────────────────────────────────────────────────────────────────────

def test_hook_blocks_a_new_non_latin_name_and_names_it(lh, tmp_path):
    root = _child(tmp_path)
    f = root / "src" / "new.ts"
    f.write_text("export const x = 1;\nconst ИМЯ = 2;\n")
    code, err, _ = lh.run_hook(_event(f), root)
    assert code == 2, err
    assert "src/new.ts:2 — имя не латиницей (было 0, стало 1)" in err and "Профиль стиля" in err


def test_hook_passes_an_existing_file_within_its_frozen_line(lh, tmp_path):
    root = _child(tmp_path)
    assert lh.run_hook(_event(root / "src" / "old.ts"), root) == (0, "", "")


def test_hook_blocks_growth_inside_an_existing_file(lh, tmp_path):
    root = _child(tmp_path)
    f = root / "src" / "old.ts"
    f.write_text(f.read_text() + "const ИМЯ2 = 3;\n")
    code, err, _ = lh.run_hook(_event(f), root)
    assert code == 2 and "(было 1, стало 2)" in err, err


def test_hook_runs_the_profile_only_on_the_edited_file(lh, tmp_path):
    root = _child(tmp_path)
    (root / "src" / "other.ts").write_text("const ИМЯ = 1;\n")    # чужой рост — не этой правки
    assert lh.run_hook(_event(root / "src" / "clean.ts"), root) == (0, "", "")
    (call,) = _profile_calls(tmp_path)
    assert call.endswith(" src/clean.ts") and " . " not in f" {call} ", call


def test_hook_says_when_the_profile_could_not_be_checked(lh, tmp_path):
    root = _child(tmp_path, eslint=False)
    f = root / "src" / "new.ts"
    f.write_text("const ИМЯ = 2;\n")
    code, err, out = lh.run_hook(_event(f), root)
    ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert code == 0 and err == ""
    assert "профиль стиля AI Ops проверен не весь" in ctx and "НЕ проверена" in ctx, ctx


def test_hook_out_of_time_for_the_profile_says_so(lh, tmp_path, monkeypatch):
    root = _child(tmp_path)
    f = root / "src" / "new.ts"
    f.write_text("const ИМЯ = 2;\n")
    monkeypatch.setattr(lh, "TIMEOUT_S", 2)
    monkeypatch.setattr(lh, "_project_lint", lambda *a: ("ok", ""))
    code, _, out = lh.run_hook(_event(f), root)
    assert code == 0 and "не успел" in json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert _profile_calls(tmp_path) == []


def test_hook_reports_project_linter_and_profile_together(lh, tmp_path, monkeypatch):
    root = _child(tmp_path)
    f = root / "src" / "new.ts"
    f.write_text("const ИМЯ = 2;\n")
    monkeypatch.setattr(lh, "_project_lint", lambda *a: ("violation", "Линтер проекта: E1"))
    code, err, _ = lh.run_hook(_event(f), root)
    assert code == 2 and "Линтер проекта: E1" in err and "имя не латиницей" in err


# ── (b) шаг CI ───────────────────────────────────────────────────────────────────────────────────

def test_ci_is_red_on_growth_and_green_after_the_fix(lh, tmp_path, monkeypatch):
    root = _child(tmp_path)
    monkeypatch.setattr(lh, "_run", lambda argv, cwd: (0, ""))      # линтер проекта — чисто
    new = root / "src" / "new.ts"
    new.write_text("const ИМЯ = 2;\n")
    code, lines = lh.run_ci(root)
    text = "\n".join(lines)
    assert code == 1 and "::error::профиль стиля AI Ops" in text and "src/new.ts" in text, text
    new.unlink()
    code, lines = lh.run_ci(root)
    assert code == 0 and any("lint-profile check` — пройдено" in ln for ln in lines), lines


def test_ci_without_a_profile_adds_only_a_plain_line(lh, tmp_path, monkeypatch):
    root = tmp_path / "plain"
    (root / ".ai").mkdir(parents=True)
    (root / ".ai" / "repository-profile.yaml").write_text(json.dumps(
        {"stacks": [{"language": "node", "commands": {"lint": "npm run lint"}}]}))
    monkeypatch.setattr(lh, "_run", lambda argv, cwd: (0, ""))
    code, lines = lh.run_ci(root)
    (line,) = [ln for ln in lines if "профиль стиля" in ln]
    assert code == 0 and not line.startswith("::") and "не включён" in line


# ── (c) доказательство lint_passed прогона кита ─────────────────────────────────────────────────

_LINT_ONLY = {"stacks": [{"language": "node", "commands": {"lint": "true"}}]}


def _collect(root: Path) -> dict:
    pol = tool_broker.Policy(level="execution", child_root=str(root), block_push=True)
    return evidence_collector.collect(_LINT_ONLY, root, pol, broker=tool_broker)


def test_growth_fails_lint_passed_with_the_address(tmp_path):
    root = _child(tmp_path)
    (root / "src" / "new.ts").write_text("const ИМЯ = 2;\n")
    res = _collect(root)
    iv = res["gate_evidence"]["implementation_verification"]
    assert "lint_passed" not in iv["provided"] and iv["status"] == "fail"
    assert any("src/new.ts:1 — имя не латиницей" in b for b in iv["blockers"]), iv["blockers"]
    assert res["checks"]["lint"]["status"] == "fail"


def test_frozen_line_keeps_lint_passed(tmp_path):
    res = _collect(_child(tmp_path))
    iv = res["gate_evidence"]["implementation_verification"]
    assert "lint_passed" in iv["provided"] and not iv.get("blockers")
    assert res["checks"]["lint"]["style_profile"]["status"] == lint_baseline.OK


def test_profile_not_checkable_is_a_warning_not_a_pass_claim(tmp_path):
    res = _collect(_child(tmp_path, eslint=False))
    iv = res["gate_evidence"]["implementation_verification"]
    assert any("профиль стиля проверен не весь" in w for w in iv.get("warnings") or []), iv


def test_no_profile_leaves_lint_evidence_unchanged(tmp_path):
    (tmp_path / "package.json").write_text("{}")
    res = _collect(tmp_path)
    assert "style_profile" not in res["checks"]["lint"]
    assert "lint_passed" in res["gate_evidence"]["implementation_verification"]["provided"]


def test_growth_fails_lint_even_when_the_child_has_no_linter(tmp_path):
    root = _child(tmp_path)
    (root / "src" / "new.ts").write_text("const ИМЯ = 2;\n")
    pol = tool_broker.Policy(level="execution", child_root=str(root), block_push=True)
    res = evidence_collector.collect({"stacks": [{"language": "node", "commands": {}}]}, root, pol,
                                     broker=tool_broker)
    assert "lint_passed" not in res["not_applicable"], "рост профиля не может быть «неприменимым»"
    assert res["gate_evidence"]["implementation_verification"]["status"] == "fail"
