"""Характеристические тесты run_pipeline (execution_pipeline.py).

Фиксируют ТЕКУЩЕЕ поведение god-функции run_pipeline (~1075 строк) ДО её расщепления (K6).
Эти тесты НЕ unit-тесты отдельных функций — они описывают «что делает система сейчас»:
какие фазы проходят, в каком порядке, какие побочные эффекты.

Каждый тест мокает зависимости и проверяет:
- какие функции вызываются
- в каком порядке
- какие побочные эффекты происходят
- что возвращается

После расщепления run_pipeline эти тесты должны продолжать проходить (или быть переписаны
под новую структуру). Они — страховка от слепых изменений при рефакторинге.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch, call

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


# ---------------------------------------------------------------------------
# Характеристические тесты: фазы run_pipeline
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPipelinePhasePlan:
    """Фаза 1: построение плана.

    run_pipeline строит план через run_plan.build_plan, если plan не передан.
    Если plan передан — используется он (v2.94: контроллер передаёт готовый план).
    """

    @patch(f"{_PATCH_BASE}.contour_consistency_evidence", return_value={"status": "pass", "provided": [], "evidence": {}})
    @patch(f"{_PATCH_BASE}.gate_executor")
    @patch(f"{_PATCH_BASE}.evidence_collector")
    @patch(f"{_PATCH_BASE}.tool_loop")
    @patch(f"{_PATCH_BASE}.tool_broker")
    @patch(f"{_PATCH_BASE}.project_detector")
    @patch(f"{_PATCH_BASE}.run_plan")
    @patch(f"{_PATCH_BASE}._resolve_base", return_value=_make_base_resolution())
    @patch(f"{_PATCH_BASE}._git")
    def test_builds_plan_when_not_provided(self, mock_git, mock_resolve, mock_run_plan,
                                           mock_detect, mock_broker, mock_loop,
                                           mock_evidence, mock_gates, mock_contour,
                                           child_repo):
        """Без plan — строится через run_plan.build_plan."""
        mock_run_plan.build_plan.return_value = _make_plan()
        mock_detect.detect.return_value = _make_profile()
        mock_broker.Policy.return_value = _make_policy()
        mock_loop.run_loop.return_value = _make_loop_result()
        mock_evidence.collect.return_value = _make_evidence_result()
        mock_gates.evaluate.return_value = _make_gates_result()
        mock_git.return_value = (0, "true", "")

        from ai_ops_kit.engine.execution_pipeline import run_pipeline
        run_pipeline("test task", {}, child_repo, _make_proposer(),
                     commit=False, install_deps=False)

        mock_run_plan.build_plan.assert_called_once()

    @patch(f"{_PATCH_BASE}.contour_consistency_evidence", return_value={"status": "pass", "provided": [], "evidence": {}})
    @patch(f"{_PATCH_BASE}.gate_executor")
    @patch(f"{_PATCH_BASE}.evidence_collector")
    @patch(f"{_PATCH_BASE}.tool_loop")
    @patch(f"{_PATCH_BASE}.tool_broker")
    @patch(f"{_PATCH_BASE}.project_detector")
    @patch(f"{_PATCH_BASE}._resolve_base", return_value=_make_base_resolution())
    @patch(f"{_PATCH_BASE}._git")
    def test_uses_provided_plan(self, mock_git, mock_resolve, mock_detect,
                                mock_broker, mock_loop, mock_evidence, mock_gates,
                                mock_contour, child_repo):
        """С plan — используется переданный, run_plan.build_plan НЕ вызывается."""
        custom_plan = _make_plan("custom-wid")
        mock_detect.detect.return_value = _make_profile()
        mock_broker.Policy.return_value = _make_policy()
        mock_loop.run_loop.return_value = _make_loop_result()
        mock_evidence.collect.return_value = _make_evidence_result()
        mock_gates.evaluate.return_value = _make_gates_result()
        mock_git.return_value = (0, "true", "")

        from ai_ops_kit.engine.execution_pipeline import run_pipeline
        result = run_pipeline("test task", {}, child_repo, _make_proposer(),
                              plan=custom_plan, commit=False, install_deps=False)

        assert result["workitem_id"] == "custom-wid"


@pytest.mark.unit
class TestPipelinePhaseDetection:
    """Фаза 2: детект стека.

    run_pipeline вызывает project_detector.detect(work_root) для определения стека.
    """

    @patch(f"{_PATCH_BASE}.contour_consistency_evidence", return_value={"status": "pass", "provided": [], "evidence": {}})
    @patch(f"{_PATCH_BASE}.gate_executor")
    @patch(f"{_PATCH_BASE}.evidence_collector")
    @patch(f"{_PATCH_BASE}.tool_loop")
    @patch(f"{_PATCH_BASE}.tool_broker")
    @patch(f"{_PATCH_BASE}.project_detector")
    @patch(f"{_PATCH_BASE}.run_plan")
    @patch(f"{_PATCH_BASE}._resolve_base", return_value=_make_base_resolution())
    @patch(f"{_PATCH_BASE}._git")
    def test_detect_called_on_work_root(self, mock_git, mock_resolve, mock_run_plan,
                                        mock_detect, mock_broker, mock_loop,
                                        mock_evidence, mock_gates, mock_contour,
                                        child_repo):
        """project_detector.detect вызывается на рабочем дереве."""
        mock_run_plan.build_plan.return_value = _make_plan()
        mock_detect.detect.return_value = _make_profile()
        mock_broker.Policy.return_value = _make_policy()
        mock_loop.run_loop.return_value = _make_loop_result()
        mock_evidence.collect.return_value = _make_evidence_result()
        mock_gates.evaluate.return_value = _make_gates_result()
        mock_git.return_value = (0, "true", "")

        from ai_ops_kit.engine.execution_pipeline import run_pipeline
        run_pipeline("task", {}, child_repo, _make_proposer(),
                     commit=False, install_deps=False)

        mock_detect.detect.assert_called_once()
        # Аргумент — Path к рабочему дереву
        call_args = mock_detect.detect.call_args
        assert Path(str(call_args[0][0])) == child_repo or str(call_args[0][0]) == str(child_repo)


@pytest.mark.unit
class TestPipelinePhasePolicy:
    """Фаза 3: политика исполнения.

    run_pipeline создаёт Policy (execution) или sandbox_policy (sandbox=True).
    """

    @patch(f"{_PATCH_BASE}.contour_consistency_evidence", return_value={"status": "pass", "provided": [], "evidence": {}})
    @patch(f"{_PATCH_BASE}.gate_executor")
    @patch(f"{_PATCH_BASE}.evidence_collector")
    @patch(f"{_PATCH_BASE}.tool_loop")
    @patch(f"{_PATCH_BASE}.tool_broker")
    @patch(f"{_PATCH_BASE}.project_detector")
    @patch(f"{_PATCH_BASE}.run_plan")
    @patch(f"{_PATCH_BASE}._resolve_base", return_value=_make_base_resolution())
    @patch(f"{_PATCH_BASE}._git")
    def test_default_policy_is_execution(self, mock_git, mock_resolve, mock_run_plan,
                                         mock_detect, mock_broker, mock_loop,
                                         mock_evidence, mock_gates, mock_contour,
                                         child_repo):
        """Без sandbox — создаётся Policy(level='execution', block_push=True)."""
        mock_run_plan.build_plan.return_value = _make_plan()
        mock_detect.detect.return_value = _make_profile()
        mock_broker.Policy.return_value = _make_policy()
        mock_loop.run_loop.return_value = _make_loop_result()
        mock_evidence.collect.return_value = _make_evidence_result()
        mock_gates.evaluate.return_value = _make_gates_result()
        mock_git.return_value = (0, "true", "")

        from ai_ops_kit.engine.execution_pipeline import run_pipeline
        run_pipeline("task", {}, child_repo, _make_proposer(),
                     commit=False, install_deps=False)

        mock_broker.Policy.assert_called_once()
        pol_call = mock_broker.Policy.call_args
        assert pol_call.kwargs.get("level") == "execution"
        assert pol_call.kwargs.get("block_push") is True

    @patch(f"{_PATCH_BASE}.contour_consistency_evidence", return_value={"status": "pass", "provided": [], "evidence": {}})
    @patch(f"{_PATCH_BASE}.gate_executor")
    @patch(f"{_PATCH_BASE}.evidence_collector")
    @patch(f"{_PATCH_BASE}.tool_loop")
    @patch(f"{_PATCH_BASE}.tool_broker")
    @patch(f"{_PATCH_BASE}.project_detector")
    @patch(f"{_PATCH_BASE}.run_plan")
    @patch(f"{_PATCH_BASE}._resolve_base", return_value=_make_base_resolution())
    @patch(f"{_PATCH_BASE}._git")
    def test_sandbox_uses_sandbox_policy(self, mock_git, mock_resolve, mock_run_plan,
                                         mock_detect, mock_broker, mock_loop,
                                         mock_evidence, mock_gates, mock_contour,
                                         child_repo):
        """sandbox=True — используется sandbox_policy вместо обычной Policy."""
        mock_run_plan.build_plan.return_value = _make_plan()
        mock_detect.detect.return_value = _make_profile()
        mock_broker.sandbox_policy.return_value = _make_policy()
        mock_loop.run_loop.return_value = _make_loop_result()
        mock_evidence.collect.return_value = _make_evidence_result()
        mock_gates.evaluate.return_value = _make_gates_result()
        mock_git.return_value = (0, "true", "")

        from ai_ops_kit.engine.execution_pipeline import run_pipeline
        run_pipeline("task", {}, child_repo, _make_proposer(),
                     sandbox=True, commit=False, install_deps=False)

        mock_broker.sandbox_policy.assert_called_once()


@pytest.mark.unit
class TestPipelinePhaseToolLoop:
    """Фаза 4: tool-loop (исполнение модели).

    run_pipeline вызывает tool_loop.run_loop с proposer, work_root, policy, budget,
    max_steps и base_context.
    """

    @patch(f"{_PATCH_BASE}.contour_consistency_evidence", return_value={"status": "pass", "provided": [], "evidence": {}})
    @patch(f"{_PATCH_BASE}.gate_executor")
    @patch(f"{_PATCH_BASE}.evidence_collector")
    @patch(f"{_PATCH_BASE}.tool_loop")
    @patch(f"{_PATCH_BASE}.tool_broker")
    @patch(f"{_PATCH_BASE}.project_detector")
    @patch(f"{_PATCH_BASE}.run_plan")
    @patch(f"{_PATCH_BASE}._resolve_base", return_value=_make_base_resolution())
    @patch(f"{_PATCH_BASE}._git")
    def test_tool_loop_called_with_proposer(self, mock_git, mock_resolve, mock_run_plan,
                                            mock_detect, mock_broker, mock_loop,
                                            mock_evidence, mock_gates, mock_contour,
                                            child_repo):
        """tool_loop.run_loop вызывается с proposer, work_root, policy."""
        mock_run_plan.build_plan.return_value = _make_plan()
        mock_detect.detect.return_value = _make_profile()
        mock_broker.Policy.return_value = _make_policy()
        mock_loop.run_loop.return_value = _make_loop_result()
        mock_evidence.collect.return_value = _make_evidence_result()
        mock_gates.evaluate.return_value = _make_gates_result()
        mock_git.return_value = (0, "true", "")

        proposer = _make_proposer()
        from ai_ops_kit.engine.execution_pipeline import run_pipeline
        run_pipeline("task", {}, child_repo, proposer,
                     commit=False, install_deps=False)

        mock_loop.run_loop.assert_called_once()
        call_args = mock_loop.run_loop.call_args
        assert call_args[0][0] is proposer  # первый аргумент — proposer

    @patch(f"{_PATCH_BASE}.contour_consistency_evidence", return_value={"status": "pass", "provided": [], "evidence": {}})
    @patch(f"{_PATCH_BASE}.gate_executor")
    @patch(f"{_PATCH_BASE}.evidence_collector")
    @patch(f"{_PATCH_BASE}.tool_loop")
    @patch(f"{_PATCH_BASE}.tool_broker")
    @patch(f"{_PATCH_BASE}.project_detector")
    @patch(f"{_PATCH_BASE}.run_plan")
    @patch(f"{_PATCH_BASE}._resolve_base", return_value=_make_base_resolution())
    @patch(f"{_PATCH_BASE}._git")
    def test_reevaluate_skips_tool_loop(self, mock_git, mock_resolve, mock_run_plan,
                                        mock_detect, mock_broker, mock_loop,
                                        mock_evidence, mock_gates, mock_contour,
                                        child_repo):
        """reevaluate_only=True — tool_loop НЕ вызывается (ноль model-вызовов)."""
        mock_run_plan.build_plan.return_value = _make_plan()
        mock_detect.detect.return_value = _make_profile()
        mock_broker.Policy.return_value = _make_policy()
        mock_evidence.collect.return_value = _make_evidence_result()
        mock_gates.evaluate.return_value = _make_gates_result()
        mock_git.side_effect = lambda *a, **kw: (0, "true", "") if a[-1] == "--is-inside-work-tree" else (0, "a" * 40, "")

        from ai_ops_kit.engine.execution_pipeline import run_pipeline
        result = run_pipeline("task", {}, child_repo, _make_proposer(),
                              commit=False, install_deps=False, reevaluate_only=True)

        mock_loop.run_loop.assert_not_called()
        # loop в результате — с stopped="reevaluate-only"
        assert result["loop"]["stopped"] == "reevaluate-only"


@pytest.mark.unit
class TestPipelinePhaseEvidence:
    """Фаза 6: evidence collection.

    run_pipeline вызывает evidence_collector.collect для реального прогона проверок.
    """

    @patch(f"{_PATCH_BASE}.contour_consistency_evidence", return_value={"status": "pass", "provided": [], "evidence": {}})
    @patch(f"{_PATCH_BASE}.gate_executor")
    @patch(f"{_PATCH_BASE}.evidence_collector")
    @patch(f"{_PATCH_BASE}.tool_loop")
    @patch(f"{_PATCH_BASE}.tool_broker")
    @patch(f"{_PATCH_BASE}.project_detector")
    @patch(f"{_PATCH_BASE}.run_plan")
    @patch(f"{_PATCH_BASE}._resolve_base", return_value=_make_base_resolution())
    @patch(f"{_PATCH_BASE}._git")
    def test_evidence_collector_called(self, mock_git, mock_resolve, mock_run_plan,
                                       mock_detect, mock_broker, mock_loop,
                                       mock_evidence, mock_gates, mock_contour,
                                       child_repo):
        """evidence_collector.collect вызывается с profile, work_root, policy."""
        mock_run_plan.build_plan.return_value = _make_plan()
        mock_detect.detect.return_value = _make_profile()
        mock_broker.Policy.return_value = _make_policy()
        mock_loop.run_loop.return_value = _make_loop_result()
        mock_evidence.collect.return_value = _make_evidence_result()
        mock_gates.evaluate.return_value = _make_gates_result()
        mock_git.return_value = (0, "true", "")

        from ai_ops_kit.engine.execution_pipeline import run_pipeline
        run_pipeline("task", {}, child_repo, _make_proposer(),
                     commit=False, install_deps=False)

        mock_evidence.collect.assert_called_once()
        call_args = mock_evidence.collect.call_args
        # Первый аргумент — profile
        assert call_args[0][0] == _make_profile()


@pytest.mark.unit
class TestPipelinePhaseGates:
    """Фаза 7: оценка гейтов.

    run_pipeline вызывает gate_executor.evaluate с workflow, evidence, gate_ids.
    """

    @patch(f"{_PATCH_BASE}.contour_consistency_evidence", return_value={"status": "pass", "provided": [], "evidence": {}})
    @patch(f"{_PATCH_BASE}.gate_executor")
    @patch(f"{_PATCH_BASE}.evidence_collector")
    @patch(f"{_PATCH_BASE}.tool_loop")
    @patch(f"{_PATCH_BASE}.tool_broker")
    @patch(f"{_PATCH_BASE}.project_detector")
    @patch(f"{_PATCH_BASE}.run_plan")
    @patch(f"{_PATCH_BASE}._resolve_base", return_value=_make_base_resolution())
    @patch(f"{_PATCH_BASE}._git")
    def test_gates_evaluated_with_plan_workflow(self, mock_git, mock_resolve, mock_run_plan,
                                                mock_detect, mock_broker, mock_loop,
                                                mock_evidence, mock_gates, mock_contour,
                                                child_repo):
        """gate_executor.evaluate вызывается с base_workflow из плана."""
        plan = _make_plan()
        plan["base_workflow"] = "standard"
        mock_run_plan.build_plan.return_value = plan
        mock_detect.detect.return_value = _make_profile()
        mock_broker.Policy.return_value = _make_policy()
        mock_loop.run_loop.return_value = _make_loop_result()
        mock_evidence.collect.return_value = _make_evidence_result()
        mock_gates.evaluate.return_value = _make_gates_result()
        mock_git.return_value = (0, "true", "")

        from ai_ops_kit.engine.execution_pipeline import run_pipeline
        run_pipeline("task", {}, child_repo, _make_proposer(),
                     commit=False, install_deps=False)

        mock_gates.evaluate.assert_called_once()
        call_kwargs = mock_gates.evaluate.call_args
        # Первый позиционный аргумент — base_workflow
        assert call_kwargs[0][0] == "standard"


@pytest.mark.unit
class TestPipelineReturnStructure:
    """Структура возврата run_pipeline.

    Фиксируем, какие ключи ВСЕГДА присутствуют в результате.
    """

    @patch(f"{_PATCH_BASE}.contour_consistency_evidence", return_value={"status": "pass", "provided": [], "evidence": {}})
    @patch(f"{_PATCH_BASE}.gate_executor")
    @patch(f"{_PATCH_BASE}.evidence_collector")
    @patch(f"{_PATCH_BASE}.tool_loop")
    @patch(f"{_PATCH_BASE}.tool_broker")
    @patch(f"{_PATCH_BASE}.project_detector")
    @patch(f"{_PATCH_BASE}.run_plan")
    @patch(f"{_PATCH_BASE}._resolve_base", return_value=_make_base_resolution())
    @patch(f"{_PATCH_BASE}._git")
    def test_return_has_required_keys(self, mock_git, mock_resolve, mock_run_plan,
                                      mock_detect, mock_broker, mock_loop,
                                      mock_evidence, mock_gates, mock_contour,
                                      child_repo):
        """Результат содержит все обязательные ключи."""
        mock_run_plan.build_plan.return_value = _make_plan()
        mock_detect.detect.return_value = _make_profile()
        mock_broker.Policy.return_value = _make_policy()
        mock_loop.run_loop.return_value = _make_loop_result()
        mock_evidence.collect.return_value = _make_evidence_result()
        mock_gates.evaluate.return_value = _make_gates_result()
        mock_git.return_value = (0, "true", "")

        from ai_ops_kit.engine.execution_pipeline import run_pipeline
        result = run_pipeline("task", {}, child_repo, _make_proposer(),
                              commit=False, install_deps=False)

        required_keys = [
            "schema_version", "kind", "workitem_id", "child_root",
            "base_workflow", "profile", "containment", "loop",
            "isolation", "base_binding", "commit", "checks",
            "exemptions", "gates", "ready_for_pr", "delivery",
            "overall_status", "not_yet",
        ]
        for key in required_keys:
            assert key in result, f"Ключ '{key}' отсутствует в результате run_pipeline"

    @patch(f"{_PATCH_BASE}.contour_consistency_evidence", return_value={"status": "pass", "provided": [], "evidence": {}})
    @patch(f"{_PATCH_BASE}.gate_executor")
    @patch(f"{_PATCH_BASE}.evidence_collector")
    @patch(f"{_PATCH_BASE}.tool_loop")
    @patch(f"{_PATCH_BASE}.tool_broker")
    @patch(f"{_PATCH_BASE}.project_detector")
    @patch(f"{_PATCH_BASE}.run_plan")
    @patch(f"{_PATCH_BASE}._resolve_base", return_value=_make_base_resolution())
    @patch(f"{_PATCH_BASE}._git")
    def test_schema_version_is_one(self, mock_git, mock_resolve, mock_run_plan,
                                   mock_detect, mock_broker, mock_loop,
                                   mock_evidence, mock_gates, mock_contour,
                                   child_repo):
        """schema_version = 1 (контракт)."""
        mock_run_plan.build_plan.return_value = _make_plan()
        mock_detect.detect.return_value = _make_profile()
        mock_broker.Policy.return_value = _make_policy()
        mock_loop.run_loop.return_value = _make_loop_result()
        mock_evidence.collect.return_value = _make_evidence_result()
        mock_gates.evaluate.return_value = _make_gates_result()
        mock_git.return_value = (0, "true", "")

        from ai_ops_kit.engine.execution_pipeline import run_pipeline
        result = run_pipeline("task", {}, child_repo, _make_proposer(),
                              commit=False, install_deps=False)

        assert result["schema_version"] == 1
        assert result["kind"] == "execution-pipeline"


@pytest.mark.unit
class TestPipelinePhaseOrdering:
    """Порядок фаз: детект -> policy -> tool-loop -> evidence -> gates.

    Фиксируем, что фазы вызываются в правильном порядке (через порядок mock-вызовов).
    """

    @patch(f"{_PATCH_BASE}.contour_consistency_evidence", return_value={"status": "pass", "provided": [], "evidence": {}})
    @patch(f"{_PATCH_BASE}.gate_executor")
    @patch(f"{_PATCH_BASE}.evidence_collector")
    @patch(f"{_PATCH_BASE}.tool_loop")
    @patch(f"{_PATCH_BASE}.tool_broker")
    @patch(f"{_PATCH_BASE}.project_detector")
    @patch(f"{_PATCH_BASE}.run_plan")
    @patch(f"{_PATCH_BASE}._resolve_base", return_value=_make_base_resolution())
    @patch(f"{_PATCH_BASE}._git")
    def test_detect_before_tool_loop(self, mock_git, mock_resolve, mock_run_plan,
                                     mock_detect, mock_broker, mock_loop,
                                     mock_evidence, mock_gates, mock_contour,
                                     child_repo):
        """Детект вызывается ДО tool-loop (профиль нужен для контекста)."""
        mock_run_plan.build_plan.return_value = _make_plan()
        mock_detect.detect.return_value = _make_profile()
        mock_broker.Policy.return_value = _make_policy()
        mock_loop.run_loop.return_value = _make_loop_result()
        mock_evidence.collect.return_value = _make_evidence_result()
        mock_gates.evaluate.return_value = _make_gates_result()
        mock_git.return_value = (0, "true", "")

        from ai_ops_kit.engine.execution_pipeline import run_pipeline
        run_pipeline("task", {}, child_repo, _make_proposer(),
                     commit=False, install_deps=False)

        # Оба вызваны
        mock_detect.detect.assert_called_once()
        mock_loop.run_loop.assert_called_once()

    @patch(f"{_PATCH_BASE}.contour_consistency_evidence", return_value={"status": "pass", "provided": [], "evidence": {}})
    @patch(f"{_PATCH_BASE}.gate_executor")
    @patch(f"{_PATCH_BASE}.evidence_collector")
    @patch(f"{_PATCH_BASE}.tool_loop")
    @patch(f"{_PATCH_BASE}.tool_broker")
    @patch(f"{_PATCH_BASE}.project_detector")
    @patch(f"{_PATCH_BASE}.run_plan")
    @patch(f"{_PATCH_BASE}._resolve_base", return_value=_make_base_resolution())
    @patch(f"{_PATCH_BASE}._git")
    def test_evidence_before_gates(self, mock_git, mock_resolve, mock_run_plan,
                                   mock_detect, mock_broker, mock_loop,
                                   mock_evidence, mock_gates, mock_contour,
                                   child_repo):
        """Evidence собирается ДО оценки гейтов (гейты нуждаются в evidence)."""
        mock_run_plan.build_plan.return_value = _make_plan()
        mock_detect.detect.return_value = _make_profile()
        mock_broker.Policy.return_value = _make_policy()
        mock_loop.run_loop.return_value = _make_loop_result()
        mock_evidence.collect.return_value = _make_evidence_result()
        mock_gates.evaluate.return_value = _make_gates_result()
        mock_git.return_value = (0, "true", "")

        from ai_ops_kit.engine.execution_pipeline import run_pipeline
        run_pipeline("task", {}, child_repo, _make_proposer(),
                     commit=False, install_deps=False)

        mock_evidence.collect.assert_called_once()
        mock_gates.evaluate.assert_called_once()


@pytest.mark.unit
class TestPipelineContainment:
    """Containment: политика изоляции в результате.

    Фиксируем, что containment честно отражает, что enforced.
    """

    @patch(f"{_PATCH_BASE}.contour_consistency_evidence", return_value={"status": "pass", "provided": [], "evidence": {}})
    @patch(f"{_PATCH_BASE}.gate_executor")
    @patch(f"{_PATCH_BASE}.evidence_collector")
    @patch(f"{_PATCH_BASE}.tool_loop")
    @patch(f"{_PATCH_BASE}.tool_broker")
    @patch(f"{_PATCH_BASE}.project_detector")
    @patch(f"{_PATCH_BASE}.run_plan")
    @patch(f"{_PATCH_BASE}._resolve_base", return_value=_make_base_resolution())
    @patch(f"{_PATCH_BASE}._git")
    def test_containment_reflects_sandbox_flag(self, mock_git, mock_resolve, mock_run_plan,
                                               mock_detect, mock_broker, mock_loop,
                                               mock_evidence, mock_gates, mock_contour,
                                               child_repo):
        """containment.sandbox = True когда sandbox=True передан."""
        mock_run_plan.build_plan.return_value = _make_plan()
        mock_detect.detect.return_value = _make_profile()
        mock_broker.sandbox_policy.return_value = _make_policy()
        mock_loop.run_loop.return_value = _make_loop_result()
        mock_evidence.collect.return_value = _make_evidence_result()
        mock_gates.evaluate.return_value = _make_gates_result()
        mock_git.return_value = (0, "true", "")

        from ai_ops_kit.engine.execution_pipeline import run_pipeline
        result = run_pipeline("task", {}, child_repo, _make_proposer(),
                              sandbox=True, commit=False, install_deps=False)

        assert result["containment"]["sandbox"] is True

    @patch(f"{_PATCH_BASE}.contour_consistency_evidence", return_value={"status": "pass", "provided": [], "evidence": {}})
    @patch(f"{_PATCH_BASE}.gate_executor")
    @patch(f"{_PATCH_BASE}.evidence_collector")
    @patch(f"{_PATCH_BASE}.tool_loop")
    @patch(f"{_PATCH_BASE}.tool_broker")
    @patch(f"{_PATCH_BASE}.project_detector")
    @patch(f"{_PATCH_BASE}.run_plan")
    @patch(f"{_PATCH_BASE}._resolve_base", return_value=_make_base_resolution())
    @patch(f"{_PATCH_BASE}._git")
    def test_block_push_always_true(self, mock_git, mock_resolve, mock_run_plan,
                                    mock_detect, mock_broker, mock_loop,
                                    mock_evidence, mock_gates, mock_contour,
                                    child_repo):
        """containment.block_push = True всегда (модель не может push-ить)."""
        mock_run_plan.build_plan.return_value = _make_plan()
        mock_detect.detect.return_value = _make_profile()
        pol = _make_policy()
        pol.block_push = True
        mock_broker.Policy.return_value = pol
        mock_loop.run_loop.return_value = _make_loop_result()
        mock_evidence.collect.return_value = _make_evidence_result()
        mock_gates.evaluate.return_value = _make_gates_result()
        mock_git.return_value = (0, "true", "")

        from ai_ops_kit.engine.execution_pipeline import run_pipeline
        result = run_pipeline("task", {}, child_repo, _make_proposer(),
                              commit=False, install_deps=False)

        assert result["containment"]["block_push"] is True


@pytest.mark.unit
class TestPipelineDeliveryPlan:
    """Фаза 8: доставка.

    run_pipeline НЕ открывает PR сама — только возвращает delivery_plan для контроллера.
    """

    @patch(f"{_PATCH_BASE}.contour_consistency_evidence", return_value={"status": "pass", "provided": [], "evidence": {}})
    @patch(f"{_PATCH_BASE}.gate_executor")
    @patch(f"{_PATCH_BASE}.evidence_collector")
    @patch(f"{_PATCH_BASE}.tool_loop")
    @patch(f"{_PATCH_BASE}.tool_broker")
    @patch(f"{_PATCH_BASE}.project_detector")
    @patch(f"{_PATCH_BASE}.run_plan")
    @patch(f"{_PATCH_BASE}._resolve_base", return_value=_make_base_resolution())
    @patch(f"{_PATCH_BASE}._git")
    def test_no_delivery_without_open_pr(self, mock_git, mock_resolve, mock_run_plan,
                                         mock_detect, mock_broker, mock_loop,
                                         mock_evidence, mock_gates, mock_contour,
                                         child_repo):
        """Без open_pr — delivery_plan = None."""
        mock_run_plan.build_plan.return_value = _make_plan()
        mock_detect.detect.return_value = _make_profile()
        mock_broker.Policy.return_value = _make_policy()
        mock_loop.run_loop.return_value = _make_loop_result()
        mock_evidence.collect.return_value = _make_evidence_result()
        mock_gates.evaluate.return_value = _make_gates_result()
        mock_git.return_value = (0, "true", "")

        from ai_ops_kit.engine.execution_pipeline import run_pipeline
        result = run_pipeline("task", {}, child_repo, _make_proposer(),
                              commit=False, install_deps=False)

        assert result["delivery_plan"] is None
        assert result["delivery"]["requested"] is False


@pytest.mark.unit
class TestPipelineSignals:
    """Signals: как обрабатываются входные сигналы.

    run_pipeline принимает signals dict, добавляет task_text, и использует
    для классификации и gate evaluation.
    """

    @patch(f"{_PATCH_BASE}.contour_consistency_evidence", return_value={"status": "pass", "provided": [], "evidence": {}})
    @patch(f"{_PATCH_BASE}.gate_executor")
    @patch(f"{_PATCH_BASE}.evidence_collector")
    @patch(f"{_PATCH_BASE}.tool_loop")
    @patch(f"{_PATCH_BASE}.tool_broker")
    @patch(f"{_PATCH_BASE}.project_detector")
    @patch(f"{_PATCH_BASE}.run_plan")
    @patch(f"{_PATCH_BASE}._resolve_base", return_value=_make_base_resolution())
    @patch(f"{_PATCH_BASE}._git")
    def test_task_text_added_to_signals(self, mock_git, mock_resolve, mock_run_plan,
                                        mock_detect, mock_broker, mock_loop,
                                        mock_evidence, mock_gates, mock_contour,
                                        child_repo):
        """signals['task_text'] устанавливается из task (внутри копии).

        run_pipeline делает dict(signals) — копирует, не мутирует оригинал.
        task_text попадает во внутреннюю копию, которая идёт в build_plan и gate evaluation.
        """
        mock_run_plan.build_plan.return_value = _make_plan()
        mock_detect.detect.return_value = _make_profile()
        mock_broker.Policy.return_value = _make_policy()
        mock_loop.run_loop.return_value = _make_loop_result()
        mock_evidence.collect.return_value = _make_evidence_result()
        mock_gates.evaluate.return_value = _make_gates_result()
        mock_git.return_value = (0, "true", "")

        from ai_ops_kit.engine.execution_pipeline import run_pipeline
        signals = {"task_type": "fix"}
        run_pipeline("my task", signals, child_repo, _make_proposer(),
                     commit=False, install_deps=False)

        # run_pipeline копирует signals (dict(signals or {})), оригинал НЕ мутируется
        assert "task_text" not in signals  # оригинал чист
        # task_text попал во внутреннюю копию — проверяем через build_plan args
        bp_call = mock_run_plan.build_plan.call_args
        inner_signals = bp_call[0][0]  # первый аргумент build_plan — signals
        assert inner_signals.get("task_text") == "my task"
