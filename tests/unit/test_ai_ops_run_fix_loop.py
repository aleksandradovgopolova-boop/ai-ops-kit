"""Характеристика fix-loop с quality-эскалацией в run() — ДО выноса (K6-глубина).

fixloop_run (test_ai_ops_run.py) покрывает happy-path петли, а провал провайдера —
test_provider_exception_returns_error_report. НЕ покрыта ветвь WRITER QUALITY-ESCALATION:
провал КАЧЕСТВЕННОГО гейта (implementation_verification/code_review) на openai-compatible пути
эскалирует writer'а по escalation_ladder. Эти тесты пинят её наблюдаемый след в model_resolution
(escalations/model_attempts/effective_model) на ТЕКУЩЕМ коде, чтобы вынос fix-loop в
_execute_with_fix_loop(ctx, ...) был проверяемо поведение-сохраняющим.

run_pipeline замокан контролируемой последовательностью rep (not-ready+quality-unmet -> ready),
плюс мокнут роутинг (esc_ladder) и провайдер-границы.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT / "tools"))

from ai_ops_kit.engine import ai_ops_run


def _git_repo(root: Path):
    for a in (("init", "-q"), ("config", "user.email", "t@t"), ("config", "user.name", "t")):
        subprocess.run(["git", "-C", str(root), *a], capture_output=True)
    (root / "src").mkdir(exist_ok=True)
    (root / "f").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "i"], capture_output=True)


def _plan_with_ladder():
    return {
        "kind": "RunModelPlan",
        "implementation": {"kind": "ModelResolutionResult", "resolved": True,
                           "role": "implementation", "model_id": "deepseek-chat",
                           "provider": "deepseek", "cost_basis": "money-mode", "fallback": {},
                           "escalation_ladder": [
                               {"model_id": "kimi-k2", "provider": "kimi",
                                "observed_success_rate": 0.9, "corpus_version": "v1"}]},
        "code_review": {"resolved": False, "role": "code_review"},
        "security_review": {"resolved": False, "role": "security_review"},
        "preferred_writer_tier": {"tier": "cheap-api", "reason": "простой класс"},
    }


_REP_NOT_READY = {
    "ready_for_pr": False, "kind": "execution-pipeline",
    "gates": {"unmet": ["implementation_verification"]},
    "checks": {"implementation_verification": {"status": "fail",
                                               "runs": [{"output_tail": "AssertionError: 1 != 2"}]}},
}
_REP_READY = {"ready_for_pr": True, "kind": "execution-pipeline", "gates": {"unmet": []},
              "loop": {"applied_writes": 1}}


@pytest.fixture(scope="module")
def escalated_run(tmp_path_factory):
    root = tmp_path_factory.mktemp("fixesc")
    _git_repo(root)
    ep = {"key_env": "X_KEY", "base_url": "http://x/api"}
    trust = {"ready": True, "preflight": {"ready": True, "blocks": []}}
    seq = iter([dict(_REP_NOT_READY), dict(_REP_READY)])
    with patch("ai_ops_kit.providers.model_router.plan_run", return_value=_plan_with_ladder()), \
         patch("ai_ops_kit.providers.provider_endpoints.key_available", return_value=True), \
         patch("ai_ops_kit.providers.provider_endpoints.endpoint_for", return_value=ep), \
         patch("ai_ops_kit.engine.ai_ops_run._load_klp_by_env", return_value={}), \
         patch("ai_ops_kit.engine.ai_ops_run._provider_trust", return_value=trust), \
         patch("ai_ops_kit.providers.orchestrator.make_openai_provider",
               side_effect=lambda *a, **k: (lambda prompt: {"done": True})), \
         patch("ai_ops_kit.engine.execution_pipeline.run_pipeline",
               side_effect=lambda *a, **k: next(seq)):
        rep = ai_ops_run.run(
            task_text="добавить a",
            signals={"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]},
            child_root=root, engine="pipeline", provider_name="openai-compatible", model=None,
            proposer=lambda c: {"done": True}, feature="fixesc", review_fix_attempts=1)
    return root, rep


@pytest.mark.unit
class TestQualityEscalationInFixLoop:
    """Провал качественного гейта -> эскалация writer'а по ladder, след в model_resolution."""

    def test_final_rep_ready_after_escalation(self, escalated_run):
        _, rep = escalated_run
        assert rep.get("ready_for_pr") is True

    def test_escalation_recorded(self, escalated_run):
        _, rep = escalated_run
        mr = rep["model_resolution"]
        assert mr["effective_model"] == "kimi-k2"
        assert any(e["to"] == "kimi-k2" and e["provider"] == "kimi" for e in mr.get("escalations", []))

    def test_model_attempts_grew(self, escalated_run):
        _, rep = escalated_run
        att = rep["model_resolution"]["model_attempts"]
        # первая попытка помечена quality_failed, добавлена вторая (эскалация)
        assert len(att) >= 2
        assert att[0]["outcome"] == "quality_failed"
        assert att[-1]["model"] == "kimi-k2" and att[-1]["trigger"] == "quality_escalation"

    def test_fix_attempt_journalled(self, escalated_run):
        from ai_ops_kit.shared import lifecycle_store as _ls
        root, _ = escalated_run
        jr = _ls.journal_read(root / "features" / "fixesc" / "lifecycle-journal.jsonl")
        assert any(e.get("kind") == "fix_attempt" for e in jr["events"])
