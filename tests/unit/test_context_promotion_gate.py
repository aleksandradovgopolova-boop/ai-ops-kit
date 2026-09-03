"""Гранулярные тесты context_promotion_gate (мигрировано из test_context_promotion_gate_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.context.context_promotion_gate import (
    Path,
    check_promotion_readiness,
    sys,
)


sys.path.insert(0, str(Path(__file__).resolve().parent))
from ai_ops_kit.context import context_engine as ce # noqa: E402


@pytest.fixture
def base_view():
    return {"included": [{"file": "a.py", "data_class": "internal"}],
            "excluded_access": [], "mandatory_missing": [], "mandatory_excluded_access": [],
            "cache_key": "repo:x|sha:s1|afp:A:1|dcp:D:1|allowed:h|role:executor",
            "sha": "s1", "total_tokens": 500}


@pytest.mark.unit
class TestPromotionReady:
    def test_real_clean_view(self, tmp_path):
        root = tmp_path
        (root / "src").mkdir()
        (root / "src" / "pricing.py").write_text("def apply_discount(a):\n    return a*0.9  # discount\n", encoding="utf-8")
        (root / "POLICY.md").write_text("# governing policy discount\n", encoding="utf-8")
        afp = {"id": "T-AFP", "kind": "AccessFilterPolicy",
               "rules": [{"role": "executor", "allowed_classes": ["public", "internal"]}]}
        allowed = {"public", "internal"}
        v = ce.build_context(root, "discount", "executor", sha="abc123", afp=afp,
                             v1_mandatory=["POLICY.md"], budget_tokens=10000)
        r = check_promotion_readiness(v, allowed, model_window=100000)
        assert r["ready"] is True
        assert all(c["pass"] for c in r["contracts"].values())

    def test_clean_synthetic(self, base_view):
        assert check_promotion_readiness(base_view, {"internal"}, 100000)["ready"]


@pytest.mark.unit
class TestPromotionContracts:
    def test_secret_access_filter_fail(self, base_view):
        leak = {**base_view, "included": [{"file": "secret.py", "data_class": "secret"}]}
        r = check_promotion_readiness(leak, {"internal"}, 100000)
        assert r["ready"] is False
        assert not r["contracts"]["access_filter_before_retrieval"]["pass"]

    def test_denied_filename_fail(self, base_view):
        denied = {**base_view, "included": [{"file": "b.py", "data_class": "internal"}],
                  "excluded_access": [{"file": "b.py", "data_class": "confidential"}]}
        r = check_promotion_readiness(denied, {"internal"}, 100000)
        assert not r["contracts"]["no_denied_filenames_in_payload"]["pass"]

    def test_mandatory_missing_fail(self, base_view):
        miss = {**base_view, "mandatory_missing": ["spec.md"]}
        assert not check_promotion_readiness(miss, {"internal"}, 100000)[
            "contracts"]["applicable_rules_in_mandatory"]["pass"]

    def test_mandatory_excluded_access_fail(self, base_view):
        mexc = {**base_view, "mandatory_excluded_access": ["policy.md"]}
        assert not check_promotion_readiness(mexc, {"internal"}, 100000)[
            "contracts"]["applicable_rules_in_mandatory"]["pass"]

    def test_no_pin_fail(self, base_view):
        nopin = {**base_view, "cache_key": "repo:x|role:executor", "sha": None}
        assert not check_promotion_readiness(nopin, {"internal"}, 100000)[
            "contracts"]["policy_hash_pinned_per_run"]["pass"]

    def test_hard_window_fail(self, base_view):
        big = {**base_view, "total_tokens": 200000}
        r = check_promotion_readiness(big, {"internal"}, model_window=100000)
        assert not r["contracts"]["hard_window_decompose_or_block"]["pass"]
        assert r["ready"] is False
