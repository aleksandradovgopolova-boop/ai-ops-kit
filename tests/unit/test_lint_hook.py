"""Хук линта дочки (`templates/runtime/lint_hook.py`): правка агента проверяется линтером проекта.

Работа `lint-runs-at-edit-and-in-child-ci` (#1183). Три обязательных теста на capability:
  * positive     — нарушение в правке -> код 2 и сообщение линтера агенту; чистая правка -> 0 молча;
  * fail-closed  — проверить нечем (нет линтера, нет команды, линтер упал) -> 0 и строка «НЕ
                   проверена», а не молчаливый «пройдено» и не блокировка сессии;
  * side-effect  — линтер зовётся ТОЛЬКО на изменённом файле и НЕ зовётся вне дочки, на служебных
                   путях и при опт-ауте (фальшивый линтер пишет журнал вызовов).

Линтеры фальшивые (sh-скрипты в tmp_path): тест проверяет проводку хука, а не ruff/eslint.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[2]
HOOK = KIT / "templates" / "runtime" / "lint_hook.py"

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def lh():
    spec = importlib.util.spec_from_file_location("_lint_hook_under_test", HOOK)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    # Без байткода: `templates/**` едет в поставку целиком, `.pyc` рядом с хуком стал бы её частью.
    saved, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = saved
    return mod


# Фальшивый линтер: пишет свои аргументы в журнал, падает кодом 1 на файле со словом BAD,
# кодом 2 — на слове CRASH (так ruff/eslint сообщают о сбое конфигурации, а не о нарушениях).
_FAKE = """#!/bin/sh
echo "$@" >> "{log}"
for a in "$@"; do f="$a"; done
if grep -q CRASH "$f" 2>/dev/null; then echo "config error: boom" >&2; exit 2; fi
if grep -q BAD "$f" 2>/dev/null; then
  i=0; while [ $i -lt {lines} ]; do echo "$f:$i:1: E001 плохое имя"; i=$((i+1)); done; exit 1
