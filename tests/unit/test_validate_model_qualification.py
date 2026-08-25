"""Granular tests for validate_model_qualification (migrated from selftest)."""
from __future__ import annotations

import pytest

from validate_model_qualification import (
    DEFAULT,
    PKG,
    check,
    cm_integrity_errors,
    derive_cascade_status,
    derive_judge_status,
    derive_status,
    economics_errors,
    yaml,
)


# --- derive_status ---

class TestDeriveStatus:
    @pytest.mark.unit
    def test_false_green_positive_means_not_qualified(self):
        assert derive_status({"false_green": 1, "success_rate": 0.99,
                              "schema_valid_rate": 0.99}) == "not_qualified"

    @pytest.mark.unit
    def test_zero_fg_high_rates_means_qualified(self):
        assert derive_status({"false_green": 0, "success_rate": 0.85,
                              "schema_valid_rate": 0.95}) == "qualified"

    @pytest.mark.unit
    def test_zero_fg_medium_rates_means_conditional(self):
        assert derive_status({"false_green": 0, "success_rate": 0.6,
                              "schema_valid_rate": 0.8}) == "conditional"

    @pytest.mark.unit
    def test_zero_fg_low_rates_means_experimental(self):
        assert derive_status({"false_green": 0, "success_rate": 0.2,
                              "schema_valid_rate": 0.4}) == "experimental"


# --- derive_judge_status ---

class TestDeriveJudgeStatus:
    @pytest.fixture
    def full_judge_metrics(self):
        return {"false_green": 0, "recall": 1.0, "precision": 0.93,
                "specificity": 0.92, "schema_valid_rate": 0.97}

    @pytest.mark.unit
    def test_full_heldout_means_qualified(self, full_judge_metrics):
        assert derive_judge_status(full_judge_metrics,
                                   {"positive": 52, "negative": 28}) == "qualified"

    @pytest.mark.unit
    def test_false_green_positive_means_not_qualified(self, full_judge_metrics):
        assert derive_judge_status({**full_judge_metrics, "false_green": 1},
                                   {"positive": 52, "negative": 28}) == "not_qualified"

    @pytest.mark.unit
    def test_low_specificity_means_conditional(self, full_judge_metrics):
        assert derive_judge_status({**full_judge_metrics, "specificity": 0.125},
                                   {"positive": 52, "negative": 28}) == "conditional"

    @pytest.mark.unit
    def test_small_corpus_means_conditional(self, full_judge_metrics):
        assert derive_judge_status(full_judge_metrics,
                                   {"positive": 13, "negative": 8}) == "conditional"


# --- derive_cascade_status ---

class TestDeriveCascadeStatus:
    @pytest.fixture
    def full_cascade_metrics(self):
        return {"unsafe_passes": 0, "safe_handling_rate": 1.0, "clean_auto_pass_rate": 0.93,
                "auto_decision_coverage": 0.92, "schema_valid_rate": 0.98}

    @pytest.mark.unit
    def test_full_fail_closed_means_qualified(self, full_cascade_metrics):
        assert derive_cascade_status(full_cascade_metrics,
                                     {"positive": 52, "negative": 28}) == "qualified"

    @pytest.mark.unit
    def test_unsafe_pass_means_not_qualified(self, full_cascade_metrics):
        assert derive_cascade_status({**full_cascade_metrics, "unsafe_passes": 1},
                                     {"positive": 52, "negative": 28}) == "not_qualified"

    @pytest.mark.unit
    def test_low_coverage_means_conditional(self, full_cascade_metrics):
        assert derive_cascade_status({**full_cascade_metrics, "auto_decision_coverage": 0.4},
                                     {"positive": 52, "negative": 28}) == "conditional"

    @pytest.mark.unit
    def test_low_clean_auto_pass_means_conditional(self, full_cascade_metrics):
        assert derive_cascade_status({**full_cascade_metrics, "clean_auto_pass_rate": 0.5},
                                     {"positive": 52, "negative": 28}) == "conditional"


# --- cm_integrity_errors ---

class TestConfusionMatrixIntegrity:
    @pytest.fixture
    def cm_ok(self):
        return {"true_positive": 48, "false_negative": 0, "true_negative": 26,
                "false_positive": 1, "positive_abstain": 4, "negative_abstain": 1}

    @pytest.mark.unit
    def test_valid_cm_passes(self, cm_ok):
        assert cm_integrity_errors(cm_ok, {"positive": 52, "negative": 28},
                                   {"unsafe_passes": 0}, "t") == []

    @pytest.mark.unit
    def test_pos_abstain_dropped_from_denominator(self, cm_ok):
        errs = cm_integrity_errors(cm_ok, {"positive": 60, "negative": 28},
                                   {"unsafe_passes": 0}, "t")
        assert any("нельзя терять" in x for x in errs)

    @pytest.mark.unit
    def test_unsafe_passes_not_equal_fn(self, cm_ok):
        errs = cm_integrity_errors(
            {**cm_ok, "false_negative": 2, "positive_abstain": 2},
            {"positive": 52, "negative": 28}, {"unsafe_passes": 0}, "t")
        assert any("false green" in x for x in errs)


# --- check() integration ---

