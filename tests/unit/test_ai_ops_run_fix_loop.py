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


def test_controller_fix_attempt_keeps_shared_counter(tmp_path, monkeypatch):
    from ai_ops_kit.engine import execution_pipeline, tool_loop, tool_broker
    from ai_ops_kit.shared.budget import Budget
    _git_repo(tmp_path)
    shared, seen, calls = Budget(max_model_calls=1), [], []
    def pipeline(*args, **kwargs):
        seen.append(kwargs["budget"])
        loop = tool_loop.run_loop(lambda _: (calls.append("model") or {"done": True}),
            tmp_path, tool_broker.Policy(), budget=kwargs["budget"], max_steps=1)
        return {**_REP_NOT_READY, "loop": loop}
    monkeypatch.setattr(execution_pipeline, "run_pipeline", pipeline)
    monkeypatch.setattr(ai_ops_run, "_provider_trust", lambda *a, **k: {"ready": True,
                        "preflight": {"ready": True, "blocks": []}})
    monkeypatch.setattr(ai_ops_run, "_load_klp_by_env", lambda *a, **k: {})
    rep = ai_ops_run.run("bounded fix", {"task_type": "QUICK", "size": "small", "risk": "low"},
        tmp_path, feature="bounded-fix", provider_name="openai-compatible", model="controlled-model",
        proposer=lambda _: {"done": True}, budget=shared, review_fix_attempts=1)
    assert len(seen) == 2 and all(item is shared for item in seen)
    assert calls == ["model"] and shared.model_calls == 1
    assert rep["ready_for_pr"] is False


@pytest.mark.parametrize("mode", ["restore", "conflict", "missing", "corrupt"])
def test_resume_preserves_saved_limits_or_refuses_unknown_prior_budget(tmp_path, monkeypatch, mode):
    import yaml
    from ai_ops_kit.engine import execution_pipeline, tool_loop, tool_broker
    from ai_ops_kit.shared.budget import Budget
    _git_repo(tmp_path)
    target = tmp_path / "features/prior/run-plan.yaml"
    target.parent.mkdir(parents=True)
    if mode != "missing":
        target.write_text("corrupt: [" if mode == "corrupt" else yaml.safe_dump(
            {"kind": "run-plan", "execution_budget": {"max_model_calls": 2}}))
    before = target.read_bytes() if target.exists() else None
    calls, seen = [], []
    def pipeline(*args, **kwargs):
        seen.append(kwargs["budget"])
        loop = tool_loop.run_loop(lambda _: (calls.append("model") or {"op": "read", "path": "f"}),
            tmp_path, tool_broker.Policy(), budget=kwargs["budget"], max_steps=3)
        return {**_REP_NOT_READY, "loop": loop}
    monkeypatch.setattr(execution_pipeline, "run_pipeline", pipeline)
    monkeypatch.setattr(ai_ops_run, "_resume_gate", lambda *a, **kw: ({}, None, None))
    monkeypatch.setattr(ai_ops_run, "_run_preflight", lambda *a, **kw: ({}, None))
    shared = Budget(max_model_calls=3) if mode == "conflict" else None
    rep = ai_ops_run.run("prior task", {"task_type": "QUICK"}, tmp_path, feature="prior",
        resume=True, budget=shared, proposer=lambda _: {"done": True})
    if mode == "restore":
        assert calls == ["model", "model"] and seen[0].model_calls == 2
        assert rep["budget"]["max_model_calls"] == 2 and rep["budget"]["remaining_calls"] == 0
        assert yaml.safe_load(target.read_text())["execution_budget"]["max_model_calls"] == 2
    else:
        assert rep.get("blocked_by") == "execution-budget" and calls == []
        assert (target.read_bytes() if target.exists() else None) == before
