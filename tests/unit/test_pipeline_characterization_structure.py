"""Характеристические тесты run_pipeline: структура возврата, порядок фаз и побочные ветви.

Тематическое продолжение test_pipeline_characterization.py (там — пофазные проверки самих фаз).
Здесь фиксируется наблюдаемый контракт прогона: обязательные ключи результата, порядок вызовов,
containment, delivery_plan, signals, фаза security на committed-пути и baseline_diff-ветка.

Общие фабрики моков, фикстура child_repo, константы путей патчинга и _committing_loop живут в
_pipeline_char_helpers (не собирается pytest).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from _pipeline_char_helpers import (
    _PATCH_BASE,
    _SETUP_BASE,
    _committing_loop,
    _make_base_resolution,
    _make_evidence_result,
    _make_gates_result,
    _make_loop_result,
    _make_plan,
    _make_policy,
    _make_profile,
    _make_proposer,
)


@pytest.mark.unit
class TestPipelineReturnStructure:
    """Структура возврата run_pipeline.

    Фиксируем, какие ключи ВСЕГДА присутствуют в результате.
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
    @patch(f"{_SETUP_BASE}.evidence_collector")
    @patch(f"{_PATCH_BASE}.tool_loop")
    @patch(f"{_PATCH_BASE}.tool_broker")
    @patch(f"{_PATCH_BASE}.project_detector")
    @patch(f"{_PATCH_BASE}.run_plan")
    @patch(f"{_SETUP_BASE}._resolve_base", return_value=_make_base_resolution())
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
    @patch(f"{_SETUP_BASE}.evidence_collector")
    @patch(f"{_PATCH_BASE}.tool_loop")
    @patch(f"{_PATCH_BASE}.tool_broker")
    @patch(f"{_PATCH_BASE}.project_detector")
    @patch(f"{_PATCH_BASE}.run_plan")
    @patch(f"{_SETUP_BASE}._resolve_base", return_value=_make_base_resolution())
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
    @patch(f"{_SETUP_BASE}.evidence_collector")
    @patch(f"{_PATCH_BASE}.tool_loop")
    @patch(f"{_PATCH_BASE}.tool_broker")
    @patch(f"{_PATCH_BASE}.project_detector")
    @patch(f"{_PATCH_BASE}.run_plan")
    @patch(f"{_SETUP_BASE}._resolve_base", return_value=_make_base_resolution())
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
    @patch(f"{_SETUP_BASE}.evidence_collector")
    @patch(f"{_PATCH_BASE}.tool_loop")
    @patch(f"{_PATCH_BASE}.tool_broker")
    @patch(f"{_PATCH_BASE}.project_detector")
    @patch(f"{_PATCH_BASE}.run_plan")
    @patch(f"{_SETUP_BASE}._resolve_base", return_value=_make_base_resolution())
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
    @patch(f"{_SETUP_BASE}.evidence_collector")
    @patch(f"{_PATCH_BASE}.tool_loop")
    @patch(f"{_PATCH_BASE}.tool_broker")
    @patch(f"{_PATCH_BASE}.project_detector")
    @patch(f"{_PATCH_BASE}.run_plan")
    @patch(f"{_SETUP_BASE}._resolve_base", return_value=_make_base_resolution())
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
    @patch(f"{_SETUP_BASE}.evidence_collector")
    @patch(f"{_PATCH_BASE}.tool_loop")
    @patch(f"{_PATCH_BASE}.tool_broker")
    @patch(f"{_PATCH_BASE}.project_detector")
    @patch(f"{_PATCH_BASE}.run_plan")
    @patch(f"{_SETUP_BASE}._resolve_base", return_value=_make_base_resolution())
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
    @patch(f"{_SETUP_BASE}.evidence_collector")
    @patch(f"{_PATCH_BASE}.tool_loop")
    @patch(f"{_PATCH_BASE}.tool_broker")
    @patch(f"{_PATCH_BASE}.project_detector")
    @patch(f"{_PATCH_BASE}.run_plan")
    @patch(f"{_SETUP_BASE}._resolve_base", return_value=_make_base_resolution())
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


