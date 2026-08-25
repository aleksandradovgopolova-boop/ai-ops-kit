"""Гранулярные тесты model_router (мигрировано из test_model_router_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import pytest

from model_router import (
    ALL_ROLES,
    _load,
    escalation_decision,
    plan_run,
    resolve,
    writer_tier,
)


@pytest.fixture(scope="module")
def loaded():
    return _load()


@pytest.fixture(scope="module")
def roles_cfg(loaded):
    return loaded[0]


@pytest.fixture(scope="module")
def quals(loaded):
    return loaded[1]


@pytest.fixture(scope="module")
def models(loaded):
    return loaded[2]


@pytest.mark.unit
class TestResolveImplementation:
    def test_resolved_with_cheapest_eligible(self, roles_cfg, quals, models):
        r = resolve("implementation", roles_cfg, quals, models)
        assert r["resolved"]
        assert r.get("model_id")
        assert r["reason"].startswith("cheapest-eligible")

    def test_cost_basis_is_money(self, roles_cfg, quals, models):
        r = resolve("implementation", roles_cfg, quals, models)
        assert r["cost_basis"] == "money"
        assert "cost_warning" not in r

    def test_cheapest_is_deepseek(self, roles_cfg, quals, models):
        r = resolve("implementation", roles_cfg, quals, models)
        assert r["model_id"] == "deepseek-v4-flash"
        assert r["provider"] == "deepseek"

    def test_fallback_is_qwen(self, roles_cfg, quals, models):
        r = resolve("implementation", roles_cfg, quals, models)
        assert (r.get("fallback") or {}).get("model_id") == "qwen3-coder-plus"


@pytest.mark.unit
class TestEscalationLadder:
    @pytest.fixture(autouse=True)
    def setup_ladder(self, roles_cfg, quals, models):
        r = resolve("implementation", roles_cfg, quals, models)
        self.ladder = r.get("escalation_ladder") or []

    def test_top_is_kimi_by_success_rate(self):
        assert bool(self.ladder)
        assert self.ladder[0]["model_id"] == "kimi-k2.7-code-highspeed"
        assert self.ladder[0]["basis"] == "higher_observed_success_rate"

    def test_sorted_desc_by_success_rate_with_corpus_version(self):
        rates = [x["observed_success_rate"] for x in self.ladder]
        assert rates == sorted(rates, reverse=True)
        assert all("corpus_version" in x for x in self.ladder)

    def test_only_above_top(self):
        assert all(x["model_id"] != "deepseek-v4-flash" for x in self.ladder)
        assert all(x["observed_success_rate"] > 0.667 for x in self.ladder)


@pytest.mark.unit
class TestMoneyMode:
    def test_selected_by_money_not_tokens(self):
        ms = {
            "a": {"classes": ["balanced"], "cost_class": "low"},
            "b": {"classes": ["balanced"], "cost_class": "low"},
        }
        q = [
            {"role": "implementation", "status": "conditional", "model_id": "a", "provider": "pa",
             "revision": "a", "corpus_version": "t", "metrics": {"false_green": 0},
             "economics": {"tokens_per_verified_change": 50000, "total_cost_per_verified_change": 0.90}},
            {"role": "implementation", "status": "conditional", "model_id": "b", "provider": "pb",
             "revision": "b", "corpus_version": "t", "metrics": {"false_green": 0},
             "economics": {"tokens_per_verified_change": 150000, "total_cost_per_verified_change": 0.07}},
        ]
        rc = {"roles": {"implementation": {"preferred_class": "balanced"}}}
        rm = resolve("implementation", rc, q, ms)
        assert rm["cost_basis"] == "money"
        assert rm["model_id"] == "b"
        assert "cost_warning" not in rm


@pytest.mark.unit
class TestStrictJudge:
    def test_security_review_not_resolved(self, roles_cfg, quals, models):
        r = resolve("security_review", roles_cfg, quals, models)
        assert r["resolved"] is False
        assert "escalation" in r

    def test_strict_judge_conditional_in_class_not_resolved(self):
        ms = {"m-cond": {"classes": ["high-reasoning"], "cost_class": "low"}}
        q = [{"role": "security_review", "status": "conditional", "model_id": "m-cond",
              "provider": "x", "revision": "r", "corpus_version": "t",
              "metrics": {"false_green": 0, "cost_per_change": 1}}]
        rc = {"roles": {"security_review": {"preferred_class": "high-reasoning", "fallback_class": "high-reasoning"}}}
        assert resolve("security_review", rc, q, ms)["resolved"] is False

    def test_econ_review_conditional_resolved(self):
        ms = {"m-cond": {"classes": ["high-reasoning"], "cost_class": "low"}}
        q = [{"role": "code_review", "status": "conditional", "model_id": "m-cond",
              "provider": "x", "revision": "r", "corpus_version": "t",
              "metrics": {"false_green": 0, "cost_per_change": 1}}]
        rc = {"roles": {"code_review": {"preferred_class": "high-reasoning", "fallback_class": "high-reasoning"}}}
        assert resolve("code_review", rc, q, ms)["resolved"] is True

    def test_false_green_blocks_even_writer(self):
        ms = {"m-cond": {"classes": ["high-reasoning"], "cost_class": "low"}}
        q = [{"role": "implementation", "status": "conditional", "model_id": "m-cond",
              "provider": "x", "revision": "r", "corpus_version": "t",
              "metrics": {"false_green": 1, "cost_per_change": 1}}]
        rc = {"roles": {"implementation": {"preferred_class": "high-reasoning", "fallback_class": "high-reasoning"}}}
        assert resolve("implementation", rc, q, ms)["resolved"] is False


@pytest.mark.unit
class TestTwoQualifiedModels:
    def test_cheapest_plus_fallback(self, models):
        q2 = [
            {"role": "implementation", "status": "qualified", "model_id": "kimi-k3",
             "provider": "kimi", "revision": "kimi-k3", "corpus_version": "t",
             "metrics": {"false_green": 0, "cost_per_change": 1.4}},
            {"role": "implementation", "status": "qualified", "model_id": "kimi-k2.7-code-highspeed",
             "provider": "kimi", "revision": "hs", "corpus_version": "t",
             "metrics": {"false_green": 0, "cost_per_change": 0.9}},
        ]
        rc = {
            "roles": {"implementation": {"preferred_class": "balanced", "fallback_class": "high-reasoning"}},
            "escalation_policy": {"triggers": ["reviewer_abstain"], "max_targeted_retries": 1, "escalate_scope": "review_only"},
        }
        r = resolve("implementation", rc, q2, models)
        assert r["model_id"] == "kimi-k2.7-code-highspeed"
        assert r["fallback"]["model_id"] == "kimi-k3"


@pytest.mark.unit
class TestEscalationDecision:
    def test_abstain_attempt0_retries(self, roles_cfg):
        assert escalation_decision("code_review", 0, "reviewer_abstain", roles_cfg)["action"] == "retry"

    def test_abstain_after_retries_escalates_review_only(self, roles_cfg):
        d = escalation_decision("code_review", 1, "reviewer_abstain", roles_cfg)
        assert d["action"] == "escalate"
        assert d["scope"] == "review_only"

    def test_ok_proceeds(self, roles_cfg):
        assert escalation_decision("code_review", 0, "ok", roles_cfg)["action"] == "proceed"


@pytest.mark.unit
class TestPlanRun:
    def test_all_four_roles_present(self, roles_cfg, quals, models):
        plan = plan_run(roles_cfg, quals, models)
        assert all(r in plan for r in ALL_ROLES)

    def test_implementation_resolved_security_not(self, roles_cfg, quals, models):
        plan = plan_run(roles_cfg, quals, models)
        assert plan["implementation"]["resolved"] is True
        assert plan["security_review"]["resolved"] is False


@pytest.mark.unit
class TestConflictAwareRouting:
    @pytest.fixture(autouse=True)
    def setup_conflict(self):
        def _ec(c):
            return {
                "input_tokens_per_change": 1, "output_tokens_per_change": 1,
                "tokens_per_verified_change": 1, "input_price_per_mtok": c,
                "output_price_per_mtok": c, "currency": "USD",
                "price_snapshot_at": "2026-07-30", "price_source": "test",
                "total_cost_per_verified_change": 2 * c / 1e6,
            }

        self.rc = {
            "roles": {
                "implementation": {"preferred_class": "balanced"},
                "security_review": {"preferred_class": "balanced"},
            },
            "role_constraints": {"security_review": {"must_differ_from": "implementation"}},
        }
        self.ms = {
            "J": {"classes": ["balanced"], "cost_class": "low"},
            "W": {"classes": ["balanced"], "cost_class": "mid"},
        }
        self.q = [
            {"role": "security_review", "status": "qualified", "model_id": "J", "provider": "p",
             "revision": "J", "corpus_version": "c", "metrics": {"false_green": 0}, "economics": _ec(0.1)},
            {"role": "implementation", "status": "qualified", "model_id": "J", "provider": "p",
             "revision": "J", "corpus_version": "c", "metrics": {"false_green": 0, "success_rate": 0.9},
             "economics": _ec(0.1)},
            {"role": "implementation", "status": "conditional", "model_id": "W", "provider": "p",
             "revision": "W", "corpus_version": "c", "metrics": {"false_green": 0, "success_rate": 0.6},
             "economics": _ec(1.0)},
        ]
        self.plan = plan_run(self.rc, self.q, self.ms)

    def test_judge_fixed_as_j(self):
        assert self.plan["security_review"]["resolved"]
        assert self.plan["security_review"]["model_id"] == "J"

    def test_implementation_rerouted_to_w(self):
        assert self.plan["implementation"]["resolved"]
        assert self.plan["implementation"]["model_id"] == "W"

    def test_constraint_applied_and_writer_ne_judge(self):
        assert bool(self.plan.get("role_constraints_applied"))
        assert self.plan["implementation"]["model_id"] != self.plan["security_review"]["model_id"]


@pytest.mark.unit
class TestWriterTier:
    def test_quick_maps_to_cheap_api(self):
        assert writer_tier({"task_type": "QUICK"})["tier"] == "cheap-api"

    def test_engineering_maps_to_strong_executor(self):
        r = writer_tier({"task_type": "ENGINEERING"})
        assert r["tier"] == "strong-executor"
        assert r["provider_hint"] == "claude-cli"

    def test_product_maps_to_strong_executor(self):
        assert writer_tier({"task_type": "PRODUCT"})["tier"] == "strong-executor"

    def test_quick_with_critical_risk_overrides_to_strong(self):
        assert writer_tier({"task_type": "QUICK", "risk": "critical"})["tier"] == "strong-executor"

    def test_plan_run_with_signals_carries_writer_tier(self, roles_cfg, quals, models):
        plan = plan_run(roles_cfg, quals, models, signals={"task_type": "ENGINEERING"})
        assert isinstance(plan.get("preferred_writer_tier"), dict)
        assert plan["preferred_writer_tier"]["tier"] == "strong-executor"
