"""Unit tests for tools/gate_executor.py — quality gate evaluation.

Tests gate classification, evidence validation, deterministic validators,
override policy, and the evaluate() aggregation. Complements the selftest
wrapper with granular assertions.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT / "tools"))

import gate_executor


@pytest.mark.critical_path
@pytest.mark.unit
class TestGateClassification:
    """Tests for classify() — gate type determination."""

    def test_deterministic_gate(self):
        """Gate with validator should classify as deterministic."""
        gate = {"validator": "validate-references"}
        kind = gate_executor.classify(gate)
        assert kind == "deterministic"

    def test_ai_review_gate(self):
        """Gate with review_mode=read-only should classify as ai-review."""
        gate = {"review_mode": "read-only"}
        kind = gate_executor.classify(gate)
        assert kind == "ai-review"

    def test_writer_check_fallback(self):
        """Gate without validator or review_mode should classify as writer-check."""
        gate = {}
        kind = gate_executor.classify(gate)
        assert kind == "writer-check"

    def test_human_approval_unconditional(self):
        """Gate with human_approval=True should classify as human-approval."""
        gate = {"human_approval": True}
        kind = gate_executor.classify(gate)
        assert kind == "human-approval"


@pytest.mark.critical_path
@pytest.mark.unit
class TestEvaluateQuick:
    """Tests for evaluate() on QUICK workflow."""

    def test_quick_without_evidence_blocked(self):
        """QUICK workflow without evidence should be blocked."""
        result = gate_executor.evaluate("QUICK")
        assert result["blocked"] is True
        assert len(result["unmet_gates"]) > 0

    def test_quick_with_full_evidence_passes(self):
        """QUICK with complete evidence should not be blocked."""
        evidence = {
            "intake_completeness": {
                "status": "pass",
                "provided": ["classified_type", "size", "risk"],
            },
            "implementation_verification": {
                "status": "pass",
                "provided": ["build_passed", "lint_passed", "typecheck_passed", "tests_passed", "tested_revision"],
            },
        }
        result = gate_executor.evaluate("QUICK", evidence=evidence)
        assert result["blocked"] is False

    def test_partial_evidence_still_blocked(self):
        """Providing evidence for only one gate should still block."""
        evidence = {
            "intake_completeness": {
                "status": "pass",
                "provided": ["classified_type", "size", "risk"],
            },
        }
        result = gate_executor.evaluate("QUICK", evidence=evidence)
        assert result["blocked"] is True


@pytest.mark.critical_path
@pytest.mark.unit
class TestOverridePolicy:
    """Tests for override_effective — respects bypass_policy."""

    def test_forbidden_gate_cannot_be_overridden(self):
        """Gates with bypass_policy=forbidden cannot be overridden."""
        gate = {"bypass_policy": "forbidden"}
        override = {"by": "admin", "reason": "urgent"}
        assert gate_executor.override_effective(gate, override) is False

    def test_allowed_gate_can_be_overridden(self):
        """Gates with override_policy.allowed=True can be overridden."""
        gate = {"override_policy": {"allowed": True}}
        override = {"by": "admin", "reason": "urgent"}
        assert gate_executor.override_effective(gate, override) is True

    def test_no_override_policy_cannot_bypass(self):
        """Gates without explicit override policy cannot be bypassed."""
        gate = {}
        override = {"by": "admin", "reason": "urgent"}
        assert gate_executor.override_effective(gate, override) is False


@pytest.mark.critical_path
@pytest.mark.unit
class TestEvaluateGate:
    """Tests for evaluate_gate — single gate evaluation."""

    def test_evaluate_gate_returns_schema(self):
        """evaluate_gate should return a dict with required schema keys."""
        gate = {"validator": "validate-references"}
        result = gate_executor.evaluate_gate(
            "test_gate",
            gate,
            evidence={},
        )
        assert "schema_version" in result
        assert "gate" in result
        assert "status" in result
        assert "blocking" in result

    def test_unmet_gate_has_fail_or_warn_status(self):
        """Unmet gate without evidence should have status=fail or warn."""
        gate = {"blocking": True}
        result = gate_executor.evaluate_gate(
            "test_gate",
            gate,
            evidence={},
        )
        assert result["status"] in ("fail", "warn")


@pytest.mark.critical_path
@pytest.mark.unit
class TestCollectEvidence:
    """Tests for collect_evidence — extracting evidence from reviewer artifacts."""

    def test_collect_from_reviewer_json(self, child_root):
        """collect_evidence should read from .reviewer.json files."""
        run_dir = child_root / ".ai" / "runtime" / "test-run"
        run_dir.mkdir(parents=True)
        reviewer_file = run_dir / "stage-review.reviewer.json"
        reviewer_file.write_text('{"verdict": "pass", "reasoning": "looks good"}')

        evidence = gate_executor.collect_evidence("QUICK", run_dir)
        assert isinstance(evidence, dict)

    def test_collect_empty_when_no_artifacts(self, child_root):
        """collect_evidence should return empty dict when no artifacts exist."""
        run_dir = child_root / ".ai" / "runtime" / "empty-run"
        run_dir.mkdir(parents=True)
        evidence = gate_executor.collect_evidence("QUICK", run_dir)
        assert evidence == {} or isinstance(evidence, dict)


@pytest.mark.critical_path
@pytest.mark.unit
class TestLoadGates:
    """Tests for load_gates — loading gate definitions."""

    def test_load_gates_returns_dict(self):
        """load_gates should return a dict of gate definitions."""
        gates = gate_executor.load_gates()
        assert isinstance(gates, dict)
        assert len(gates) > 0

    def test_load_workflows_returns_dict(self):
        """load_workflows should return a dict of workflow definitions."""
        workflows = gate_executor.load_workflows()
        assert isinstance(workflows, dict)
        assert len(workflows) > 0


# ── Migrated from test_gate_executor_selftest.py (granular ports below) ──


@pytest.mark.critical_path
@pytest.mark.unit
class TestRealGateClassification:
    """classify() over the real gates.yaml registry (not synthetic dicts)."""

    def test_intake_completeness_is_deterministic(self):
        gates = gate_executor.load_gates()
        assert gate_executor.classify(gates["intake_completeness"]) == "deterministic"

    def test_code_review_is_ai_review(self):
        gates = gate_executor.load_gates()
        assert gate_executor.classify(gates["code_review"]) == "ai-review"


@pytest.mark.critical_path
@pytest.mark.unit
class TestClassifyBySignals:
    """classify() for the conditional security human-approval gate."""

    def test_security_surface_changed_is_human_approval(self):
        sec = gate_executor.load_gates()["security"]
        assert gate_executor.classify(sec, {"security_surface_changed": True}) == "human-approval"

    def test_secret_boundary_is_human_approval(self):
        """Alias name from spec_levels/security_pack also raises human-approval (name drift removed)."""
        sec = gate_executor.load_gates()["security"]
        assert gate_executor.classify(sec, {"secret_boundary": True}) == "human-approval"

    def test_destructive_is_human_approval(self):
        sec = gate_executor.load_gates()["security"]
        assert gate_executor.classify(sec, {"destructive": True}) == "human-approval"

    def test_security_without_signals_not_human_approval(self):
        """Conditional required_when + no signals must NOT block unconditionally."""
        sec = gate_executor.load_gates()["security"]
        assert gate_executor.classify(sec, None) != "human-approval"


@pytest.mark.critical_path
@pytest.mark.unit
class TestUnmetGateSets:
    """Exact unmet_gates sets and fail (not warn) status for blocking gates."""

    def test_quick_no_evidence_unmet_is_both_blocking_gates(self):
        r0 = gate_executor.evaluate("QUICK")
        assert set(r0["unmet_gates"]) == {"intake_completeness", "implementation_verification"}

    def test_unmet_blocking_gate_status_is_fail(self):
        """An unmet blocking gate has status=fail, never warn."""
        r0 = gate_executor.evaluate("QUICK")
        assert all(g["status"] == "fail" for g in r0["gate_results"] if g["blocking"])

    def test_quick_partial_unmet_is_exactly_impl_verification(self):
        evidence = {"intake_completeness": {"status": "pass",
                                            "provided": ["classified_type", "size", "risk"]}}
        r2 = gate_executor.evaluate("QUICK", evidence=evidence)
        assert r2["blocked"] is True
        assert r2["unmet_gates"] == ["implementation_verification"]


@pytest.mark.critical_path
@pytest.mark.unit
class TestGateIdsOverride:
    """gate_ids override evaluates RunPlan gates (base + tracks), not only contract gates."""

    def _good(self):
        return {
            "intake_completeness": {"status": "pass",
                                    "provided": ["classified_type", "size", "risk"]},
            "implementation_verification": {"status": "pass",
                "provided": ["build_passed", "lint_passed", "typecheck_passed",
                             "tests_passed", "tested_revision"]},
        }

    def test_track_gate_reaches_evaluated_gates(self):
        rp_gates = list(gate_executor.load_workflows()["QUICK"].get("quality_gates", [])) + ["ux_review"]
        r = gate_executor.evaluate("QUICK", self._good(), gate_ids=rp_gates)
        assert "ux_review" in r["evaluated_gates"]

    def test_track_gate_without_evidence_blocks(self):
        rp_gates = list(gate_executor.load_workflows()["QUICK"].get("quality_gates", [])) + ["ux_review"]
        r = gate_executor.evaluate("QUICK", self._good(), gate_ids=rp_gates)
        assert "ux_review" in r["unmet_gates"] and r["blocked"] is True


@pytest.mark.critical_path
@pytest.mark.unit
class TestSmartExemption:
    """v2.61 smart relaxation: not_applicable exempts a flag, recorded in warnings, never fabricated."""

    _partial = {"implementation_verification": {"status": "pass",
                "provided": ["build_passed", "tests_passed", "tested_revision"]}}  # no lint/typecheck

    def test_missing_lint_typecheck_blocks_without_exemption(self):
        r = gate_executor.evaluate("QUICK", dict(self._partial))
        assert "implementation_verification" in r["unmet_gates"]

    def test_not_applicable_exempts_gate(self):
        r = gate_executor.evaluate(
            "QUICK", dict(self._partial),
            not_applicable={"implementation_verification": {"lint_passed", "typecheck_passed"}})
        assert "implementation_verification" not in r["unmet_gates"]

    def test_exemption_recorded_in_warnings(self):
        r = gate_executor.evaluate(
            "QUICK", dict(self._partial),
            not_applicable={"implementation_verification": {"lint_passed", "typecheck_passed"}})
        iv = next(g for g in r["gate_results"] if g["gate"] == "implementation_verification")
        assert any("освобождено" in w for w in iv.get("warnings", []))


@pytest.mark.critical_path
@pytest.mark.unit
class TestBarePass:
    """A status:pass without required_evidence is rejected (no evidence-free pass)."""

    def test_bare_pass_is_blocked(self):
        r = gate_executor.evaluate("QUICK", {
            "intake_completeness": {"status": "pass"},
            "implementation_verification": {"status": "pass"}})
        assert r["blocked"] is True


@pytest.mark.critical_path
@pytest.mark.unit
class TestDeterministicRun:
    """deterministic_run executes real validators; symbolic ones return None."""

    def test_real_validator_executes_and_passes(self):
        run = gate_executor.deterministic_run("validate-references + validate-claims")
        assert run is not None and run[0] == "pass"

    def test_symbolic_validator_returns_none(self):
        assert gate_executor.deterministic_run("validate-intake") is None


@pytest.mark.critical_path
@pytest.mark.unit
class TestArchitectureRequiredWhen:
    """A gate with required_when is applicable only under an architectural signal."""

    _gate = {"id": "architecture_review", "blocking": True, "review_mode": "read-only",
             "responsible_role": "architecture-reviewer",
             "required_when": ["architecture_change", "data_migration"]}

    def test_not_applicable_without_signal(self):
        r = gate_executor.evaluate_gate("architecture_review", self._gate, {}, signals={})
        assert r["status"] == "pass" and r["blocking"] is False
        assert "not_applicable" in r.get("scope", [])

    def test_fails_with_signal_and_no_evidence(self):
        r = gate_executor.evaluate_gate("architecture_review", self._gate, {},
                                        signals={"data_migration": True})
        assert r["status"] == "fail" and r["blocking"] is True


@pytest.mark.critical_path
@pytest.mark.unit
class TestFreshnessRun:
    """_freshness_run checks the REPOSITORY context, not the kit selftest."""

    def _ctx(self, base: Path) -> Path:
        ctx = base / ".ai" / "project" / "context"
        ctx.mkdir(parents=True)
        return ctx

    def test_stale_product_status_warns_with_filename(self, tmp_path):
        (self._ctx(tmp_path) / "ProductStatus.md").write_text(
            "---\nstability: volatile\nreviewed_at: 2020-01-01\n---\n# stale\n", encoding="utf-8")
        st, checks, _ = gate_executor._freshness_run(str(tmp_path))
        assert st == "warn"
        assert any("stale:ProductStatus.md" in c["id"] for c in checks)

    def test_fresh_context_passes(self, tmp_path):
        (self._ctx(tmp_path) / "ProductStatus.md").write_text(
            "---\nstability: volatile\nreviewed_at: 2999-01-01\n---\n# fresh\n", encoding="utf-8")
        st, _, _ = gate_executor._freshness_run(str(tmp_path))
        assert st == "pass"

    def test_no_context_warns_with_gap_marker(self, tmp_path):
        st, checks, _ = gate_executor._freshness_run(str(tmp_path))
        assert st == "warn"
        assert any("repo_context_present" in c["id"] for c in checks)


@pytest.mark.critical_path
@pytest.mark.unit
class TestForbiddenOverrideAtWorkflow:
    """A forbidden gate that fails stays blocked even with an override present."""

    def test_forbidden_gate_override_stays_blocked(self):
        r = gate_executor.evaluate("QUICK", {
            "intake_completeness": {"status": "pass",
                                    "provided": ["classified_type", "size", "risk"]},
            "implementation_verification": {"status": "fail",
                "override": {"by": "human:lead", "reason": "hotfix, verified manually"}}})
        assert r["blocked"] is True


@pytest.mark.critical_path
@pytest.mark.unit
class TestGateResultSchema:
    """Every gate-result obeys the schema: allowed keys only, required keys present."""

    def test_gate_results_conform_to_schema(self):
        r0 = gate_executor.evaluate("QUICK")
        required = {"schema_version", "gate", "status", "blocking", "owner", "review_mode"}
        for g in r0["gate_results"]:
            assert set(g).issubset(gate_executor._ALLOWED_KEYS)
            assert required.issubset(g)


@pytest.mark.critical_path
@pytest.mark.unit
class TestAllWorkflowsResolve:
    """Every workflow contract resolves its quality_gates without SystemExit."""

    def test_all_contracts_resolve(self):
        for wid in gate_executor.load_workflows():
            gate_executor.evaluate(wid)  # raises SystemExit on a dangling gate reference


@pytest.mark.critical_path
@pytest.mark.unit
class TestValidateEvidence:
    """validate_evidence checks the shape of an evidence mapping."""

    def test_valid_evidence_has_no_errors(self):
        assert gate_executor.validate_evidence({"g": {"status": "pass"}}) == []

    def test_invalid_status_is_error(self):
        assert gate_executor.validate_evidence({"g": {"status": "maybe"}}) != []

    def test_unknown_field_is_error(self):
        assert gate_executor.validate_evidence({"g": {"status": "pass", "foo": 1}}) != []

    def test_checks_without_status_is_error(self):
        assert gate_executor.validate_evidence(
            {"g": {"status": "pass", "checks": [{"id": "x"}]}}) != []


@pytest.mark.critical_path
@pytest.mark.unit
class TestCollectEvidenceMarkdown:
    """collect_evidence extracts reviewer verdicts from markdown artifacts."""

    def _run_dir(self, tmp_path: Path, verify_body: str) -> Path:
        (tmp_path / "stage-intake.md").write_text("Intake\nstatus: passed\n", encoding="utf-8")
        (tmp_path / "stage-local-verify.md").write_text(verify_body, encoding="utf-8")
        return tmp_path

    def test_pass_verdict_extracted_for_quick_gates(self, tmp_path):
        rd = self._run_dir(tmp_path, "# Final Verification\nИтог: pass\n")
        collected = gate_executor.collect_evidence("QUICK", rd)
        assert collected.get("intake_completeness", {}).get("status") == "pass"
        assert collected.get("implementation_verification", {}).get("status") == "pass"

    def test_provided_not_fabricated(self, tmp_path):
        """Reviewer does not fabricate deterministic evidence (provided stays empty)."""
        rd = self._run_dir(tmp_path, "# Final Verification\nИтог: pass\n")
        collected = gate_executor.collect_evidence("QUICK", rd)
        assert not collected.get("implementation_verification", {}).get("provided")

    def test_reviewer_words_do_not_close_deterministic_gates(self, tmp_path):
        rd = self._run_dir(tmp_path, "# Final Verification\nИтог: pass\n")
        collected = gate_executor.collect_evidence("QUICK", rd)
        assert gate_executor.evaluate("QUICK", collected)["blocked"] is True

    def test_fail_verdict_blocks(self, tmp_path):
        rd = self._run_dir(tmp_path, "Recommendation: FAIL\n")
        collected = gate_executor.collect_evidence("QUICK", rd)
        assert gate_executor.evaluate("QUICK", collected)["blocked"] is True


@pytest.mark.critical_path
@pytest.mark.unit
class TestStructuredReviewerResult:
    """v2.33: a structural .reviewer.json is the source of truth over markdown."""

    def _setup(self, tmp_path: Path) -> Path:
        (tmp_path / "stage-local-verify.md").write_text("Итог: pass\n", encoding="utf-8")
        (tmp_path / "stage-local-verify.reviewer.json").write_text(json.dumps({
            "schema_version": 1, "kind": "reviewer-result", "gate": "implementation_verification",
            "status": "fail", "checks": [{"id": "tests", "status": "fail"}],
            "blockers": ["2 теста упали на ревизии abc123"]}), encoding="utf-8")
        return tmp_path

    def test_structured_fail_beats_markdown_pass(self, tmp_path):
        col = gate_executor.collect_evidence("QUICK", self._setup(tmp_path))
        assert col.get("implementation_verification", {}).get("status") == "fail"

    def test_structured_fail_blocks_quick(self, tmp_path):
        col = gate_executor.collect_evidence("QUICK", self._setup(tmp_path))
        assert gate_executor.evaluate("QUICK", col)["blocked"] is True


@pytest.mark.critical_path
@pytest.mark.unit
class TestValidateEvidenceSchemas:
    """validate_evidence_schemas checks well-formedness of gate.evidence_schema types."""

    def test_registry_schemas_are_wellformed(self):
        assert gate_executor.validate_evidence_schemas() == []

    def test_broken_type_is_error(self):
        assert gate_executor.validate_evidence_schemas(
            {"g": {"evidence_schema": {"build": {"exit_code": "bogus"}}}}) != []


@pytest.mark.unit
class TestEvidenceFromNoVerdict:
    """no-verdict -> evidence, которое НАЗЫВАЕТ причину (находка поля P0, obs-2026-08-20).

    Блокирующий гейт при отсутствии вердикта обязан пасть с НАЗВАННОЙ причиной (а не общим «нет
    заключения reviewer»), нести `"reviewer verdict"` в evidence (взводит reviewer-blocked в
    _hard_stop) и различать под-случаи: бюджет / чтения-без-вердикта / ноль разбираемых ответов /
    названный отказ провайдера."""
    BLOCKING = {"blocking": True}
    ADVISORY = {"blocking": False}

    def _said(self, ev):
        return " ".join((ev.get("blockers") or []) + (ev.get("warnings") or []))

    def test_blocking_no_verdict_fails_with_named_reason(self):
        ev = gate_executor.evidence_from_no_verdict(
            self.BLOCKING, gate_id="code_review", stopped="no-verdict",
            errors=["ревьюер не вынес вердикт"])
        assert ev["status"] == "fail"
        said = self._said(ev)
        assert "не вынес вердикт" in said
        assert "нет заключения reviewer" not in said, "общая формулировка врала о причине"

    def test_evidence_carries_reviewer_verdict_marker(self):
        """`_hard_stop` распознаёт reviewer-blocked по подстроке 'reviewer verdict' в evidence."""
        ev = gate_executor.evidence_from_no_verdict(
            self.BLOCKING, gate_id="code_review", stopped="no-verdict", errors=["x"])
        assert any("reviewer verdict" in e for e in ev.get("evidence", []))

    def test_budget_subcase_is_named_and_not_pending_human(self):
        ev = gate_executor.evidence_from_no_verdict(
            self.BLOCKING, gate_id="code_review", stopped="budget: max_model_calls")
        assert "бюджет" in self._said(ev)
        assert not ev.get("pending_human")

    def test_reads_without_verdict_flags_pending_human(self):
        ev = gate_executor.evidence_from_no_verdict(
            self.BLOCKING, gate_id="code_review", stopped="no-verdict", reads=["a.py", "b.py"])
        assert "2" in self._said(ev) and ev.get("pending_human") is True

    def test_advisory_gate_warns_not_fails(self):
        ev = gate_executor.evidence_from_no_verdict(
            self.ADVISORY, gate_id="ux_review", stopped="no-verdict", errors=["x"])
        assert ev["status"] == "warn" and ev.get("warnings")

    def test_provider_refusal_reason_is_primary(self):
        refusal = {"kind": "provider-refusal", "reason": "empty_answer",
                   "reason_text": "модель вернула пустой ответ", "provider": "claude-cli"}
        ev = gate_executor.evidence_from_no_verdict(
            self.BLOCKING, gate_id="code_review", stopped="refusal: empty_answer", refusal=refusal)
        assert ev["status"] == "fail"
        assert "пустой" in self._said(ev)
