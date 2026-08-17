"""Property-based tests for critical AI Ops Kit invariants (v3.28.0 R10).

Hypothesis generates random inputs to find edge cases that example-based tests miss.
Focus: preflight, budget, usage_ledger, security_scan — the trust-critical modules.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

# Add tools/ to path
PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT / "tools"))

import budget as budget_mod
import usage_ledger
import security_scan


# ============================================================================
# Budget properties
# ============================================================================

class TestBudgetProperties:
    """Invariant properties for the execution budget."""

    @given(
        ceiling=st.integers(min_value=1, max_value=10000),
        n_calls=st.integers(min_value=0, max_value=100),
    )
    @settings(max_examples=100, deadline=2000)
    def test_charge_never_exceeds_ceiling(self, ceiling, n_calls):
        """Budget must never allow spending more than the ceiling."""
        b = budget_mod.Budget(max_model_calls=ceiling)
        charged = 0
        for _ in range(n_calls):
            try:
                b.charge_call(cost=0.0)
                charged += 1
            # ТИП СУЖЕН (срез tests ратчета 2026-08-12). Здесь стояло
            # `except (budget_mod.BudgetExceeded, Exception)`, а кортеж с `Exception` делает
            # конкретный тип ДЕКОРАТИВНЫМ: ловилось всё. Последствие не косметическое — тест мог
            # ПРОЙТИ при полностью сломанном бюджете: если `charge_call` падал бы, например,
            # TypeError на первом же вызове, `charged` оставался 0, и `charged <= ceiling`
            # выполнялось тривиально. Теперь любое ДРУГОЕ исключение валит тест, как и должно в
            # property-проверке.
            except budget_mod.BudgetExceeded:
                break
        assert charged <= ceiling
        # ОБРАТНАЯ СТОРОНА, без которой утверждение выше почти ничего не стоит: когда запросов
        # больше потолка, бюджет обязан израсходоваться РОВНО до потолка, а не «сколько-нибудь».
        if n_calls > ceiling:
            assert charged == ceiling, (
                f"бюджет остановился на {charged} при потолке {ceiling} и {n_calls} запросах")

    @given(ceiling=st.integers(min_value=1, max_value=10000))
    @settings(max_examples=50, deadline=2000)
    def test_zero_calls_within_budget(self, ceiling):
        """Zero calls must always be within any positive budget."""
        b = budget_mod.Budget(max_model_calls=ceiling)
        assert b.remaining_calls() == ceiling
        assert b.model_calls == 0

    @given(
        ceiling=st.integers(min_value=1, max_value=1000),
        extra=st.integers(min_value=1, max_value=1000),
    )
    @settings(max_examples=50, deadline=2000)
    def test_exceeding_raises(self, ceiling, extra):
        """Calling more than ceiling times must raise BudgetExceeded."""
        b = budget_mod.Budget(max_model_calls=ceiling)
        for _ in range(ceiling):
            b.charge_call(cost=0.0)
        with pytest.raises(budget_mod.BudgetExceeded):
            b.charge_call(cost=0.0)

    @given(ceiling=st.integers(min_value=1, max_value=100))
    @settings(max_examples=30, deadline=2000)
    def test_spent_equals_charged(self, ceiling):
        """model_calls must equal the number of successful charge_call invocations."""
        b = budget_mod.Budget(max_model_calls=ceiling)
        actual = 0
        for _ in range(ceiling + 10):
            try:
                b.charge_call(cost=0.0)
                actual += 1
            except budget_mod.BudgetExceeded:
                break
        assert b.model_calls == actual

    @given(ceiling=st.integers(min_value=1, max_value=100))
    @settings(max_examples=30, deadline=2000)
    def test_remaining_decreases(self, ceiling):
        """remaining_calls() must decrease by 1 after each successful charge."""
        b = budget_mod.Budget(max_model_calls=ceiling)
        prev = b.remaining_calls()
        for _ in range(min(ceiling, 10)):
            b.charge_call(cost=0.0)
            curr = b.remaining_calls()
            assert curr == prev - 1
            prev = curr


# ============================================================================
# Usage Ledger honesty properties
# ============================================================================

class TestUsageLedgerHonesty:
    """Invariant properties for usage recording honesty."""

    @given(
        in_tok=st.one_of(st.none(), st.integers(min_value=0, max_value=100000)),
        out_tok=st.one_of(st.none(), st.integers(min_value=0, max_value=100000)),
    )
    @settings(max_examples=100, deadline=2000)
    def test_unavailable_never_has_tokens(self, in_tok, out_tok):
        """usage_status=unavailable with non-None tokens is always an error."""
        rec = {
            "usage_status": "unavailable",
            "input_tokens": in_tok,
            "output_tokens": out_tok,
        }
        errors = usage_ledger.check(rec)
        if in_tok is not None or out_tok is not None:
            assert len(errors) > 0, "unavailable with tokens should be an error"
        else:
            assert len(errors) == 0, "unavailable with None tokens should be clean"

    @given(
        in_tok=st.one_of(st.none(), st.integers(min_value=0, max_value=100000)),
        out_tok=st.one_of(st.none(), st.integers(min_value=0, max_value=100000)),
    )
    @settings(max_examples=100, deadline=2000)
    def test_measured_requires_tokens(self, in_tok, out_tok):
        """usage_status=measured with no tokens at all is always an error."""
        rec = {
            "usage_status": "measured",
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "cost": 0.01,
            "cost_status": "measured",
        }
        errors = usage_ledger.check(rec)
        if in_tok is None and out_tok is None:
            assert len(errors) > 0, "measured with no tokens should be an error"

    @given(
        cost=st.one_of(st.none(), st.floats(min_value=0, max_value=1000)),
    )
    @settings(max_examples=50, deadline=2000)
    def test_measured_cost_requires_value(self, cost):
        """cost_status=measured with cost=None is always an error."""
        rec = {
            "usage_status": "measured",
            "input_tokens": 10,
            "output_tokens": 5,
            "cost": cost,
            "cost_status": "measured",
        }
        errors = usage_ledger.check(rec)
        if cost is None:
            assert len(errors) > 0, "measured cost with None cost should be an error"

    @given(
        status=st.sampled_from(["measured", "estimated", "unavailable"]),
    )
    @settings(max_examples=30, deadline=2000)
    def test_valid_status_no_status_error(self, status):
        """Valid usage_status values should not produce status errors."""
        rec = {
            "usage_status": status,
            "input_tokens": 10 if status != "unavailable" else None,
            "output_tokens": 5 if status != "unavailable" else None,
            "cost": 0.01,
            "cost_status": "measured",
        }
        errors = usage_ledger.check(rec)
        status_errors = [e for e in errors if "usage_status" in e]
        assert len(status_errors) == 0


# ============================================================================
# Security scan properties
# ============================================================================

class TestSecurityScanProperties:
    """Invariant properties for the security scanner."""

    @given(
        secret=st.sampled_from([
            "AKIA1234567890ABCDEF",     # AWS access key (AKIA + 16 uppercase/digits)
            "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij",  # GitHub PAT (ghp_ + 36 alnum)
            "xoxb-1234567890-abcdefghij",  # Slack token
            "AIza1234567890abcdefghijklmnopqrstuvwxy",  # Google API key (AIza + 35 alnum)
        ]),
    )
    @settings(max_examples=50, deadline=2000)
    def test_known_secrets_always_detected(self, secret):
        """Known secret patterns must always be detected regardless of surrounding text."""
        files = {"test.py": f"key = '{secret}'\n"}
        findings = security_scan.scan_secrets(files)
        assert len(findings) > 0, f"Secret '{secret[:10]}...' not detected"

    @given(
        placeholder=st.sampled_from([
            "${API_KEY}", "$ENV_VAR", "<your-key-here>",
            "xxxxxxxxxxxxxx", "changeme", "example_key",
            "placeholder_value", "env[SECRET]",
        ]),
    )
    @settings(max_examples=50, deadline=2000)
    def test_placeholders_never_flagged(self, placeholder):
        """Placeholders and examples must never be flagged as secrets."""
        files = {"config.py": f"key = '{placeholder}'\n"}
        findings = security_scan.scan_secrets(files)
        # Filter: only generic_secret_assignment could match placeholders
        generic_hits = [f for f in findings if f["id"] == "generic_secret_assignment"]
        assert len(generic_hits) == 0, f"Placeholder '{placeholder}' falsely flagged"

    @given(
        safe_code=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
            min_size=10, max_size=200,
        ),
    )
    @settings(max_examples=50, deadline=2000)
    def test_normal_text_no_secrets(self, safe_code):
        """Normal text without secret patterns should not trigger secret detection."""
        # Avoid text that accidentally contains secret-like patterns
        assume("AKIA" not in safe_code)
        assume("ghp_" not in safe_code)
        assume("xox" not in safe_code)
        assume("AIza" not in safe_code)
        assume("BEGIN" not in safe_code)
        assume("private_key" not in safe_code.lower())
        assume("secret" not in safe_code.lower())
        assume("password" not in safe_code.lower())
        assume("token" not in safe_code.lower())
        assume("api_key" not in safe_code.lower())

        files = {"normal.py": safe_code}
        findings = security_scan.scan_secrets(files)
        assert len(findings) == 0

    @given(
        dangerous=st.sampled_from([
            "eval(user_input)",
            "exec(code)",
            "subprocess.run(cmd, shell=True)",
            "os.system(cmd)",
            "pickle.loads(data)",
            "yaml.load(data)",
        ]),
    )
    @settings(max_examples=30, deadline=2000)
    def test_injection_patterns_always_flagged(self, dangerous):
        """Known dangerous patterns must always be flagged by injection scanner."""
        files = {"code.py": dangerous + "\n"}
        findings = security_scan.scan_injection(files)
        assert len(findings) > 0, f"Injection pattern '{dangerous}' not flagged"

    @given(
        safe_code=st.sampled_from([
            "x = 1 + 2\n",
            "result = json.loads(data)\n",
            "path = os.path.join(base, name)\n",
            "items = [x for x in data if x > 0]\n",
            "response = requests.get(url)\n",
            "data = yaml.safe_load(f)\n",
            "subprocess.run(['ls', '-la'])\n",
        ]),
    )
    @settings(max_examples=30, deadline=2000)
    def test_safe_code_no_injection_flags(self, safe_code):
        """Safe code patterns should not trigger injection flags."""
        files = {"safe.py": safe_code}
        findings = security_scan.scan_injection(files)
        assert len(findings) == 0, f"Safe code falsely flagged: {safe_code.strip()}"


# ============================================================================
# Preflight properties
# ============================================================================

class TestPreflightProperties:
    """Invariant properties for the preflight checker."""

    @given(
        task_type=st.sampled_from(["QUICK", "ENGINEERING", "PRODUCT", "CRITICAL"]),
    )
    @settings(max_examples=50, deadline=2000)
    def test_preflight_always_returns_required_keys(self, task_type):
        """Preflight must always return ok, blocked, checks, reasons regardless of input."""
        import preflight
        with tempfile.TemporaryDirectory() as tmpdir:
            result = preflight.assess(
                {"task_type": task_type}, tmpdir, "test-wid"
            )
        assert "ok" in result
        assert "blocked" in result
        assert "checks" in result
        assert "reasons" in result
        assert isinstance(result["ok"], bool)
        assert isinstance(result["blocked"], bool)
        assert isinstance(result["checks"], dict)
        assert isinstance(result["reasons"], list)

    @given(
        task_type=st.sampled_from(["QUICK", "ENGINEERING", "PRODUCT", "CRITICAL"]),
    )
    @settings(max_examples=50, deadline=2000)
    def test_blocked_implies_reasons(self, task_type):
        """If blocked=True, reasons must be non-empty."""
        import preflight
        with tempfile.TemporaryDirectory() as tmpdir:
            result = preflight.assess(
                {"task_type": task_type}, tmpdir, "test-wid"
            )
        if result["blocked"]:
            assert len(result["reasons"]) > 0, "blocked=True but no reasons given"

    @given(
        task_type=st.sampled_from(["QUICK", "ENGINEERING", "PRODUCT", "CRITICAL"]),
    )
    @settings(max_examples=50, deadline=2000)
    def test_not_ok_implies_blocked(self, task_type):
        """If ok=False, blocked must be True (no silent failures)."""
        import preflight
        with tempfile.TemporaryDirectory() as tmpdir:
            result = preflight.assess(
                {"task_type": task_type}, tmpdir, "test-wid"
            )
        if not result["ok"]:
            assert result["blocked"], "ok=False but not blocked — silent failure"

    @given(
        task_type=st.sampled_from(["ENGINEERING", "PRODUCT", "CRITICAL"]),
    )
    @settings(max_examples=50, deadline=2000)
    def test_heavy_without_spec_blocked(self, task_type):
        """Heavy task types without spec artifact and without author must be blocked."""
        import preflight
        with tempfile.TemporaryDirectory() as tmpdir:
            result = preflight.assess(
                {"task_type": task_type}, tmpdir, "test-wid",
                spec_cov={"spec_artifact": False, "blocking_missing": []},
            )
        assert result["blocked"], f"{task_type} without spec should be blocked"
        assert any("spec-first" in r for r in result["reasons"])

    @given(
        task_type=st.sampled_from(["ENGINEERING", "PRODUCT", "CRITICAL"]),
    )
    @settings(max_examples=50, deadline=2000)
    def test_reevaluate_skips_build_preconditions(self, task_type):
        """reevaluate_only=True must not apply build-preconditions (spec, atomic)."""
        import preflight
        with tempfile.TemporaryDirectory() as tmpdir:
            result = preflight.assess(
                {"task_type": task_type}, tmpdir, "test-wid",
                spec_cov={"spec_artifact": False, "blocking_missing": []},
                reevaluate_only=True,
            )
        # spec check should be skipped
        if "spec" in result["checks"]:
            assert result["checks"]["spec"].get("skipped_reevaluate") is True