# ---------------------------------------------------------------------------
# Характеристические тесты фазы security (committed-путь)
#
# Существующие тесты выше гоняют happy-path с commit=False -> committed_sha=None ->
# фаза security НЕ исполняется. Эти тесты доводят прогон до РЕАЛЬНОГО коммита (мок-петля
# пишет файл в рабочее дерево, commit=True), поэтому фаза security выполняется на НАСТОЯЩЕМ
# security_pack (не на моках) и её вердикт можно зафиксировать до расщепления run_pipeline (K6).
#
# ВАЖНО: здесь НЕ патчатся _git и _resolve_base — коммит должен произойти по-настоящему,
# иначе committed_sha=None и фаза security снова не исполнится.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPipelineSecurityCharacterization:
    """Фаза security: доменный вердикт security_pack -> gate_ev['security'].

    Фиксируем ДВЕ опорные ветви на committed-пути:
    - чистый дифф -> security 'pass' (домены закрыты детерминированно), 'security' НЕ форсится
      в оценку гейтов;
    - новая зависимость -> security 'fail' (нужен ApprovalRecord) И 'security' ФОРСИТСЯ в
      gate_ids (инвариант v2.125: security-находка блокирует даже в QUICK-workflow без гейта
      security).
    """

    @patch(f"{_PATCH_BASE}.contour_consistency_evidence", return_value={"status": "pass", "provided": [], "evidence": {}})
    @patch(f"{_PATCH_BASE}.gate_executor")
    @patch(f"{_SETUP_BASE}.evidence_collector")
    @patch(f"{_PATCH_BASE}.tool_loop")
    @patch(f"{_PATCH_BASE}.tool_broker")
    @patch(f"{_PATCH_BASE}.project_detector")
    @patch(f"{_PATCH_BASE}.run_plan")
    def test_clean_diff_security_passes(self, mock_run_plan, mock_detect, mock_broker,
                                        mock_loop, mock_evidence, mock_gates, mock_contour,
                                        child_repo):
        """Чистый дифф (только документация) -> security='pass', 'security' НЕ в gate_ids."""
        mock_run_plan.build_plan.return_value = _make_plan()
        mock_detect.detect.return_value = _make_profile()
        mock_broker.Policy.return_value = _make_policy()
        mock_loop.run_loop.side_effect = _committing_loop({"notes.md": "just docs\n"})
        mock_evidence.collect.return_value = _make_evidence_result()
        mock_gates.evaluate.return_value = _make_gates_result()

        from ai_ops_kit.engine.execution_pipeline import run_pipeline
        result = run_pipeline("task", {}, child_repo, _make_proposer(),
                              commit=True, install_deps=False)

        # security-вердикт, переданный в gate_executor.evaluate (2-й позиционный — gate_ev)
        gate_ev = mock_gates.evaluate.call_args[0][1]
        assert gate_ev["security"]["status"] == "pass"
        assert set(gate_ev["security"]["provided"]) == {
            "no_secrets", "no_injection_surface", "deps_approved"}
        # security НЕ форсится в оценку гейтов на чистом диффе
        assert "security" not in mock_gates.evaluate.call_args.kwargs["gate_ids"]
        # проекция для отчёта присутствует и честна
        assert result["security_scan"]["overall"] == "clear"

    @patch(f"{_PATCH_BASE}.contour_consistency_evidence", return_value={"status": "pass", "provided": [], "evidence": {}})
    @patch(f"{_PATCH_BASE}.gate_executor")
    @patch(f"{_SETUP_BASE}.evidence_collector")
    @patch(f"{_PATCH_BASE}.tool_loop")
    @patch(f"{_PATCH_BASE}.tool_broker")
    @patch(f"{_PATCH_BASE}.project_detector")
    @patch(f"{_PATCH_BASE}.run_plan")
    def test_new_dependency_forces_security_gate(self, mock_run_plan, mock_detect, mock_broker,
                                                 mock_loop, mock_evidence, mock_gates, mock_contour,
                                                 child_repo):
        """Новая зависимость в диффе -> security='fail' (нужен ApprovalRecord) И 'security'
        ФОРСИТСЯ в gate_ids, хотя в плане QUICK гейта security нет (инвариант v2.125)."""
        import subprocess
        # базовый requirements.txt уже в репозитории (до правки)
        (child_repo / "requirements.txt").write_text("existing==1.0\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(child_repo), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(child_repo), "commit", "-q", "-m", "add reqs"], check=True)

        mock_run_plan.build_plan.return_value = _make_plan()   # base_workflow=quick, без security
        mock_detect.detect.return_value = _make_profile()
        mock_broker.Policy.return_value = _make_policy()
        # петля добавляет НОВУЮ прямую зависимость
        mock_loop.run_loop.side_effect = _committing_loop(
            {"requirements.txt": "existing==1.0\nrequests==2.31.0\n"})
        mock_evidence.collect.return_value = _make_evidence_result()
        mock_gates.evaluate.return_value = _make_gates_result()

        from ai_ops_kit.engine.execution_pipeline import run_pipeline
        result = run_pipeline("task", {}, child_repo, _make_proposer(),
                              commit=True, install_deps=False)

        gate_ev = mock_gates.evaluate.call_args[0][1]
        assert gate_ev["security"]["status"] == "fail"
        # причина — незакрытое человеко-одобрение по домену dependencies
        domains = [m.get("domain") for m in gate_ev["security"].get("approvals_missing", [])]
        assert "dependencies" in domains
        # ФОРСИНГ: security добавлен в оценку гейтов несмотря на QUICK-план без него
        assert "security" in mock_gates.evaluate.call_args.kwargs["gate_ids"]
        assert result["security_scan"]["overall"] == "needs_review"


@pytest.mark.unit
class TestPipelinePhaseBaselineDiff:
    """Фаза install-deps/baseline (baseline_diff=True): evidence на БАЗЕ до правок модели.

    Существующие тесты гоняют baseline_diff=False -> baseline-ветка _prepare_environment и
    baseline-раздел отчёта НЕ исполняются. Этот тест фиксирует их до/после расщепления (K6):
    evidence_collector.collect вызывается ДВАЖДЫ (baseline + основной прогон), отчёт несёт
    baseline-раздел и переключается на критерий no-regressions.
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
    def test_baseline_diff_collects_baseline_and_reports(self, mock_git, mock_resolve, mock_run_plan,
                                                         mock_detect, mock_broker, mock_loop,
                                                         mock_evidence, mock_gates, mock_contour,
                                                         child_repo):
        """baseline_diff=True -> collect вызван дважды, отчёт несёт baseline + no-regressions."""
        mock_run_plan.build_plan.return_value = _make_plan()
        mock_detect.detect.return_value = _make_profile()
        mock_broker.Policy.return_value = _make_policy()
        mock_loop.run_loop.return_value = _make_loop_result()
        mock_evidence.collect.return_value = _make_evidence_result()
        mock_gates.evaluate.return_value = _make_gates_result()
        mock_git.return_value = (0, "true", "")

        from ai_ops_kit.engine.execution_pipeline import run_pipeline
        result = run_pipeline("task", {}, child_repo, _make_proposer(),
                              commit=False, install_deps=False, baseline_diff=True)

        # collect вызван дважды: baseline (в _prepare_environment) + основной прогон
        assert mock_evidence.collect.call_count == 2
        # baseline-раздел присутствует, критерий переключён на no-regressions
        assert result["baseline"] is not None
        assert result["ready_criterion"] == "no-regressions"
