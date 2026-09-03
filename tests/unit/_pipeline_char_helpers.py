"""Общие хелперы/фикстуры характеристических тестов run_pipeline (не собирается pytest).

Вынесены из test_pipeline_characterization.py при тематическом расщеплении файла: модульные
фабрики моков, фикстура child_repo, константы путей патчинга и _committing_loop. Импортируются
обоими собираемыми файлами (test_pipeline_characterization*.py).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Фикстуры: минимальные моки для всех зависимостей run_pipeline
# ---------------------------------------------------------------------------

def _make_plan(workitem_id="test-feature"):
    """Минимальный план, который ожидает run_pipeline."""
    return {
        "workitem_id": workitem_id,
        "base_workflow": "quick",
        "gates": {"implementation_verification": {}, "code_review": {}},
    }


def _make_proposer():
    """Мок предложителя (модель), возвращающий «нет правок» (done за 0 шагов)."""
    proposer = MagicMock()
    return proposer


def _make_policy():
    """Мок политики исполнения."""
    pol = MagicMock()
    pol.level = "execution"
    pol.block_push = True
    pol.shell_mode = "allowlist"
    pol.allow_network = False
    pol.shell_path_guard = False
    pol.shell_scope_guard = False
    pol.write_scope = None
    return pol


def _make_profile():
    """Мок профиля стека (project_detector.detect)."""
    return {"stacks": [{"language": "python"}], "undetermined": []}


def _make_loop_result(stopped="done", steps=0):
    """Мок результата tool-loop."""
    return {
        "schema_version": 1,
        "kind": "tool-loop-report",
        "stopped": stopped,
        "steps": steps,
        "model_calls": steps,
        "executed": [],
        "denied": [],
        "evidence": [],
        "transcript": [],
    }


def _make_evidence_result():
    """Мок результата evidence_collector.collect."""
    return {
        "checks": {"build": {"status": "pass"}, "tests": {"status": "pass"}},
        "gate_evidence": {},
        "not_applicable": [],
        "tests_absent": False,
        "revision": "abc123" * 6 + "abcd",  # 40 chars
    }


def _make_gates_result():
    """Мок результата gate_executor.evaluate."""
    return {
        "evaluated_gates": ["implementation_verification"],
        "unmet_gates": [],
        "blocked": False,
        "closure": {"counts": {"validator": 1}, "judged_or_human": []},
        "gate_results": {},
    }


def _make_base_resolution():
    """Мок результата _resolve_base."""
    sha = "a" * 40
    return {"base_ref": "main", "base_sha": sha, "mode": "auto",
            "resolved": True, "source": "upstream", "reason": None}


@pytest.fixture
def child_repo(tmp_path):
    """Минимальный git-репозиторий для тестов pipeline."""
    import subprocess
    child = tmp_path / "child"
    child.mkdir()
    subprocess.run(["git", "-C", str(child), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(child), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(child), "config", "user.name", "t"], check=True)
    (child / "README.md").write_text("# test\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(child), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(child), "commit", "-q", "-m", "init"], check=True)
    return child


# ---------------------------------------------------------------------------
# Модульные пути для патчинга
# ---------------------------------------------------------------------------

_PATCH_BASE = "ai_ops_kit.engine.execution_pipeline"
# deep-cut: кластер изоляции/окружения/сборки evidence вынесен в pipeline_setup. Его коллабораторы
# (evidence_collector, _resolve_base) резолвятся из globals ЭТОГО модуля — подмену ставим здесь, а не
# на реэкспорте в execution_pipeline (иначе она не дойдёт до _setup_isolation/_assemble_evidence).
_SETUP_BASE = "ai_ops_kit.engine.pipeline_setup"


def _committing_loop(files):
    """side_effect для tool_loop.run_loop: пишет files={rel: content} в work_root и
    возвращает stopped=done -> появляется реальная правка -> коммит на ветке."""
    def _side(proposer, work_root, pol, **kw):
        for rel, content in files.items():
            (Path(work_root) / rel).write_text(content, encoding="utf-8")
        return _make_loop_result(stopped="done", steps=1)
    return _side
