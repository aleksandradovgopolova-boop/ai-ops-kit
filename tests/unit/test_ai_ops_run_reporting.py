"""Юнит-тесты ai_ops_run: отчётность и контекст-артефакты прогона (reporting)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT / "tools"))

from ai_ops_kit.engine import ai_ops_run

from _ai_ops_run_helpers import _git_init_commit


@pytest.mark.critical_path
@pytest.mark.unit
class TestReviewFixContext:
    """Tests for _review_fix_context — blocker context for writer iteration."""

    def test_returns_none_when_ready(self):
        """ready_for_pr=True -> no fix context needed."""
        report = {"ready_for_pr": True}
        assert ai_ops_run._review_fix_context(report) is None

    def test_returns_none_for_non_dict(self):
        """Non-dict input -> None."""
        assert ai_ops_run._review_fix_context(None) is None
        assert ai_ops_run._review_fix_context("string") is None

    def test_returns_none_for_preflight_blocked(self):
        """blocked-preflight -> not model-fixable -> None."""
        report = {"ready_for_pr": False, "overall_status": "blocked-preflight"}
        assert ai_ops_run._review_fix_context(report) is None

    def test_returns_context_for_failed_check(self):
        """Failed check with output_tail -> fix context includes the tail."""
        report = {
            "ready_for_pr": False,
            "overall_status": "not-ready",
            "gates": {"unmet": ["implementation_verification"]},
            "checks": {
                "tests": {
                    "status": "fail",
                    "runs": [{"output_tail": "AssertionError: expected 2 got 1"}]
                }
            },
            "reviews": [],
        }
        ctx = ai_ops_run._review_fix_context(report)
        assert ctx is not None
        assert "tests" in ctx
        assert "AssertionError" in ctx

    def test_returns_context_for_failed_review(self):
        """Failed review with blockers -> fix context includes blockers."""
        report = {
            "ready_for_pr": False,
            "overall_status": "not-ready",
            "gates": {"unmet": ["code_review"]},
            "checks": {},
            "reviews": [
                {"gate": "code_review", "status": "fail",
                 "blockers": ["missing docstring", "no type hints"]}
            ],
        }
        ctx = ai_ops_run._review_fix_context(report)
        assert ctx is not None
        assert "missing docstring" in ctx
        assert "no type hints" in ctx

    def test_returns_context_for_security_unmet(self):
        """Security gate unmet -> fix context mentions security."""
        report = {
            "ready_for_pr": False,
            "overall_status": "not-ready",
            "gates": {"unmet": ["security"]},
            "checks": {},
            "reviews": [],
            "security_scan": {"needs_review": ["input_validation"]},
        }
        ctx = ai_ops_run._review_fix_context(report)
        assert ctx is not None
        assert "security" in ctx

    def test_returns_none_for_human_approval_error(self):
        """Error mentioning human approval -> not model-fixable -> None."""
        report = {
            "ready_for_pr": False,
            "overall_status": "blocked",
            "error": "нужно human approval",
            "gates": {"unmet": []},
            "checks": {},
            "reviews": [],
        }
        assert ai_ops_run._review_fix_context(report) is None

    def test_returns_none_for_lifecycle_error(self):
        """Error mentioning lifecycle -> not model-fixable -> None."""
        report = {
            "ready_for_pr": False,
            "overall_status": "blocked",
            "error": "lifecycle barrier failed",
            "gates": {"unmet": []},
            "checks": {},
            "reviews": [],
        }
        assert ai_ops_run._review_fix_context(report) is None

    def test_returns_none_when_no_parts(self):
        """Not ready but no actionable blockers -> None."""
        report = {
            "ready_for_pr": False,
            "overall_status": "not-ready",
            "gates": {"unmet": []},
            "checks": {},
            "reviews": [],
        }
        assert ai_ops_run._review_fix_context(report) is None

    def test_review_warn_status_included(self):
        """Review with status=warn and blockers -> included in fix context."""
        report = {
            "ready_for_pr": False,
            "overall_status": "not-ready",
            "gates": {"unmet": ["code_review"]},
            "checks": {},
            "reviews": [
                {"gate": "code_review", "status": "warn",
                 "blockers": ["consider adding tests"]}
            ],
        }
        ctx = ai_ops_run._review_fix_context(report)
        assert ctx is not None
        assert "consider adding tests" in ctx

    def test_review_fail_without_blockers(self):
        """Review fail without explicit blockers -> generic message."""
        report = {
            "ready_for_pr": False,
            "overall_status": "not-ready",
            "gates": {"unmet": ["code_review"]},
            "checks": {},
            "reviews": [
                {"gate": "code_review", "status": "fail", "blockers": None}
            ],
        }
        ctx = ai_ops_run._review_fix_context(report)
        assert ctx is not None
        assert "ревью" in ctx


@pytest.mark.critical_path
@pytest.mark.unit
class TestResumeContextFromHandoff:
    """Tests for _resume_context_from_handoff — building resume prompt context."""

    def test_no_handoff_file(self, tmp_path):
        """No handoff file -> None."""
        result = ai_ops_run._resume_context_from_handoff(tmp_path, "nonexistent")
        assert result is None

    def test_handoff_with_completed(self, tmp_path):
        """Handoff with completed items -> context includes them."""
        fdir = tmp_path / "features" / "feat1"
        fdir.mkdir(parents=True)
        import yaml
        handoff = {
            "kind": "RunHandoff",
            "workitem_id": "feat1",
            "completed": ["wrote src/a.py", "added tests"],
            "decisions": [{"id": "d1", "summary": "use async"}],
            "changed_files": ["src/a.py", "test_a.py"],
            "open_questions": ["verify edge case"],
            "next_action": "run tests",
        }
        (fdir / "run-handoff.yaml").write_text(
            yaml.safe_dump(handoff, allow_unicode=True), encoding="utf-8")
        result = ai_ops_run._resume_context_from_handoff(tmp_path, "feat1")
        assert result is not None
        assert "RESUME" in result
        assert "wrote src/a.py" in result
        assert "d1" in result
        assert "src/a.py" in result
        assert "verify edge case" in result
        assert "run tests" in result

    def test_handoff_minimal(self, tmp_path):
        """Minimal handoff (only kind/workitem_id) -> context has header only."""
        fdir = tmp_path / "features" / "feat2"
        fdir.mkdir(parents=True)
        import yaml
        (fdir / "run-handoff.yaml").write_text(
            yaml.safe_dump({"kind": "RunHandoff", "workitem_id": "feat2"},
                           allow_unicode=True), encoding="utf-8")
        result = ai_ops_run._resume_context_from_handoff(tmp_path, "feat2")
        assert result is not None
        assert "RESUME" in result

    def test_handoff_empty_file(self, tmp_path):
        """Empty handoff file -> context has header (safe_load returns None -> {})."""
        fdir = tmp_path / "features" / "feat3"
        fdir.mkdir(parents=True)
        (fdir / "run-handoff.yaml").write_text("", encoding="utf-8")
        result = ai_ops_run._resume_context_from_handoff(tmp_path, "feat3")
        assert result is not None
        assert "RESUME" in result


@pytest.fixture(scope="module")
def pipeline_run(tmp_path_factory):
    """Канонический pipeline-прогон mock-предложителем (пишет src/a.py). Один раз на модуль."""
    root = tmp_path_factory.mktemp("pipe")
    subprocess.run(["git", "-C", str(root), "init", "-q"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], capture_output=True)
    (root / "src").mkdir(); (root / "f").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "i"], capture_output=True)
    pscript = iter([{"op": "write", "path": "src/a.py", "content": "a=1\n"}, {"done": True}])
    rp = ai_ops_run.run(
        task_text="добавить a",
        signals={"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]},
        child_root=root, engine="pipeline", proposer=lambda c: next(pscript),
    )
    return root, rp, rp["workitem_id"]


@pytest.mark.critical_path
@pytest.mark.unit
class TestEnginePipelineExecution:
    """engine=pipeline: движок реально применил изменение и прошёл единый lifecycle."""

    def test_applied_write_and_file_exists(self, pipeline_run):
        """Движок применил ровно одно изменение и файл существует на диске."""
        root, rp, _ = pipeline_run
        assert rp["loop"]["applied_writes"] == 1
        assert (root / "src" / "a.py").exists()

    def test_commit_barrier_ordering(self, pipeline_run):
        """commit-barrier: ready_for_delivery предшествует run_end по seq журнала."""
        from ai_ops_kit.shared import lifecycle_store as _ls
        root, _, pfid = pipeline_run
        jr = _ls.journal_read(root / "features" / pfid / "lifecycle-journal.jsonl")
        seq_by_kind = {e["kind"]: e["seq"] for e in jr["events"]}
        assert "ready_for_delivery" in seq_by_kind
        assert seq_by_kind["ready_for_delivery"] < seq_by_kind["run_end"]

    def test_active_work_registered(self, pipeline_run):
        """pipeline зарегистрировал active-work."""
        root, _, _ = pipeline_run
        assert (root / ".ai" / "runtime" / "active-work.yaml").exists()

    def test_lifecycle_artifacts_in_report(self, pipeline_run):
        """lifecycle-артефакты в отчёте: rep['lifecycle']['workitem'] указывает на workitem.yaml."""
        _, rp, pfid = pipeline_run
        assert isinstance(rp.get("lifecycle"), dict)
        assert rp["lifecycle"].get("workitem") == f"features/{pfid}/workitem.yaml"

    def test_single_plan_workitem_id_matches(self, pipeline_run):
        """Единый план: workitem_id отчёта совпадает с id артефактов (второй план не строился)."""
        root, rp, pfid = pipeline_run
        assert rp["workitem_id"] == pfid
        assert (root / "features" / pfid / "workitem.yaml").exists()


@pytest.mark.critical_path
@pytest.mark.unit
class TestF012ActiveWorkDeregistration:
    """F-012: прогон снят с учёта в любом исходе; статус честно отражает исход."""

    def test_deregistered_after_run(self, pipeline_run):
        """active-work содержит запись с id == workitem_id (снята с учёта по завершении)."""
        from ai_ops_kit.lifecycle import active_work
        root, _, pfid = pipeline_run
        awd = active_work.load(root / ".ai" / "runtime" / "active-work.yaml")
        entry = next((w for w in awd.get("active", []) if w.get("id") == pfid), None)
        assert entry is not None

    def test_status_reflects_outcome(self, pipeline_run):
        """done только при ready_for_pr, иначе blocked + status_reason."""
        from ai_ops_kit.lifecycle import active_work
        root, rp, pfid = pipeline_run
        awd = active_work.load(root / ".ai" / "runtime" / "active-work.yaml")
        entry = next((w for w in awd.get("active", []) if w.get("id") == pfid), None)
        assert entry is not None
        if rp.get("ready_for_pr"):
            assert entry.get("status") == "done"
        else:
            assert entry.get("status") == "blocked" and entry.get("status_reason")


@pytest.mark.critical_path
@pytest.mark.unit
class TestPipelineContext:
    """v2.97/v2.108: контекст измерен до модели, payload собран и подан."""

    def test_context_bundle_measured(self, pipeline_run):
        """estimated_tokens>0 и context_budget>0 в отчёте."""
        _, rp, _ = pipeline_run
        assert isinstance(rp.get("context_bundle"), dict)
        assert rp["context_bundle"]["estimated_tokens"] > 0
        assert rp["context_bundle"]["context_budget"] > 0

    def test_context_payload_saved(self, pipeline_run):
        """ContextPayload сохранён рядом с планом."""
        root, _, pfid = pipeline_run
        assert (root / "features" / pfid / "context-payload.yaml").exists()

    def test_payload_fed_to_model(self, pipeline_run):
        """payload подан модели (fed_to_model) + бюджет с резервом (payload_budget < context_budget)."""
        _, rp, _ = pipeline_run
        payload = rp.get("context_payload")
        assert isinstance(payload, dict)
        assert payload["fed_to_model"] is True
        assert payload["payload_budget"] < payload["context_budget"]


@pytest.mark.critical_path
@pytest.mark.unit
class TestPipelineSpecAndWorkPackage:
    """v2.98/v2.99/v2.100/v2.111: spec-level, handoff, атомарный пакет."""

    def test_spec_coverage_saved_level_zero(self, pipeline_run):
        """SpecCoverage сохранён + level==0 для QUICK (L0)."""
        root, rp, pfid = pipeline_run
        assert (root / "features" / pfid / "spec-coverage.yaml").exists()
        assert isinstance(rp.get("spec_coverage"), dict)
        assert rp["spec_coverage"]["level"] == 0

    def test_handoff_next_action(self, pipeline_run):
        """handoff несёт непустой next_action (следующий шаг)."""
        _, rp, _ = pipeline_run
        assert isinstance(rp.get("handoff"), dict)
        assert bool(rp["handoff"].get("next_action"))

    def test_work_package_saved_atomic(self, pipeline_run):
        """WorkPackagePlan сохранён + atomic==True (QUICK/1 подсистема)."""
        root, rp, pfid = pipeline_run
        assert (root / "features" / pfid / "work-package.yaml").exists()
        assert isinstance(rp.get("work_package"), dict)
        assert rp["work_package"]["atomic"] is True

    def test_atomic_has_no_subpackages(self, pipeline_run):
        """Атомарный пакет -> work_packages пуст (не выдумываем разбиение)."""
        _, rp, _ = pipeline_run
        assert rp["work_package"].get("work_packages") == []


@pytest.mark.critical_path
@pytest.mark.unit
class TestMockProposerNote:
    """v2.119: заметка 'живой предложитель' уместна для mock и убрана для живого провайдера."""

    def test_mock_note_present(self, pipeline_run):
        """mock-провайдер -> заметка «живой предложитель» присутствует в not_yet."""
        _, rp, _ = pipeline_run
        assert any("живой предложитель" in n for n in (rp.get("not_yet") or []))

    def test_live_provider_note_removed(self, tmp_path):
        """Живой провайдер -> заметка «живой предложитель» убрана из not_yet."""
        root = tmp_path / "live"
        root.mkdir()
        _git_init_commit(root)
        pscript = iter([{"op": "write", "path": "b.py", "content": "b=1\n"}, {"done": True}])
        rp_live = ai_ops_run.run(
            task_text="добавить b",
            signals={"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]},
            child_root=root, engine="pipeline", proposer=lambda c: next(pscript),
            provider_name="anthropic", feature="live-fn",
        )
        assert not any("живой предложитель" in n for n in (rp_live.get("not_yet") or []))


@pytest.fixture(scope="module")
def hybrid_run(tmp_path_factory):
    """Pipeline-прогон с context_hybrid=True (mock-предложитель). Один раз на модуль.

    Закрывает пробел покрытия под расщепление K6: под-блок hybrid фазы компиляции
    контекста (context_hybrid) не гонялся ни одним тестом до этого.
    """
    root = tmp_path_factory.mktemp("hybrid")
    subprocess.run(["git", "-C", str(root), "init", "-q"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], capture_output=True)
    (root / "src").mkdir(); (root / "f").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "i"], capture_output=True)
    pscript = iter([{"op": "write", "path": "src/a.py", "content": "a=1\n"}, {"done": True}])
    rp = ai_ops_run.run(
        task_text="добавить a",
        signals={"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]},
        child_root=root, engine="pipeline", proposer=lambda c: next(pscript),
        context_hybrid=True,
    )
    return root, rp


@pytest.mark.unit
class TestPipelineContextHybrid:
    """Характеристика под-блока hybrid фазы компиляции контекста (context_hybrid=True).

    Фиксирует поведение ДО расщепления run() (K6-глубина): на минимальном репозитории
    без v2-additions hybrid — fail-safe v1-only, ничего не подаётся сверх v1.
    """

    def test_report_has_context_hybrid(self, hybrid_run):
        """rep['context_hybrid'] присутствует и является ContextHybrid."""
        _, rp = hybrid_run
        assert rp["context_hybrid"]["kind"] == "ContextHybrid"

    def test_v1_only_fail_safe_on_minimal_repo(self, hybrid_run):
        """Без v2-additions: mode=v1-only, ничего не подано сверх v1, exact-snapshot соблюдён."""
        _, rp = hybrid_run
        ch = rp["context_hybrid"]
        assert ch["mode"] == "v1-only"
        assert ch["fed_to_model"] is False
        assert ch["v2_additions"] == []
        assert ch["exact_snapshot"] is True


@pytest.fixture(scope="module")
def shadow_run(tmp_path_factory):
    """Pipeline-прогон с context_shadow=True (mock-предложитель). Один раз на модуль.

    Закрывает пробел покрытия под расщепление K6: под-блок context_shadow фазы
    обогащения отчёта не гонялся через run() ни одним тестом до этого.
    """
    root = tmp_path_factory.mktemp("shadow")
    subprocess.run(["git", "-C", str(root), "init", "-q"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], capture_output=True)
    (root / "src").mkdir(); (root / "f").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "i"], capture_output=True)
    pscript = iter([{"op": "write", "path": "src/a.py", "content": "a=1\n"}, {"done": True}])
    rp = ai_ops_run.run(
        task_text="добавить a",
        signals={"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]},
        child_root=root, engine="pipeline", proposer=lambda c: next(pscript),
        context_shadow=True,
    )
    return root, rp


@pytest.mark.unit
class TestPipelineContextShadow:
    """Характеристика под-блока context_shadow фазы обогащения отчёта (context_shadow=True).

    Фиксирует поведение ДО расщепления run() (K6-глубина): shadow — чистая наблюдаемость
    РЯДОМ с боевым v1, полностью guarded — его сбой не роняет прогон, а честно фиксируется.
    """

    def test_shadow_present_and_guarded(self, shadow_run):
        """rep['context_shadow'] присутствует как dict; прогон не упал из-за shadow."""
        _, rp = shadow_run
        assert isinstance(rp.get("context_shadow"), dict)
        # прогон дошёл до отчёта пайплайна (shadow не прервал исполнение)
        assert rp.get("kind") == "execution-pipeline"


@pytest.mark.unit
class TestPipelineRunProvenance:
    """Характеристика фазы обогащения отчёта provenance-полями (runtime/provider/engine/
    model/model_resolution/preflight/lifecycle). Фиксирует поведение ДО расщепления run()
    (K6-глубина) перед выносом блока в _enrich_run_report.
    """

    def test_runtime_engine_provider(self, pipeline_run):
        _, rp, _ = pipeline_run
        assert rp["runtime"] == "claude-code"
        assert rp["engine"] == "pipeline"
        assert rp["provider"] == "mock"

    def test_model_resolution_and_preflight_present(self, pipeline_run):
        _, rp, _ = pipeline_run
        assert rp["model_resolution"]["kind"] == "ModelResolution"
        assert "preflight" in rp

    def test_lifecycle_dict_shape(self, pipeline_run):
        _, rp, pfid = pipeline_run
        lc = rp["lifecycle"]
        assert lc["workitem"] == f"features/{pfid}/workitem.yaml"
        assert lc["run_plan"] == f"features/{pfid}/run-plan.yaml"
        assert lc["run_report"] == f"features/{pfid}/run-report.json"
        assert lc["run_handoff"] == f"features/{pfid}/run-handoff.yaml"
        assert lc["active_work"] == ".ai/runtime/active-work.yaml"
        assert "concurrency_preflight" in lc


@pytest.mark.unit
class TestPipelineRunCost:
    """Характеристика фазы run_cost (агрегат tokens/latency/cost из вызовов модели).

    pipeline_run с mock-предложителем даёт пустой drain_call_stats -> тело `if _stats:`
    (rep['cost'] + usage_ledger) не гонялось. Инжектируем один вызов, чтобы зафиксировать
    поведение ДО расщепления run() (K6-глубина) перед выносом в _finalize_run_cost.
    """

    def _run_with_stats(self, root, stats):
        import subprocess
        from unittest.mock import patch
        root.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "-C", str(root), "init", "-q"], capture_output=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t"], capture_output=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], capture_output=True)
        (root / "src").mkdir(); (root / "f").write_text("x", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "-A"], capture_output=True)
        subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "i"], capture_output=True)
        ps = iter([{"op": "write", "path": "src/a.py", "content": "a=1\n"}, {"done": True}])
        with patch("ai_ops_kit.providers.orchestrator.drain_call_stats", return_value=stats):
            return ai_ops_run.run(
                task_text="add a",
                signals={"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]},
                child_root=root, engine="pipeline", proposer=lambda c: next(ps))

    def test_cost_aggregated_from_stats(self, tmp_path):
        """Непустой drain_call_stats -> rep['cost'] агрегирует calls/tokens/latency."""
        rp = self._run_with_stats(tmp_path / "r", [
            {"input_tokens": 100, "output_tokens": 40, "latency_s": 1.5, "cost_usd_est": 0.01},
            {"input_tokens": 50, "output_tokens": 10, "latency_s": 0.5, "cost_usd_est": 0.005},
        ])
        cost = rp["cost"]
        assert cost["calls"] == 2
        assert cost["input_tokens"] == 150
        assert cost["output_tokens"] == 50
        assert cost["latency_s"] == 2.0
        assert cost["cost_usd_est"] == 0.015

    def test_no_stats_no_cost(self, tmp_path):
        """Пустой drain_call_stats -> rep['cost'] не проставляется (нет вызовов — нечего агрегировать)."""
        rp = self._run_with_stats(tmp_path / "r", [])
        assert "cost" not in rp
