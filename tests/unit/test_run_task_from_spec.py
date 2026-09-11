"""`run`/`do` без текста задачи берут её из spec.yaml (живой прогон #587, 08.09.2026).

Движок строит задачу писателю ТОЛЬКО из позиционного аргумента (`ctx = task + профиль`), а НЕ из
spec.yaml. Вызов `./ai-ops run --execute --feature <wid>` без текста давал писателю пустой блок
«=== ЗАДАЧА ===»: два прогона подряд дали 0 правок / openspec-заготовку про «задача пуста», хотя
spec.yaml с целью и критериями был заполнен. Лечение: когда текст не передан, а спека фичи
заполнена — `run`/`do` собирают задачу из её разделов (`status: complete`). Fail-closed: нет спеки /
нет заполненных разделов -> задача пустая, поведение как раньше (кит честно заблокирует).

Три обязательных теста на capability (AGENTS.md): positive (сборка из спеки), override (явный текст
задачи НЕ перекрывается), backward-compat / fail-closed (нет спеки / пустые разделы -> пусто).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from ai_ops_kit.cli import ai_ops_cli
from ai_ops_kit.gates import spec_levels


def _repo(root: Path) -> Path:
    (root / ".ai-ops.yaml").write_text("project: {name: t}\n", encoding="utf-8")
    (root / "app.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    for a in (["init"], ["config", "user.email", "t@t"], ["config", "user.name", "t"],
              ["add", "-A"], ["commit", "-m", "init"]):
        subprocess.run(["git", *a], cwd=root, capture_output=True)
    return root


def _write_spec(root: Path, wid: str, sections: dict) -> None:
    sp = spec_levels._spec_path(root, wid)
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(yaml.safe_dump(
        {"kind": "spec", "workitem_id": wid, "level": 1, "sections": sections},
        allow_unicode=True, sort_keys=False), encoding="utf-8")


# ----------------------------------------------------------- уровень модуля ---

@pytest.mark.unit
class TestTaskFromSpec:

    def test_composes_completed_sections_in_order(self, tmp_path):
        _write_spec(tmp_path, "wi-1", {
            "goal": {"status": "complete", "content": "показать время чтения"},
            "acceptance_criteria": {"status": "complete", "content": "пусто -> 0"},
        })
        task = spec_levels.task_from_spec(tmp_path, "wi-1")
        assert "показать время чтения" in task
        assert "пусто -> 0" in task
        # порядок: goal (Цель) раньше acceptance_criteria (Критерии приёмки)
        assert task.index("Цель") < task.index("Критерии приёмки")

    def test_skips_missing_and_empty_sections(self, tmp_path):
        _write_spec(tmp_path, "wi-1", {
            "goal": {"status": "complete", "content": "сделать X"},
            "scope": {"status": "missing", "content": ""},
            "constraints": {"status": "complete", "content": "   "},  # пробелы = пусто
        })
        task = spec_levels.task_from_spec(tmp_path, "wi-1")
        assert "сделать X" in task
        assert "Объём работ" not in task       # scope missing
        assert "Ограничения" not in task       # constraints пустой

    def test_no_spec_returns_empty(self, tmp_path):
        assert spec_levels.task_from_spec(tmp_path, "no-such") == ""

    def test_all_sections_incomplete_returns_empty(self, tmp_path):
        _write_spec(tmp_path, "wi-1", {"goal": {"status": "missing", "content": ""}})
        assert spec_levels.task_from_spec(tmp_path, "wi-1") == ""

    def test_broken_spec_returns_empty(self, tmp_path):
        sp = spec_levels._spec_path(tmp_path, "wi-1")
        sp.parent.mkdir(parents=True)
        sp.write_text("this: is: not: valid: yaml: [", encoding="utf-8")
        assert spec_levels.task_from_spec(tmp_path, "wi-1") == ""


# -------------------------------------------------------- путь человека CLI ---

@pytest.mark.unit
class TestRunDerivesTaskFromSpec:

    def _spy_run(self, monkeypatch):
        seen = {}
        from ai_ops_kit.engine import ai_ops_run

        def _spy(task, signals, child_root, **kw):
            seen["task"] = task
            return {"schema_version": 1, "kind": "execution-pipeline", "workitem_id": "wi-1"}

        monkeypatch.setattr(ai_ops_run, "run", _spy)
        return seen

    def test_run_without_task_text_derives_from_spec(self, tmp_path, monkeypatch):
        """positive: run --feature без текста -> движок получает задачу, собранную из спеки."""
        root = _repo(tmp_path)
        _write_spec(root, "wi-1", {
            "goal": {"status": "complete", "content": "добавить estimateReadingMinutes"},
            "acceptance_criteria": {"status": "complete", "content": "пусто -> 0"},
        })
        seen = self._spy_run(monkeypatch)
        ai_ops_cli.main(["run", str(root), "--feature", "wi-1", "--execute",
                         "--signals", '{"task_type":"ENGINEERING","size":"small","risk":"low"}'])
        assert seen.get("task"), "движок получил пустую задачу — сборка из спеки не сработала"
        assert "estimateReadingMinutes" in seen["task"]

    def test_explicit_task_text_is_not_overridden(self, tmp_path, monkeypatch):
        """override: явный текст задачи побеждает — спеку НЕ подставляем поверх."""
        root = _repo(tmp_path)
        _write_spec(root, "wi-1", {
            "goal": {"status": "complete", "content": "из спеки"},
        })
        seen = self._spy_run(monkeypatch)
        ai_ops_cli.main(["run", "явная задача из строки", str(root), "--feature", "wi-1",
                         "--execute",
                         "--signals", '{"task_type":"ENGINEERING","size":"small","risk":"low"}'])
        assert seen.get("task") == "явная задача из строки"

    def test_run_without_spec_reaches_engine_with_empty_task(self, tmp_path, monkeypatch):
        """fail-closed: нет спеки -> задача остаётся пустой, поведение как раньше (не падаем)."""
        root = _repo(tmp_path)
        seen = self._spy_run(monkeypatch)
        ai_ops_cli.main(["run", str(root), "--feature", "wi-nospec", "--execute",
                         "--signals", '{"task_type":"ENGINEERING","size":"small","risk":"low"}'])
        assert seen.get("task") == ""
