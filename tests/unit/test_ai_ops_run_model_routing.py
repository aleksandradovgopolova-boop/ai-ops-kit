"""Характеристика model-routing в run() (openai-compatible путь) — ДО выноса (K6-глубина).

Замер сессии 2026-08-26: путь `model is None and provider_name == "openai-compatible"` в
контроллере не гонялся ни одним тестом (owner-tuned подсистема роутинга: writer≠judge по модели,
JIT-trust, complexity-aware strong-executor, provider fallback). Эти тесты пинят наблюдаемое
поведение `rep["model_resolution"]` на этом пути на ТЕКУЩЕМ коде, чтобы вынос блока в
`_resolve_models(ctx)` был проверяемо поведение-сохраняющим (тесты не правятся при выносе).

Моки стоят на границах, которые вызывает сам блок роутинга: model_router.plan_run,
provider_endpoints.key_available/endpoint_for, ai_ops_run._provider_trust/_load_klp_by_env и
orchestrator.make_openai_provider/claude_binary/make_claude_cli_provider/claude_lookup.
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


def _plan(*, impl=True, rev=True, tier="cheap-api", tier_reason="сложный класс",
          impl_fallback=None, ladder=None, sec=False):
    """Форма model_router.plan_run: implementation/code_review/security_review + preferred_writer_tier."""
    p = {
        "kind": "RunModelPlan",
        "implementation": ({"kind": "ModelResolutionResult", "resolved": True,
                            "role": "implementation", "model_id": "deepseek-chat",
                            "provider": "deepseek", "cost_basis": "money-mode",
                            "fallback": impl_fallback or {}, "escalation_ladder": ladder or []}
                           if impl else {"resolved": False, "role": "implementation"}),
        "code_review": ({"kind": "ModelResolutionResult", "resolved": True, "role": "code_review",
                         "model_id": "kimi-k2", "provider": "kimi"}
                        if rev else {"resolved": False, "role": "code_review"}),
        "security_review": {"resolved": bool(sec), "role": "security_review"},
        "preferred_writer_tier": {"tier": tier, "reason": tier_reason},
    }
    return p


def _run_routed(root, *, plan, trust_ready=True, key_avail=True, claude_bin=None,
                claude_named_missing=False, signals=None, feature="mr"):
    """Прогнать run() по openai-compatible пути с замоканными границами роутинга."""
    ps = iter([{"op": "write", "path": "src/a.py", "content": "a=1\n"}, {"done": True}])
    ep = {"key_env": "X_KEY", "base_url": "http://x/api"}
    trust = ({"ready": True, "preflight": {"ready": True, "blocks": []}} if trust_ready
             else {"ready": False, "reason": "ключ просрочен/ротация",
                   "preflight": {"ready": False, "blocks": ["ключ просрочен/ротация"]}})
    look = {"where": "named" if claude_named_missing else "path"}
    with patch("ai_ops_kit.providers.model_router.plan_run", return_value=plan), \
         patch("ai_ops_kit.providers.provider_endpoints.key_available", return_value=key_avail), \
         patch("ai_ops_kit.providers.provider_endpoints.endpoint_for", return_value=ep), \
         patch("ai_ops_run._load_klp_by_env", return_value={}), \
         patch("ai_ops_run._provider_trust", return_value=trust), \
         patch("ai_ops_kit.providers.orchestrator.make_openai_provider",
               side_effect=lambda *a, **k: (lambda prompt: {"done": True})), \
         patch("ai_ops_kit.providers.orchestrator.claude_binary", return_value=claude_bin), \
         patch("ai_ops_kit.providers.orchestrator.make_claude_cli_provider",
               side_effect=lambda *a, **k: (lambda prompt: {"done": True})), \
         patch("ai_ops_kit.providers.orchestrator.claude_lookup", return_value=look):
        return ai_ops_run.run(
            task_text="добавить a",
            signals=signals or {"task_type": "QUICK", "size": "small", "risk": "low",
                                "affected_areas": ["core"]},
            child_root=root, engine="pipeline", provider_name="openai-compatible", model=None,
            proposer=lambda c: next(ps), feature=feature)


@pytest.fixture(scope="module")
def routed_happy(tmp_path_factory):
    root = tmp_path_factory.mktemp("mr_happy")
    _git_repo(root)
    return _run_routed(root, plan=_plan())


@pytest.mark.unit
class TestOpenAICompatibleRouting:
    """Happy-path: impl+rev резолвятся, ключи есть, trust ready -> writer=impl, judge независим."""

    def test_resolution_applied_router_mode(self, routed_happy):
        mr = routed_happy["model_resolution"]
        assert mr["kind"] == "ModelResolution"
        assert mr["applied"] is True
        assert mr["mode"] == "router"

    def test_writer_is_resolved_impl_model(self, routed_happy):
        mr = routed_happy["model_resolution"]
        assert mr["writer"] == {"model_id": "deepseek-chat", "provider": "deepseek",
                                "cost_basis": "money-mode"}
        assert mr["initial_model"] == "deepseek-chat"
        assert mr["effective_model"] == "deepseek-chat"

    def test_reviewer_independent_by_model(self, routed_happy):
        """rev резолвится в ДРУГУЮ модель + ключ + trust -> judge независим от writer по модели."""
        rev = routed_happy["model_resolution"]["reviewer"]
        assert rev == {"model_id": "kimi-k2", "provider": "kimi", "independent_by_model": True}

    def test_first_model_attempt_recorded(self, routed_happy):
        att = routed_happy["model_resolution"]["model_attempts"]
        assert att[0]["attempt"] == 1
        assert att[0]["model"] == "deepseek-chat" and att[0]["provider"] == "deepseek"
        assert att[0]["trigger"] == "initial"

    def test_report_provider_is_openai_compatible(self, routed_happy):
        assert routed_happy["provider"] == "openai-compatible"


@pytest.mark.unit
class TestReviewerFallsBackToSelfModel:
    """code_review НЕ резолвится -> reviewer=writer по модели (self-model), с честной записью."""

    def test_self_model_reviewer(self, tmp_path):
        root = tmp_path / "mr_self"; root.mkdir(); _git_repo(root)
        rep = _run_routed(root, plan=_plan(rev=False), feature="mrself")
        rev = rep["model_resolution"]["reviewer"]
        assert rev["independent_by_model"] is False
        assert rev["model_id"] == "deepseek-chat"


@pytest.mark.unit
class TestComplexityAwareStrongExecutor:
    """preferred_writer_tier=strong-executor + локальный claude есть -> writer=claude-code-local."""

    def test_strong_executor_selected_when_claude_available(self, tmp_path):
        root = tmp_path / "mr_strong"; root.mkdir(); _git_repo(root)
        rep = _run_routed(root, plan=_plan(tier="strong-executor"),
                          claude_bin="/usr/local/bin/claude", feature="mrstrong")
        mr = rep["model_resolution"]
        assert mr["effective_model"] == "claude-code-local"
        assert mr["writer"]["provider"] == "claude-cli"
        assert mr["writer"]["tier"] == "strong-executor"
        # code_review резолвится в kimi (!= claude-cli, ключ+trust) -> judge независим по модели
        assert mr["reviewer"]["model_id"] == "kimi-k2"
        assert mr["reviewer"]["independent_by_model"] is True

    def test_strong_executor_reviewer_falls_back_to_cheap_qualified_judge(self, tmp_path):
        """writer=claude-cli, code_review НЕ резолвится -> judge = дешёвый qualified impl (deepseek),
        независим от claude-cli по модели (owner-план review->deepseek)."""
        root = tmp_path / "mr_strong_dsjudge"; root.mkdir(); _git_repo(root)
        rep = _run_routed(root, plan=_plan(tier="strong-executor", rev=False),
                          claude_bin="/usr/local/bin/claude", feature="mrstrongds")
        mr = rep["model_resolution"]
        assert mr["writer"]["provider"] == "claude-cli"
        assert mr["reviewer"]["model_id"] == "deepseek-chat"
        assert mr["reviewer"]["independent_by_model"] is True

    def test_strong_executor_unavailable_falls_back(self, tmp_path):
        """Класс требует strong-executor, но claude недоступен -> money-mode writer + честная запись."""
        root = tmp_path / "mr_noexec"; root.mkdir(); _git_repo(root)
        rep = _run_routed(root, plan=_plan(tier="strong-executor"), claude_bin=None,
                          feature="mrnoexec")
        mr = rep["model_resolution"]
        assert mr.get("strong_executor_unavailable") is True
        assert mr["effective_model"] == "deepseek-chat"   # остался дешёвый writer


@pytest.mark.unit
class TestKeyPreflightBlocksTheRun:
    """JIT-trust PRIMARY не готов -> blocked-preflight ДО provider-вызова (fail-closed)."""

    def test_blocked_preflight_returns_without_pipeline(self, tmp_path):
        root = tmp_path / "mr_blocked"; root.mkdir(); _git_repo(root)
        rep = _run_routed(root, plan=_plan(), trust_ready=False, feature="mrblocked")
        assert rep["status"] == "blocked-preflight"
        assert rep["ready_for_pr"] is False
        assert rep["model_resolution"]["preflight_blocked"] is True
        assert "key_preflight" in rep
        # петли не было: pipeline не запускался
        assert rep.get("loop") is None