fi
exit 0
"""


def _fake_linter(path: Path, log: Path, lines: int = 1) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_FAKE.format(log=log, lines=lines), encoding="utf-8")
    path.chmod(0o755)
    return path


def _profile(root: Path, stacks: list) -> None:
    (root / ".ai").mkdir(parents=True, exist_ok=True)
    (root / ".ai" / "repository-profile.yaml").write_text(
        json.dumps({"kind": "repository-profile", "stacks": stacks}), encoding="utf-8")  # JSON ⊂ YAML


@pytest.fixture
def py_child(tmp_path):
    """Python-дочка: профиль с `ruff check .` и фальшивый ruff в `.venv/bin`."""
    root = tmp_path / "child"
    (root / "src").mkdir(parents=True)
    _profile(root, [{"language": "python", "commands": {"lint": "ruff check ."}}])
    log = tmp_path / "calls.log"
    _fake_linter(root / ".venv" / "bin" / "ruff", log)
    return root, log


def _event(path: Path) -> dict:
    return {"tool_name": "Write", "tool_input": {"file_path": str(path)}}


def _calls(log: Path) -> list:
    return log.read_text(encoding="utf-8").splitlines() if log.is_file() else []


# ── positive ──────────────────────────────────────────────────────────────────────────────────────

def test_violation_exits_2_with_linter_message(lh, py_child):
    root, log = py_child
    f = root / "src" / "calc.py"
    f.write_text("BAD = 1\n", encoding="utf-8")
    code, err, out = lh.run_hook(_event(f), root)
    assert code == 2, "нарушение в правке обязано вернуться агенту кодом 2"
    assert "src/calc.py" in err and "E001 плохое имя" in err, err
    assert "ruff" in err and out == ""


def test_clean_file_exits_0_silently(lh, py_child):
    root, log = py_child
    f = root / "src" / "ok.py"
    f.write_text("x = 1\n", encoding="utf-8")
    assert lh.run_hook(_event(f), root) == (0, "", "")
    assert _calls(log), "линтер не позвали — «чисто» ничем не проверено"


def test_linter_sees_only_the_edited_file(lh, py_child):
    root, log = py_child
    f = root / "src" / "one.py"
    f.write_text("x = 1\n", encoding="utf-8")
    lh.run_hook(_event(f), root)
    (call,) = _calls(log)
    assert call.split() == ["check", "--force-exclude", "src/one.py"], call


def test_node_eslint_runs_on_the_file_via_local_bin(lh, tmp_path):
    root = tmp_path / "web"
    (root / "src").mkdir(parents=True)
    (root / "package.json").write_text(json.dumps({"scripts": {"lint": "eslint ."}}), encoding="utf-8")
    _profile(root, [{"language": "node", "commands": {"lint": "npm run lint"}}])
    log = tmp_path / "eslint.log"
    _fake_linter(root / "node_modules" / ".bin" / "eslint", log)
    f = root / "src" / "App.tsx"
    f.write_text("const BAD = 1\n", encoding="utf-8")
    code, err, _ = lh.run_hook(_event(f), root)
    assert code == 2 and "eslint" in err
    assert _calls(log) == ["src/App.tsx"]


def test_go_lints_only_the_package_of_the_file(lh, tmp_path):
    root = tmp_path / "svc"
    argv, cwd, why = lh.per_file_command(root, "internal/api/h.go", "go", "golangci-lint run")
    if argv is None:                       # на машине без golangci-lint — честная причина, не argv
        assert "не установлен" in why
    else:
        assert argv[1:] == ["run", "./internal/api"] and cwd == root


def test_long_output_is_capped(lh, tmp_path):
    root = tmp_path / "child"
    (root / "src").mkdir(parents=True)
    _profile(root, [{"language": "python", "commands": {"lint": "ruff check ."}}])
    _fake_linter(root / ".venv" / "bin" / "ruff", tmp_path / "l.log", lines=200)
    f = root / "src" / "big.py"
    f.write_text("BAD\n", encoding="utf-8")
    code, err, _ = lh.run_hook(_event(f), root)
    assert code == 2
    assert err.count("E001") <= lh.MAX_LINES and "всего строк: 200" in err
    assert len(err) < lh.MAX_CHARS + 500


def test_cli_entry_reads_stdin_like_claude_code(py_child):
    """Как зовёт Claude Code: JSON в stdin, код выхода и stderr процесса."""
    root, _ = py_child
    f = root / "src" / "cli.py"
    f.write_text("BAD\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(HOOK), "hook", "--root", str(root)],
                       input=json.dumps(_event(f)), capture_output=True, text=True, timeout=60)
    assert r.returncode == 2 and "src/cli.py" in r.stderr, (r.returncode, r.stderr)


# ── fail-closed: проверить нечем — не блокируем, но и не выдаём за пройденное ────────────────────

def _context(out: str) -> str:
    return json.loads(out)["hookSpecificOutput"]["additionalContext"]


def test_missing_linter_is_0_with_note_not_a_pass(lh, tmp_path, monkeypatch):
    root = tmp_path / "child"
    (root / "src").mkdir(parents=True)
    _profile(root, [{"language": "python", "commands": {"lint": "ruff check ."}}])
    empty = tmp_path / "emptybin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    f = root / "src" / "a.py"
    f.write_text("BAD\n", encoding="utf-8")
    code, err, out = lh.run_hook(_event(f), root)
    assert code == 0 and err == ""
    ctx = _context(out)
    assert "не установлен" in ctx and "НЕ проверена" in ctx, ctx


def test_no_lint_command_in_profile_is_named(lh, tmp_path):
    root = tmp_path / "child"
    (root / "src").mkdir(parents=True)
    _profile(root, [{"language": "python", "commands": {"lint": None}}])
    f = root / "src" / "a.py"
    f.write_text("x\n", encoding="utf-8")
    code, _, out = lh.run_hook(_event(f), root)
    assert code == 0 and "нет команды линта" in _context(out)


def test_no_profile_is_named(lh, tmp_path):
    root = tmp_path / "child"
    (root / "src").mkdir(parents=True)
    f = root / "src" / "a.py"
    f.write_text("x\n", encoding="utf-8")
    code, _, out = lh.run_hook(_event(f), root)
    assert code == 0 and "профиль" in _context(out)


def test_linter_crash_is_not_a_violation_and_not_a_pass(lh, py_child):
    root, _ = py_child
    f = root / "src" / "c.py"
    f.write_text("CRASH\n", encoding="utf-8")
    code, err, out = lh.run_hook(_event(f), root)
    assert code == 0 and err == ""
    assert "не отработал (код 2" in _context(out)


def test_whole_repo_only_command_is_skipped_with_reason(lh, tmp_path):
    root = tmp_path / "web"
    (root / "src").mkdir(parents=True)
    (root / "package.json").write_text(json.dumps({"scripts": {"lint": "turbo run lint"}}),
                                       encoding="utf-8")
    _profile(root, [{"language": "node", "commands": {"lint": "npm run lint"}}])
    f = root / "src" / "a.ts"
    f.write_text("x\n", encoding="utf-8")
    code, _, out = lh.run_hook(_event(f), root)
    assert code == 0 and "весь репозиторий" in _context(out)


# ── side-effect: где линтер НЕ зовётся ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("rel", [".ai/managed/x.py", "node_modules/pkg/a.py", ".venv/lib/a.py",
                                 "build/gen.py", "docs/readme.md"])
def test_service_paths_and_non_code_are_skipped(lh, py_child, rel):
    root, log = py_child
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("BAD\n", encoding="utf-8")
    assert lh.run_hook(_event(f), root) == (0, "", "")
    assert _calls(log) == [], f"линтер позван на {rel}"


def test_file_outside_the_child_is_skipped(lh, py_child, tmp_path):
    root, log = py_child
    f = tmp_path / "elsewhere.py"
    f.write_text("BAD\n", encoding="utf-8")
    assert lh.run_hook(_event(f), root) == (0, "", "")
    assert _calls(log) == []


@pytest.mark.parametrize("value", ["off", "false", "disabled"])
def test_opt_out_in_config_disables_the_hook(lh, py_child, value):
    root, log = py_child
    (root / ".ai-ops.yaml").write_text(f"standard:\n  lint_hook: {value}\n", encoding="utf-8")
    f = root / "src" / "a.py"
    f.write_text("BAD\n", encoding="utf-8")
    assert lh.run_hook(_event(f), root) == (0, "", "")
    assert _calls(log) == []


def test_config_without_the_key_keeps_the_hook_on(lh, py_child):
    root, _ = py_child
    (root / ".ai-ops.yaml").write_text("standard:\n  version: 7\n", encoding="utf-8")
    f = root / "src" / "a.py"
    f.write_text("BAD\n", encoding="utf-8")
    assert lh.run_hook(_event(f), root)[0] == 2


# ── вход `ci`: весь репозиторий, честно о пропуске ──────────────────────────────────────────────

def _ci_child(tmp_path, commands: dict, fake: str = "ruff"):
    root = tmp_path / "child"
    (root / "src").mkdir(parents=True)
    bindir = tmp_path / "bin"
    _fake_linter(bindir / fake, tmp_path / "ci.log")
    prof = tmp_path / "profile.json"
    prof.write_text(json.dumps({"stacks": [{"language": "python", "commands": commands}]}),
                    encoding="utf-8")
    return root, bindir, prof


def test_ci_passes_when_the_lint_command_passes(lh, tmp_path, monkeypatch):
    root, bindir, prof = _ci_child(tmp_path, {"lint": "ruff check src/ok.py"})
    (root / "src" / "ok.py").write_text("x\n", encoding="utf-8")
    monkeypatch.setenv("PATH", f"{bindir}:/usr/bin:/bin")
    code, lines = lh.run_ci(root, prof)
    assert code == 0 and any("пройдено" in ln for ln in lines), lines


def test_ci_fails_on_violations(lh, tmp_path, monkeypatch):
    root, bindir, prof = _ci_child(tmp_path, {"lint": "ruff check src/bad.py"})
    (root / "src" / "bad.py").write_text("BAD\n", encoding="utf-8")
    monkeypatch.setenv("PATH", f"{bindir}:/usr/bin:/bin")
    code, lines = lh.run_ci(root, prof)
    assert code == 1
    assert any(ln.startswith("::error::") and "НЕ пройдено" in ln for ln in lines), lines
    assert any("E001" in ln for ln in lines), "причина провала не показана"


def test_ci_without_linter_warns_plainly_not_silently(lh, tmp_path):
    root, _, prof = _ci_child(tmp_path, {"lint": None, "test": "pytest"})
    code, lines = lh.run_ci(root, prof)
    assert code == 0
    text = "\n".join(lines)
    assert "::warning::" in text and "НЕ исполнялся" in text and "не найден" in text, text


def test_ci_declared_but_missing_tool_is_red(lh, tmp_path, monkeypatch):
    root, _, prof = _ci_child(tmp_path, {"lint": "no-such-linter-xyz ."})
    code, lines = lh.run_ci(root, prof)
    assert code == 1 and any("не нашлась" in ln for ln in lines), lines


def test_ci_refuses_format_command_that_rewrites(lh, tmp_path, monkeypatch):
    root, bindir, prof = _ci_child(tmp_path, {"lint": "ruff check src", "format": "prettier --write ."})
    monkeypatch.setenv("PATH", f"{bindir}:/usr/bin:/bin")
    code, lines = lh.run_ci(root, prof)
    assert any("переписывает файлы" in ln and "НЕ проверен" in ln for ln in lines), lines
    assert code == 0


def test_ci_writes_step_summary(lh, tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    lh._summary(["python: lint `ruff check .` — пройдено", "    деталь не в сводку"])
    text = summary.read_text(encoding="utf-8")
    assert "Линт дочки" in text and "пройдено" in text and "деталь" not in text