class TestCheckIntegration:
    @pytest.fixture
    def base_registry(self):
        return {"registry_type": "model-qualification", "qualifications": [
            {"model_id": "kimi-k3", "provider": "kimi", "revision": "kimi-k3",
             "role": "implementation", "corpus_version": "t",
             "metrics": {"false_green": 0, "success_rate": 0.85, "schema_valid_rate": 0.95},
             "status": "qualified"}]}

    @pytest.mark.unit
    def test_cascade_qualified_with_unsafe_pass_is_error(self):
        bad_casc = {"registry_type": "model-qualification", "qualifications": [
            {"model_id": "deepseek-v4-flash", "revision": "r", "provider": "deepseek",
             "role": "security_review", "judge_mode": "cascade", "corpus_version": "c",
             "status": "qualified", "corpus_hash": "h",
             "detector_prompt_hash": "d", "verifier_prompt_hash": "v", "policy_hash": "p",
             "sample_counts": {"positive": 52, "negative": 28},
             "confusion_matrix": {"true_positive": 50, "false_negative": 2, "true_negative": 26,
                                  "false_positive": 1, "positive_abstain": 0, "negative_abstain": 1},
             "metrics": {"unsafe_passes": 2, "false_green": 2, "safe_handling_rate": 0.96,
                         "clean_auto_pass_rate": 0.93, "auto_decision_coverage": 0.95,
                         "schema_valid_rate": 0.98}}]}
        errs = check(bad_casc, pkg=PKG)
        assert any("not_qualified" in x or "safety" in x for x in errs)

    @pytest.mark.unit
    def test_judge_qualified_without_confusion_matrix_is_error(self):
        bad_judge = {"registry_type": "model-qualification", "qualifications": [
            {"model_id": "deepseek-v4-flash", "revision": "r", "provider": "deepseek",
             "role": "security_review", "corpus_version": "c", "status": "qualified",
             "metrics": {"false_green": 0, "recall": 1.0, "precision": 0.93,
                         "specificity": 0.92, "schema_valid_rate": 0.97}}]}
        errs = check(bad_judge, pkg=PKG)
        assert any("confusion_matrix" in x or "prompt_hash" in x for x in errs)

    @pytest.mark.unit
    def test_valid_registry_passes(self, base_registry):
        assert check(base_registry) == []

    @pytest.mark.unit
    def test_qualified_with_false_green_is_error(self, base_registry):
        lie = {**base_registry, "qualifications": [{**base_registry["qualifications"][0],
                "status": "qualified",
                "metrics": {"false_green": 1, "success_rate": 0.9, "schema_valid_rate": 0.9}}]}
        errs = check(lie)
        assert any("safety" in x or "метрики дают" in x for x in errs)

    @pytest.mark.unit
    def test_qualified_with_low_success_is_error(self, base_registry):
        lie2 = {**base_registry, "qualifications": [{**base_registry["qualifications"][0],
                 "status": "qualified",
                 "metrics": {"false_green": 0, "success_rate": 0.3, "schema_valid_rate": 0.4}}]}
        errs = check(lie2)
        assert any("метрики дают" in x for x in errs)

    @pytest.mark.unit
    def test_nonexistent_model_id_is_error(self, base_registry):
        errs = check({**base_registry, "qualifications": [
            {**base_registry["qualifications"][0], "model_id": "ghost-model"}]})
        assert any("нет в models.yaml" in x for x in errs)


# --- Economics ---

class TestEconomics:
    @pytest.fixture
    def good_economics(self):
        return {"input_tokens_per_change": 100000, "output_tokens_per_change": 20000,
                "tokens_per_verified_change": 120000, "input_price_per_mtok": 2.0,
                "output_price_per_mtok": 8.0, "currency": "USD",
                "price_snapshot_at": "2026-07-28", "price_source": "http://x",
                "total_cost_per_verified_change": 0.36}

    @pytest.mark.unit
    def test_consistent_economics_passes(self, good_economics):
        assert economics_errors(good_economics, "t") == []

    @pytest.mark.unit
    def test_total_cost_mismatch(self, good_economics):
        errs = economics_errors({**good_economics, "total_cost_per_verified_change": 9.9}, "t")
        assert any("не сходятся" in x for x in errs)

    @pytest.mark.unit
    def test_price_without_provenance(self, good_economics):
        errs = economics_errors({**good_economics, "price_snapshot_at": None}, "t")
        assert any("провенанс" in x for x in errs)

    @pytest.mark.unit
    def test_null_price_with_cost_set(self):
        errs = economics_errors(
            {"input_tokens_per_change": 1, "output_tokens_per_change": 1,
             "tokens_per_verified_change": 2, "input_price_per_mtok": None,
             "output_price_per_mtok": None, "total_cost_per_verified_change": 0.5}, "t")
        assert any("деньги без тарифа" in x for x in errs)

    @pytest.mark.unit
    def test_null_price_and_null_cost_passes(self):
        assert economics_errors(
            {"input_tokens_per_change": 100, "output_tokens_per_change": 100,
             "tokens_per_verified_change": 200, "input_price_per_mtok": None,
             "output_price_per_mtok": None, "total_cost_per_verified_change": None,
             "verification_required": True}, "t") == []


# --- Real file ---

class TestRealFile:
    @pytest.mark.slow
    @pytest.mark.unit
    def test_real_default_registry_is_valid(self):
        if DEFAULT.exists():
            errs = check(yaml.safe_load(DEFAULT.read_text(encoding="utf-8")))
            assert errs == [], "\n".join(str(x) for x in errs)
