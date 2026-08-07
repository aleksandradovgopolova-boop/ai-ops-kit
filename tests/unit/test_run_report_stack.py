"""Unit-тесты честного `стек:` в отчёте прогона (P1-3) — tools/ai_ops_run.py.

Проблема, которую закрывает P1-3: отчёт печатал «стек: не определён» на всех путях, где профиль
в отчёт не попадал, — то есть врал про распознанный стек даже в репозитории, который кит
только что успешно определил.

Три обязательных теста на capability (AGENTS.md):
  * positive       — в python-репозитории отчёт печатает `стек: python (pip)`;
  * fail-closed    — стек не определён или детектор упал -> честное «не определён», а не
                     выдуманный стек, и прогон при этом не падает;
  * side-effect    — профиль РЕАЛЬНО лежит в отчёте прогона (и в run-report.json), а не только
                     в stdout: постфактум видно, по какому стеку шёл прогон.

Всё на временных каталогах, без сети и без внешних тулчейнов.
"""
from __future__ import annotations

import subprocess

import pytest

import ai_ops_run


def _py_repo(root):
    (root / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\nversion = '0.1.0'\n\n"
        "[tool.pytest.ini_options]\naddopts = '-q'\n", encoding="utf-8")
    (root / "tests").mkdir(exist_ok=True)
    return root


def _git_repo(root):
    (root / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    for a in (["init"], ["config", "user.email", "t@t"], ["config", "user.name", "t"],
              ["add", "-A"], ["commit", "-m", "init"]):
        subprocess.run(["git", *a], cwd=root, capture_output=True)
    return root


def _pipeline_report(profile):
    """Минимальный отчёт движка — ровно те ключи, которые читает _print_pipeline."""
    return {"kind": "execution-pipeline", "workitem_id": "wi-1", "base_workflow": "QUICK",
            "provider": "mock", "runtime": "claude-code", "ready_for_pr": False,
            "loop": {"stopped": "done", "steps": 1, "applied_writes": 0, "denied": 0},
            "commit": {}, "gates": {}, "profile": profile}


# ---------------------------------------------------------------- positive ---

@pytest.mark.unit
class TestStackIsNamedHonestly:
    """Определённый стек доезжает до человека в том виде, в каком его увидел детектор."""

    def test_python_repo_report_names_the_stack(self, tmp_path):
        prof = ai_ops_run._profile_for_report(_py_repo(tmp_path))
        assert prof["stacks"] == ["python"]
        assert prof["display"] == ["python (pip)"]

    def test_printed_line_shows_stack_not_placeholder(self, tmp_path, capsys):
        """Ровно та регрессия, ради которой P1-3: в python-репо строка `стек:` не «не определён»."""
        ai_ops_run.print_human(_pipeline_report(ai_ops_run._profile_for_report(_py_repo(tmp_path))))
        out = capsys.readouterr().out
        assert "стек: python (pip)" in out
        assert "не определён" not in out

    @pytest.mark.parametrize("profile,expected", [
        ({"stacks": [{"language": "python", "package_manager": "pip"}]}, ["python (pip)"]),
        ({"stacks": [{"language": "go"}]}, ["go"]),
        ({"stacks": ["python", "node"]}, ["python", "node"]),      # отчёты старой формы
        ({"stacks": []}, []),
        ({}, []),
        (None, []),
    ])
    def test_stacks_human_handles_every_report_shape(self, profile, expected):
        """Профиль приезжает в разной форме (словари детектора и строки старых отчётов) —
        печать не должна падать ни на одной, иначе прогон рушится на выводе результата."""
        assert ai_ops_run._stacks_human(profile) == expected


# ------------------------------------------------------------- fail-closed ---

@pytest.mark.unit
class TestUndeterminedStackIsAdmitted:
    """Чего не определили — называем не определённым. Выдуманный стек опаснее отсутствующего."""

    def test_repo_without_manifests_says_undetermined(self, tmp_path, capsys):
        (tmp_path / "README.md").write_text("# демо\n", encoding="utf-8")
        prof = ai_ops_run._profile_for_report(tmp_path)
        assert prof["stacks"] == []
        assert prof["undetermined"], "стек не определён, но причина не названа"

        ai_ops_run.print_human(_pipeline_report(prof))
        assert "стек: не определён" in capsys.readouterr().out

    def test_detector_failure_does_not_break_the_run(self, tmp_path, monkeypatch):
        """Сбой детектора не роняет отчёт: прогон уже сделан, потерять его из-за печати нельзя."""
        import project_detector

        def _boom(_root):
            raise RuntimeError("детектор сломался")

        monkeypatch.setattr(project_detector, "detect", _boom)
        assert ai_ops_run._profile_for_report(tmp_path) is None

    def test_detector_failure_keeps_profile_already_in_report(self, tmp_path, monkeypatch):
        """Если движок уже положил профиль в отчёт, сбой повторной детекции его не стирает."""
        import project_detector

        monkeypatch.setattr(project_detector, "detect",
                            lambda _root: (_ for _ in ()).throw(RuntimeError("боль")))
        prof = ai_ops_run._profile_for_report(tmp_path, existing={"stacks": ["python"]})
        assert prof["stacks"] == ["python"]
        assert prof["display"] == ["python"]

    def test_printing_never_raises_on_missing_profile(self, capsys):
        """Отчёт без профиля вообще (старые run-report.json) печатается, а не падает KeyError."""
        rep = _pipeline_report(None)
        del rep["profile"]
        ai_ops_run.print_human(rep)
        assert "стек: не определён" in capsys.readouterr().out


# -------------------------------------------------------- side-effect proof ---

@pytest.mark.unit
def test_profile_is_really_stored_in_the_run_report(child_root):
    """Профиль лежит в самом отчёте прогона, а не только печатается: постфактум видно,
    по какому стеку кит работал."""
    _py_repo(child_root)
    _git_repo(child_root)

    rep = ai_ops_run.run("правка", {"task_type": "QUICK", "risk": "low"}, child_root,
                         provider_name="mock", engine="pipeline")

    assert rep["profile"]["display"] == ["python (pip)"], \
        "отчёт не знает стек, хотя детектор его определил"
