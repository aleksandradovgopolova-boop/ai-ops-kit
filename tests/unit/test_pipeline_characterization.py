"""Характеристические тесты run_pipeline (execution_pipeline.py) — пофазные проверки.

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

Тематически расщеплён: структура возврата, порядок фаз, containment, delivery, signals, security
и baseline-diff вынесены в test_pipeline_characterization_structure.py. Общие фабрики моков,
фикстура child_repo и константы путей патчинга — в _pipeline_char_helpers (не собирается pytest).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from _pipeline_char_helpers import (
    _PATCH_BASE,
    _SETUP_BASE,
    _make_base_resolution,
    _make_evidence_result,
    _make_gates_result,
    _make_loop_result,
    _make_plan,
    _make_policy,
    _make_profile,
    _make_proposer,
)


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
    @patch(f"{_SETUP_BASE}.evidence_collector")
    @patch(f"{_PATCH_BASE}.tool_loop")
    @patch(f"{_PATCH_BASE}.tool_broker")
    @patch(f"{_PATCH_BASE}.project_detector")
    @patch(f"{_PATCH_BASE}.run_plan")
    @patch(f"{_SETUP_BASE}._resolve_base", return_value=_make_base_resolution())
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
    @patch(f"{_SETUP_BASE}.evidence_collector")
    @patch(f"{_PATCH_BASE}.tool_loop")
    @patch(f"{_PATCH_BASE}.tool_broker")
    @patch(f"{_PATCH_BASE}.project_detector")
    @patch(f"{_SETUP_BASE}._resolve_base", return_value=_make_base_resolution())
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
    @patch(f"{_SETUP_BASE}.evidence_collector")
    @patch(f"{_PATCH_BASE}.tool_loop")
    @patch(f"{_PATCH_BASE}.tool_broker")
    @patch(f"{_PATCH_BASE}.project_detector")
    @patch(f"{_PATCH_BASE}.run_plan")
    @patch(f"{_SETUP_BASE}._resolve_base", return_value=_make_base_resolution())
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
    @patch(f"{_SETUP_BASE}.evidence_collector")
    @patch(f"{_PATCH_BASE}.tool_loop")
    @patch(f"{_PATCH_BASE}.tool_broker")
    @patch(f"{_PATCH_BASE}.project_detector")
    @patch(f"{_PATCH_BASE}.run_plan")
    @patch(f"{_SETUP_BASE}._resolve_base", return_value=_make_base_resolution())
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
    @patch(f"{_SETUP_BASE}.evidence_collector")
    @patch(f"{_PATCH_BASE}.tool_loop")
    @patch(f"{_PATCH_BASE}.tool_broker")
    @patch(f"{_PATCH_BASE}.project_detector")
    @patch(f"{_PATCH_BASE}.run_plan")
    @patch(f"{_SETUP_BASE}._resolve_base", return_value=_make_base_resolution())
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
    @patch(f"{_SETUP_BASE}.evidence_collector")
    @patch(f"{_PATCH_BASE}.tool_loop")
    @patch(f"{_PATCH_BASE}.tool_broker")
    @patch(f"{_PATCH_BASE}.project_detector")
    @patch(f"{_PATCH_BASE}.run_plan")
    @patch(f"{_SETUP_BASE}._resolve_base", return_value=_make_base_resolution())
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
    @patch(f"{_SETUP_BASE}.evidence_collector")
    @patch(f"{_PATCH_BASE}.tool_loop")
    @patch(f"{_PATCH_BASE}.tool_broker")
    @patch(f"{_PATCH_BASE}.project_detector")
    @patch(f"{_PATCH_BASE}.run_plan")
    @patch(f"{_SETUP_BASE}._resolve_base", return_value=_make_base_resolution())
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
    @patch(f"{_SETUP_BASE}.evidence_collector")
    @patch(f"{_PATCH_BASE}.tool_loop")
    @patch(f"{_PATCH_BASE}.tool_broker")
    @patch(f"{_PATCH_BASE}.project_detector")
    @patch(f"{_PATCH_BASE}.run_plan")
    @patch(f"{_SETUP_BASE}._resolve_base", return_value=_make_base_resolution())
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
    @patch(f"{_SETUP_BASE}.evidence_collector")
    @patch(f"{_PATCH_BASE}.tool_loop")
    @patch(f"{_PATCH_BASE}.tool_broker")
    @patch(f"{_PATCH_BASE}.project_detector")
    @patch(f"{_PATCH_BASE}.run_plan")
    @patch(f"{_SETUP_BASE}._resolve_base", return_value=_make_base_resolution())
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
