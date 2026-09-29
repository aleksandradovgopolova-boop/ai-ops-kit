"""Раздел «что выпуск привозит по безопасности» доходит до PR обновления и через CI-шаблон (#1157).

ПОВОД. Раздел появился в теле КОММИТА ветки отложенного обновления (`update_policy: pr`), но дочки,
где обновление идёт джобой `templates/ci/ai-ops-update.yml`, собирают тело PR сами — из
`last-update-report.json`, и раздела там не было: ревьюер обновления его не видел. Теперь данные
раздела лежат в отчёте (`security_surface`), а шаблон выводит их в тело PR.

ИНЪЕКЦИЯ. В разделе — пути и имена из поставки, то есть строки, которые пишет не джоба. Шаблон
обязан передавать их текстом: файл читает python, значение не проходит через `${{ }}` и не
раскрывается shell'ом. Проверено и статически, и настоящим прогоном шага с заглушками `git`/`gh`.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "templates" / "ci" / "ai-ops-update.yml"
EVIL = "НОВОЕ x — .ai/managed/a\"b'c$(touch PWNED1)`touch PWNED2`;touch PWNED3.py:1"


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def update_ops():
    _load("_inst_1157_ci_hub", "installer/ai_ops.py")
    return _load("_update_ops_1157_ci", "installer/update_ops.py")


# ─── отчёт несёт данные раздела ──────────────────────────────────────────────────────────────

def test_report_data_names_new_and_counts_preexisting(update_ops):
    flags = [{"id": "subprocess_shell_true", "path": ".ai/managed/x.py", "line": 7, "arrived": True},
             {"id": "eval_or_exec", "path": ".ai/managed/y.py", "line": 3, "arrived": False}]
    data = update_ops.security_surface(".", [], scan=lambda root, changed: flags)
    assert data["status"] == "new"
    assert data["new"] == [{"id": "subprocess_shell_true", "path": ".ai/managed/x.py", "line": 7}]
    assert data["preexisting"] == 1
    assert "НОВОЕ subprocess_shell_true — .ai/managed/x.py:7" in data["text"]
    json.dumps(data, ensure_ascii=False)                      # кладётся в JSON-отчёт как есть


def test_report_data_nothing_is_explicit(update_ops):
    data = update_ops.security_surface(".", [], scan=lambda root, changed: [])
    assert (data["status"], data["new"], data["preexisting"]) == ("nothing", [], 0)
    assert "ничего:" in data["text"]


def test_report_data_scan_failure_is_not_nothing(update_ops):
    def boom(root, changed):
        raise RuntimeError("сканер упал")
    data = update_ops.security_surface(".", [], scan=boom)
    assert data["status"] == "scan_failed" and data["preexisting"] is None
    assert "НЕ УДАЛОСЬ" in data["text"] and "ничего:" not in data["text"]


# ─── шаблон выводит раздел, не подставляя его в shell ────────────────────────────────────────

def _pr_step():
    doc = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    steps = doc["jobs"]["update"]["steps"]
    return next(s for s in steps if s.get("name") == "Открыть PR с обновлением")


def test_template_pr_body_reads_section_from_report_file():
    run = _pr_step()["run"]
    assert "security_surface" in run, "тело PR не выводит раздел безопасности из отчёта"
    assert "sys.argv[1]" in run and '"${REPORT:-/nonexistent}"' in run, (
        "раздел должен читаться python'ом из ФАЙЛА отчёта, а не из переменной shell")


def test_template_section_never_passes_through_expression_or_shell_var():
    step = _pr_step()
    assert "security_surface" not in json.dumps(step.get("env") or {}), step.get("env")
    for line in step["run"].splitlines():
        if "security_surface" in line or "sys.argv[1]" in line:
            assert "${{" not in line, f"значение отчёта подставляется выражением: {line}"
    assert "$(cat" not in step["run"] and "$(python3" not in step["run"], (
        "текст отчёта захватывается в shell-подстановку — там он уже код, а не данные")


def _run_pr_step(tmp_path, report):
    """Настоящий прогон шага: `git`/`gh` — заглушки, тело PR перехватывается при `gh pr create`."""
    work, stubs = tmp_path / "work", tmp_path / "bin"
    stubs.mkdir()
    (work / ".ai" / "runtime").mkdir(parents=True)
    if report is not None:
        (work / ".ai" / "runtime" / "last-update-report.json").write_text(
            json.dumps(report, ensure_ascii=False), encoding="utf-8")
    (stubs / "git").write_text('#!/bin/sh\n[ "$1" = diff ] && exit 1\n'
                               '[ "$1" = status ] && echo " M x"\nexit 0\n', encoding="utf-8")
    (stubs / "gh").write_text('#!/bin/sh\n[ "$2" = list ] && { echo 0; exit 0; }\n'
                              'while [ $# -gt 0 ]; do [ "$1" = --body-file ] && cp "$2" "$BODY_OUT"; '
                              'shift; done\n', encoding="utf-8")
    for s in stubs.iterdir():
        s.chmod(0o755)
    body_out = tmp_path / "body.md"
    script = _pr_step()["run"].replace("/tmp/pr-body.md", str(tmp_path / "pr-body.md"))
    env = {**os.environ, "PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}", "BODY_OUT": str(body_out),
           "HAS_PAT": "false", "TO": "9.9.9", "FROM": "9.9.8", "GH_TOKEN": "x"}
    r = subprocess.run(["bash", "-e", "-c", script], cwd=work, env=env,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    return body_out.read_text(encoding="utf-8"), work


@pytest.mark.skipif(not shutil.which("bash"), reason="нужен bash")
def test_template_prints_section_as_text_without_executing_it(tmp_path):
    text = "\nЧто этот выпуск привозит по безопасности (сканер кита по файлам .ai/managed/):\n  " + EVIL + "\n"
    body, work = _run_pr_step(tmp_path, {"security_surface": {"status": "new", "text": text}})
    assert "Что этот выпуск привозит по безопасности" in body
    assert EVIL in body, "строка раздела дошла до тела PR не буквально"
    assert not [p for p in (work, tmp_path) for f in p.iterdir() if f.name.startswith("PWNED")], (
        "текст отчёта ИСПОЛНИЛСЯ shell'ом")


@pytest.mark.skipif(not shutil.which("bash"), reason="нужен bash")
def test_template_without_section_says_check_failed(tmp_path):
    body, _ = _run_pr_step(tmp_path, {"status": "ok"})           # отчёт прежнего кита: раздела нет
    assert "проверить НЕ УДАЛОСЬ" in body and "ничего:" not in body


# ─── битый отчёт не роняет шаг после push, битая отметка — не роняет update ──────────────────

@pytest.mark.skipif(not shutil.which("bash"), reason="нужен bash")
@pytest.mark.parametrize("text", [None, 42, ["x"], "", "   \n"],
                         ids=["textnull", "textnotstr", "textlist", "empty", "blank"])
def test_template_broken_section_says_check_failed(tmp_path, text):
    body, _ = _run_pr_step(tmp_path, {"security_surface": {"text": text}})
    assert "проверить НЕ УДАЛОСЬ" in body and "ничего:" not in body, body


def test_flag_without_key_is_scan_failed_not_crash(update_ops, monkeypatch):
    """Отметка без ключа (`line`) — «проверить не удалось», а не KeyError после записи файлов."""
    from ai_ops_kit.security import security_scan
    monkeypatch.setattr(security_scan, "delivered_surface",
                        lambda root, changed, base=None: [{"id": "x", "path": "p", "arrived": True}])
    data = update_ops.security_surface(".", [".ai/managed/p"])
    assert data["status"] == "scan_failed" and data["error"] == "KeyError", data
    assert "НЕ УДАЛОСЬ" in data["text"]
