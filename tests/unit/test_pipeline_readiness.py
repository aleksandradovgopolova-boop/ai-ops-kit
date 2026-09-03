"""Юнит-тесты execution_pipeline: готовность — гейты, ревью, безопасность, evidence, approvals."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT / "tools"))

from ai_ops_kit.engine import execution_pipeline

from _pipeline_helpers import _QUICK_SIG, _init_git, _init_python_repo


@pytest.mark.critical_path
@pytest.mark.unit
class TestSecurityScanning:
    """Tests for security pack integration — fail-closed on errors."""

    def test_security_scan_key_present(self, child_root):
        """Pipeline report should include security_scan key."""
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=child_root, capture_output=True)
        (child_root / "dummy.txt").write_text("init")
        subprocess.run(["git", "add", "."], cwd=child_root, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=child_root, capture_output=True)

        def mock_proposer(ctx):
            return "done"

        report = execution_pipeline.run_pipeline(
            task="test",
            signals={"task_type": "QUICK"},
            child_root=child_root,
            proposer=mock_proposer,
        )
        assert "security_scan" in report


@pytest.mark.critical_path
@pytest.mark.unit
class TestNoSelfReview:
    """Tests for NO_SELF_REVIEW constant — gates that cannot self-review."""

    def test_no_self_review_contains_security(self):
        """NO_SELF_REVIEW should contain 'security'."""
        assert "security" in execution_pipeline.NO_SELF_REVIEW

    def test_no_self_review_contains_ai_red_team(self):
        """NO_SELF_REVIEW should contain 'ai_red_team'."""
        assert "ai_red_team" in execution_pipeline.NO_SELF_REVIEW


@pytest.mark.unit
class TestGateChecklist:
    """Tests for _gate_checklist — compact reviewer orientation."""

    def test_gate_checklist_with_evidence(self):
        gate = {"required_evidence": ["test_pass", "build_ok"], "responsible_role": "developer"}
        result = execution_pipeline._gate_checklist(gate)
        assert "developer" in result
        assert "test_pass" in result
        assert "build_ok" in result

    def test_gate_checklist_without_evidence(self):
        gate = {"responsible_role": "reviewer"}
        result = execution_pipeline._gate_checklist(gate)
        assert "reviewer" in result

    def test_gate_checklist_default_role(self):
        gate = {}
        result = execution_pipeline._gate_checklist(gate)
        assert "reviewer" in result


@pytest.mark.unit
class TestEvidenceRefErrors:
    """Tests for _evidence_ref_errors — evidence reference validation."""

    def test_empty_evidence_list(self):
        errs = execution_pipeline._evidence_ref_errors("dom", [])
        assert len(errs) > 0

    def test_non_list_evidence(self):
        errs = execution_pipeline._evidence_ref_errors("dom", "not a list")
        assert len(errs) > 0

    def test_code_read_with_path(self):
        ev = [{"type": "code-read", "path": "src/main.py", "lines": "1-10"}]
        errs = execution_pipeline._evidence_ref_errors("dom", ev)
        assert errs == []

    def test_code_read_without_path(self):
        ev = [{"type": "code-read"}]
        errs = execution_pipeline._evidence_ref_errors("dom", ev)
        assert len(errs) > 0

    def test_code_read_fabricated_path(self):
        ev = [{"type": "code-read", "path": "src/main.py"}]
        errs = execution_pipeline._evidence_ref_errors("dom", ev, reviewer_reads=["other.py"])
        assert any("сфабрикован" in e for e in errs)

    def test_code_read_matching_path(self):
        ev = [{"type": "code-read", "path": "src/main.py"}]
        errs = execution_pipeline._evidence_ref_errors("dom", ev, reviewer_reads=["src/main.py"])
        assert errs == []

    def test_test_evidence_with_command(self):
        ev = [{"type": "test", "command": "pytest"}]
        errs = execution_pipeline._evidence_ref_errors("dom", ev)
        assert errs == []

    def test_test_evidence_without_command(self):
        ev = [{"type": "test"}]
        errs = execution_pipeline._evidence_ref_errors("dom", ev)
        assert len(errs) > 0

    def test_finding_evidence_with_id(self):
        ev = [{"type": "finding", "id": "SEC001"}]
        errs = execution_pipeline._evidence_ref_errors("dom", ev)
        assert errs == []

    def test_finding_evidence_without_id(self):
        ev = [{"type": "finding"}]
        errs = execution_pipeline._evidence_ref_errors("dom", ev)
        assert len(errs) > 0

    def test_file_type_treated_as_code_read(self):
        ev = [{"type": "file", "path": "src/main.py"}]
        errs = execution_pipeline._evidence_ref_errors("dom", ev, reviewer_reads=["src/main.py"])
        assert errs == []

    def test_unknown_type_without_path(self):
        ev = [{"type": "vibes"}]
        errs = execution_pipeline._evidence_ref_errors("dom", ev)
        assert len(errs) > 0

    def test_non_dict_evidence(self):
        errs = execution_pipeline._evidence_ref_errors("dom", ["just a string"])
        assert len(errs) > 0


@pytest.mark.unit
class TestSecurityVerdictErrors:
    """Tests for _security_verdict_errors — security reviewer verdict validation."""

    def _make_vrr(self):
        import validate_reviewer_result as vrr
        return vrr

    def test_non_dict_result(self):
        errs = execution_pipeline._security_verdict_errors(None, "rev", [], self._make_vrr())
        assert len(errs) > 0

    def test_bare_pass_is_invalid(self):
        errs = execution_pipeline._security_verdict_errors(
            {"status": "pass"}, "abc123", ["injection"], self._make_vrr())
        assert len(errs) > 0

    def test_valid_structured_pass(self):
        good = {
            "schema_version": 1, "kind": "reviewer-result", "gate": "security",
            "status": "pass", "reviewed_revision": "abc123",
            "checks": [{"id": "injection", "status": "pass"}],
            "domain_results": [{"domain": "injection", "status": "pass",
                                "checks": [{"id": "no_inj", "status": "pass"}],
                                "evidence": [{"type": "code-read", "path": "a.py", "lines": "1-5"}]}]
        }
        errs = execution_pipeline._security_verdict_errors(good, "abc123", ["injection"], self._make_vrr())
        assert errs == []

    def test_wrong_revision(self):
        good = {
            "schema_version": 1, "kind": "reviewer-result", "gate": "security",
            "status": "pass", "reviewed_revision": "OTHER",
            "checks": [{"id": "injection", "status": "pass"}],
            "domain_results": [{"domain": "injection", "status": "pass",
                                "checks": [{"id": "no_inj", "status": "pass"}],
                                "evidence": [{"type": "code-read", "path": "a.py", "lines": "1-5"}]}]
        }
        errs = execution_pipeline._security_verdict_errors(good, "abc123", ["injection"], self._make_vrr())
        assert any("revision" in e for e in errs)

    def test_missing_domain_results(self):
        res = {
            "schema_version": 1, "kind": "reviewer-result", "gate": "security",
            "status": "pass", "reviewed_revision": "abc123",
            "checks": [{"id": "sec", "status": "pass"}]
        }
        errs = execution_pipeline._security_verdict_errors(res, "abc123", ["injection"], self._make_vrr())
        assert any("domain_results" in e for e in errs)

    def test_domain_results_missing_domain(self):
        res = {
            "schema_version": 1, "kind": "reviewer-result", "gate": "security",
            "status": "pass", "reviewed_revision": "abc123",
            "checks": [{"id": "sec", "status": "pass"}],
            "domain_results": [{"domain": "injection", "status": "pass",
                                "checks": [{"id": "ok", "status": "pass"}],
                                "evidence": [{"type": "code-read", "path": "a.py"}]}]
        }
        errs = execution_pipeline._security_verdict_errors(
            res, "abc123", ["injection", "secrets"], self._make_vrr())
        assert any("не покрывает" in e for e in errs)

    def test_warn_domain_with_pass_overall(self):
        res = {
            "schema_version": 1, "kind": "reviewer-result", "gate": "security",
            "status": "pass", "reviewed_revision": "abc123",
            "checks": [{"id": "sec", "status": "pass"}],
            "domain_results": [{"domain": "injection", "status": "warn",
                                "checks": [{"id": "ok", "status": "pass"}]}]
        }
        errs = execution_pipeline._security_verdict_errors(res, "abc123", ["injection"], self._make_vrr())
        assert any("несогласованно" in e for e in errs)


@pytest.mark.unit
class TestReviewableGates:
    """Tests for _reviewable_gates — which gates can be self-reviewed."""

    def test_security_excluded(self):
        result = execution_pipeline._reviewable_gates(["security", "ux_review"], {})
        assert "security" not in result

    def test_ai_red_team_excluded(self):
        result = execution_pipeline._reviewable_gates(["ai_red_team", "ux_review"], {})
        assert "ai_red_team" not in result

    def test_empty_gates(self):
        result = execution_pipeline._reviewable_gates([], {})
        assert result == []


@pytest.mark.unit
class TestOpenspecValidate:
    """Tests for _openspec_validate — openspec CLI integration."""

    def test_cli_not_found(self, child_root):
        _init_git(child_root)
        available, ok, output = execution_pipeline._openspec_validate(child_root, "test-change")
        # openspec CLI is likely not installed in test env
        if not available:
            assert "не найден" in output


@pytest.mark.unit
class TestReevaluateArtifactEvidence:
    """Tests for _reevaluate_artifact_evidence — re-derive evidence from disk."""

    def test_reevaluate_with_existing_artifacts(self, child_root):
        _init_git(child_root)
        out_dir = child_root / ".ai" / "runplan" / "reeval-wid"
        out_dir.mkdir(parents=True)
        (out_dir / "requirements.yaml").write_text(
            "schema_version: 1\nkind: requirements-artifact\n"
            "requirements:\n  - id: R1\n    statement: test requirement\n"
            "    acceptance:\n      - when x then y\n",
            encoding="utf-8")
        ev = execution_pipeline._reevaluate_artifact_evidence(child_root, "reeval-wid",
                                                              ["requirements"])
        assert "requirements" in ev
        assert ev["requirements"]["status"] == "pass"

    def test_reevaluate_missing_artifacts(self, child_root):
        _init_git(child_root)
        ev = execution_pipeline._reevaluate_artifact_evidence(child_root, "no-wid",
                                                              ["requirements"])
        assert "requirements" not in ev

    def test_reevaluate_skips_nonexistent_gate(self, child_root):
        _init_git(child_root)
        ev = execution_pipeline._reevaluate_artifact_evidence(child_root, "no-wid",
                                                              ["nonexistent_gate"])
        assert ev == {}


@pytest.mark.unit
class TestRunPipelineOverallStatus:
    """Tests for overall_status computation."""

    def test_error_status_on_preflight_fail(self, child_root):
        _init_git(child_root)
        report = execution_pipeline.run_pipeline(
            task="test",
            signals={"task_type": "QUICK"},
            child_root=child_root,
            proposer=lambda ctx: {"done": True},
            budget={"max_model_calls": 5},
            base="nonexistent-branch-xyz",
            isolate=True,
        )
        assert report["overall_status"] == "error"

    def test_ready_undelivered_with_open_pr(self, child_root):
        _init_git(child_root)
        import os
        saved = {k: os.environ.pop(k, None) for k in ("GITHUB_TOKEN", "GH_TOKEN")}
        try:
            ops = iter([{"op": "write", "path": "src/st.py", "content": "s = 1\n"}, {"done": True}])
            report = execution_pipeline.run_pipeline(
                task="status test",
                signals={"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]},
                child_root=child_root,
                proposer=lambda ctx: next(ops),
                budget={"max_model_calls": 10},
                feature="status-test",
                commit=True,
                isolate=True,
                open_pr=True,
                install_deps=False,
            )
            if report["ready_for_pr"]:
                assert report["overall_status"] == "ready-undelivered"
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v


@pytest.mark.unit
class TestReviewableGatesAdditional:
    """Additional tests for _reviewable_gates with real gate loading."""

    def test_ux_review_is_reviewable(self):
        # ux_review should be ai-review type and thus reviewable
        result = execution_pipeline._reviewable_gates(["ux_review"], {"ui_changed": True})
        assert "ux_review" in result

    def test_code_review_is_reviewable(self):
        result = execution_pipeline._reviewable_gates(["code_review"], {})
        assert "code_review" in result

    def test_deterministic_gates_not_reviewable(self):
        # requirements/specification are deterministic, not ai-review
        result = execution_pipeline._reviewable_gates(["requirements", "specification"], {})
        assert "requirements" not in result
        assert "specification" not in result


@pytest.mark.critical_path
@pytest.mark.unit
class TestRunPipelineReview:
    """Tests for run_pipeline with review=True — independent reviewer integration."""

    def test_review_without_review_proposer(self, child_root):
        _init_git(child_root)
        sig = {"task_type": "QUICK", "size": "small", "risk": "low",
               "affected_areas": ["core"], "ui_changed": True}
        ops = iter([{"op": "write", "path": "src/rv.py", "content": "r = 1\n"}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="review test",
            signals=sig,
            child_root=child_root,
            proposer=lambda ctx: next(ops),
            budget={"max_model_calls": 10},
            feature="rv-test",
            commit=True,
            isolate=True,
            install_deps=False,
        )
        # review not requested -> reviews is None
        assert report["reviews"] is None

    def test_review_with_fail_reviewer(self, child_root):
        _init_git(child_root)
        sig = {"task_type": "QUICK", "size": "small", "risk": "low",
               "affected_areas": ["core"], "ui_changed": True}
        fail_reviewer = lambda prompt: (
            '{"kind":"reviewer-result","status":"fail",'
            '"checks":[{"id":"ux","status":"fail"}],'
            '"blockers":["no states"]}')
        ops = iter([{"op": "write", "path": "src/rvf.py", "content": "r = 1\n"}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="review fail test",
            signals=sig,
            child_root=child_root,
            proposer=lambda ctx: next(ops),
            budget={"max_model_calls": 20},
            feature="rvf-test",
            commit=True,
            isolate=True,
            install_deps=False,
            review=True,
            reviewer_proposer=fail_reviewer,
        )
        # review ran -> reviews is not None
        assert report["reviews"] is not None
        assert any(r["gate"] == "ux_review" and r["status"] == "fail" for r in report["reviews"])
        # ux_review should be in unmet (reviewer said fail)
        assert "ux_review" in report["gates"]["unmet"]


@pytest.mark.unit
class TestRunPipelineApprovalRecheck:
    """Tests for approval_recheck in report."""

    def test_approval_recheck_present(self, child_root):
        _init_git(child_root)
        ops = iter([{"op": "write", "path": "src/ar.py", "content": "a = 1\n"}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="approval test",
            signals={"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]},
            child_root=child_root,
            proposer=lambda ctx: next(ops),
            budget={"max_model_calls": 10},
            feature="ar-test",
            commit=True,
        )
        assert "approval_recheck" in report
        assert isinstance(report["approval_recheck"], dict)
        assert "ok" in report["approval_recheck"]


@pytest.mark.unit
class TestSecurityFailClosed:
    """security pack бросил -> security=fail (fail-closed, не ложный green)."""

    def test_scan_raises_security_unmet_not_ready(self, child_root):
        _init_python_repo(child_root)
        from ai_ops_kit.engine import tool_broker
        from ai_ops_kit.security import security_pack as sp_mod
        sig_eng = {"task_type": "ENGINEERING", "size": "small", "risk": "medium",
                   "affected_areas": ["core"]}
        pol = tool_broker.Policy(level="execution", write_scope=["src/"])
        orig_rp = sp_mod.run_pack
        sp_mod.run_pack = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("scan boom"))
        try:
            it_se = iter([{"op": "write", "path": "src/se.py", "content": "s=1\n"}, {"done": True}])
            rep_se = execution_pipeline.run_pipeline(
                "скан падает", sig_eng, child_root, lambda c: next(it_se),
                policy=pol, budget={"max_model_calls": 5}, feature="scanerr-fn",
                commit=True, isolate=True, install_deps=False)
        finally:
            sp_mod.run_pack = orig_rp
        assert "security" in rep_se["gates"]["unmet"]
        assert not rep_se["ready_for_pr"]


@pytest.mark.unit
class TestSecurityForcedInQuick:
    """QUICK + новая зависимость -> security ФОРСИРОВАН в evaluated и блокирует без ApprovalRecord."""

    def test_security_forced_evaluated(self, child_root):
        _init_python_repo(child_root)
        from ai_ops_kit.engine import tool_broker
        pol_dep = tool_broker.Policy(level="execution", block_push=True)
        it_dep = iter([{"op": "write", "path": "requirements.txt", "content": "flask\n"}, {"done": True}])
        rep_dep = execution_pipeline.run_pipeline(
            "добавить зависимость", _QUICK_SIG, child_root, lambda c: next(it_dep),
            policy=pol_dep, budget={"max_model_calls": 5}, feature="dep-fn",
            commit=True, isolate=True, install_deps=False)
        assert "security" in rep_dep["gates"]["evaluated"]
        assert "security" in rep_dep["gates"]["unmet"]
        assert rep_dep["ready_for_pr"] is False


@pytest.mark.unit
class TestSecurityReviewerCloses:
    """Независимый security-reviewer pass закрывает needs_review домены -> security не в unmet."""

    def test_reviewer_pass_closes_security(self, child_root):
        _init_python_repo(child_root)
        from ai_ops_kit.engine import tool_broker
        sig_eng = {"task_type": "ENGINEERING", "size": "small", "risk": "medium",
                   "affected_areas": ["core"]}
        pol = tool_broker.Policy(level="execution", write_scope=["src/"])
        sec_reviewer = lambda c: {"kind": "reviewer-result", "status": "pass",  # noqa: E731
                                  "summary": "injection-surface чист"}
        it = iter([{"op": "write", "path": "src/clean.py", "content": "def f():\n    return 1\n"},
                   {"done": True}])
        rep = execution_pipeline.run_pipeline(
            "чистая правка", sig_eng, child_root, lambda c: next(it),
            policy=pol, budget={"max_model_calls": 8}, feature="secrev-fn",
            commit=True, isolate=True, install_deps=False,
            review=True, reviewer_proposer=sec_reviewer)
        assert "security" not in rep["gates"]["unmet"]


@pytest.mark.unit
class TestSecurityGuard5:
    """#5-guard: qualified судья не берёт; нет судьи+нет ApprovalRecord -> fail + называет ApprovalRecord."""

    def _sec_result(self, rep):
        return next((g for g in rep["gates"].get("gate_results", [])
                     if g.get("gate") == "security"), {})

    @staticmethod
    def _has(g, sub):
        return any(sub in b for b in (g.get("blockers") or []))

    def _sec_reviewer(self):
        return lambda c: {"kind": "reviewer-result", "status": "pass",  # noqa: E731
                          "summary": "injection-surface чист"}

    def test_qualified_judge_skips_guard5(self, child_root):
        _init_python_repo(child_root)
        from ai_ops_kit.engine import tool_broker
        pol = tool_broker.Policy(level="execution", write_scope=["src/"])
        sig_api = {"task_type": "ENGINEERING", "size": "small", "risk": "medium",
                   "affected_areas": ["core"], "api_change": True}
        it_q = iter([{"op": "write", "path": "src/rl_a.py", "content": "def a():\n    return 1\n"}, {"done": True}])
        rep_q = execution_pipeline.run_pipeline(
            "api rate strict-on", sig_api, child_root, lambda c: next(it_q),
            policy=pol, budget={"max_model_calls": 8}, feature="rl-q-fn",
            commit=True, isolate=True, install_deps=False,
            review=True, reviewer_proposer=self._sec_reviewer(), strict_judge_qualified=True)
        sec_a = self._sec_result(rep_q)
        # qualified судья -> reviewer-ветка: #5 pending_human-guard НЕ берётся
        assert not self._has(sec_a, "нет QUALIFIED security-судьи")

    def test_no_qualified_judge_no_approval_fails(self, child_root):
        _init_python_repo(child_root)
        from ai_ops_kit.engine import tool_broker
        pol = tool_broker.Policy(level="execution", write_scope=["src/"])
        sig_api = {"task_type": "ENGINEERING", "size": "small", "risk": "medium",
                   "affected_areas": ["core"], "api_change": True}
        it = iter([{"op": "write", "path": "src/rl_b.py", "content": "def b():\n    return 1\n"}, {"done": True}])
        rep = execution_pipeline.run_pipeline(
            "api rate strict-off", sig_api, child_root, lambda c: next(it),
            policy=pol, budget={"max_model_calls": 8}, feature="rl-b-fn",
            commit=True, isolate=True, install_deps=False,
            review=True, reviewer_proposer=self._sec_reviewer(), strict_judge_qualified=False)
        sec_b = self._sec_result(rep)
        assert "security" in rep["gates"]["unmet"]
        assert sec_b.get("status") == "fail"
        assert self._has(sec_b, "нет QUALIFIED security-судьи")
        # блокер называет ApprovalRecord (человеку даётся путь закрыть)
        assert self._has(sec_b, "ApprovalRecord")


@pytest.mark.unit
class TestReevaluateOnly:
    """re-evaluate-only: человеко-одобрение снимает #5-блок БЕЗ переавторинга кода."""

    def test_approval_lifts_guard5_via_reevaluate(self, child_root):
        _init_python_repo(child_root)
        from ai_ops_kit.engine import tool_broker
        from ai_ops_kit.security import security_pack as sp_re
        from ai_ops_kit.gates import approvals as appr_re
        pol = tool_broker.Policy(level="execution", write_scope=["src/"])
        sec_reviewer = lambda c: {"kind": "reviewer-result", "status": "pass",  # noqa: E731
                                  "summary": "чист"}
        sig_q = {"task_type": "QUICK", "size": "small", "risk": "low",
                 "affected_areas": ["api"], "api_change": True}
        it_q1 = iter([{"op": "write", "path": "rq.py", "content": "def rq():\n    return 1\n"}, {"done": True}])
        execution_pipeline.run_pipeline(
            "quick api sec", sig_q, child_root, lambda c: next(it_q1), policy=pol,
            budget={"max_model_calls": 8}, feature="reeval-fn", commit=True, isolate=True,
            install_deps=False, review=True, reviewer_proposer=sec_reviewer,
            strict_judge_qualified=False)
        nrq = sp_re.run_pack(files_content={"rq.py": "def rq():\n    return 1\n"},
                             signals=sig_q).get("needs_review") or ["rate_limiting"]
        rf = child_root / "features" / "reeval-fn"
        rf.mkdir(parents=True, exist_ok=True)
        (rf / "run-plan.yaml").write_text("base_workflow: QUICK\ngates: [security]\n", encoding="utf-8")
        for d in nrq:
            appr_re.write_record(child_root, "reeval-fn", approval=d, approved_by="human@owner",
                                 scope=f"security {d}", reason="человек одобрил (reeval тест)",
                                 created_at="2026-07-29", expires_at="2026-12-31",
                                 risk="medium", source="human")
        rep_re = execution_pipeline.run_pipeline(
            "quick api sec", sig_q, child_root, lambda c: {"done": True}, policy=pol,
            budget={"max_model_calls": 8}, feature="reeval-fn", commit=True, isolate=True,
            install_deps=False, review=True, reviewer_proposer=sec_reviewer,
            strict_judge_qualified=False, reevaluate_only=True)
        sec_re = next((g for g in rep_re["gates"].get("gate_results", [])
                       if g.get("gate") == "security"), {})
        assert (rep_re.get("loop") or {}).get("stopped") == "reevaluate-only"
        assert not any("нет QUALIFIED security-судьи" in b for b in (sec_re.get("blockers") or []))


@pytest.mark.unit
class TestSecretBoundary:
    """secret_boundary требует человека даже при pass ревьюера."""

    def test_secret_boundary_without_human_blocks(self, child_root):
        _init_python_repo(child_root)
        from ai_ops_kit.engine import tool_broker
        sig_eng = {"task_type": "ENGINEERING", "size": "small", "risk": "medium",
                   "affected_areas": ["core"], "secret_boundary": True}
        pol = tool_broker.Policy(level="execution", write_scope=["src/"])
        sec_reviewer = lambda c: {"kind": "reviewer-result", "status": "pass", "summary": "чист"}  # noqa: E731
        it_sb = iter([{"op": "write", "path": "src/sb.py", "content": "def g():\n    return 2\n"}, {"done": True}])
        rep_sb = execution_pipeline.run_pipeline(
            "граница секретов", sig_eng, child_root, lambda c: next(it_sb),
            policy=pol, budget={"max_model_calls": 8}, feature="sb-fn",
            commit=True, isolate=True, install_deps=False,
            review=True, reviewer_proposer=sec_reviewer)
        assert "security" in rep_sb["gates"]["unmet"]


@pytest.mark.unit
class TestBaselineDoesNotBypassGates:
    """P0.1: baseline-diff НЕ обходит прочие блокирующие гейты (ux_review без evidence)."""

    def test_ui_changed_ux_review_blocks_despite_no_regressions(self, child_root):
        _init_python_repo(child_root)
        from ai_ops_kit.engine import tool_broker
        sig_ui = dict(_QUICK_SIG, ui_changed=True)
        pol = tool_broker.Policy(level="execution", write_scope=["src/"])
        it = iter([{"op": "write", "path": "src/p01.py", "content": "p=1\n"}, {"done": True}])
        rep = execution_pipeline.run_pipeline(
            "baseline не обходит гейты", sig_ui, child_root, lambda c: next(it),
            policy=pol, budget={"max_model_calls": 5}, feature="p01-fn",
            commit=True, baseline_diff=True)
        assert rep["gates"]["other_blocking_unmet"]
        assert rep["ready_for_pr"] is False

    def test_gate_results_and_tested_revision_in_report(self, child_root):
        _init_python_repo(child_root)
        from ai_ops_kit.engine import tool_broker
        sig_ui = dict(_QUICK_SIG, ui_changed=True)
        pol = tool_broker.Policy(level="execution", write_scope=["src/"])
        it = iter([{"op": "write", "path": "src/p01.py", "content": "p=1\n"}, {"done": True}])
        rep = execution_pipeline.run_pipeline(
            "baseline gate_results", sig_ui, child_root, lambda c: next(it),
            policy=pol, budget={"max_model_calls": 5}, feature="p01b-fn",
            commit=True, baseline_diff=True)
        assert isinstance(rep["gates"]["gate_results"], list)
        assert rep["gates"]["tested_revision"] == rep["commit"]["sha"]


@pytest.mark.unit
class TestReviewUiGateBlocksWithoutReview:
    """ui_changed -> ux_review в evaluated+unmet, reviews=None без --review."""

    def test_ux_review_blocks_without_reviewer(self, child_root):
        _init_python_repo(child_root)
        sig_rv = dict(_QUICK_SIG, ui_changed=True)
        it = iter([{"op": "write", "path": "src/nr.py", "content": "n=1\n"}, {"done": True}])
        rep = execution_pipeline.run_pipeline(
            "ui без ревью", sig_rv, child_root, lambda c: next(it),
            budget={"max_model_calls": 5}, feature="nr-fn",
            commit=True, isolate=True, install_deps=False)
        assert "ux_review" in rep["gates"]["evaluated"]
        assert "ux_review" in rep["gates"]["unmet"]
        assert rep["reviews"] is None


@pytest.mark.unit
class TestReviewContentlessWarn:
    """rc11: contentless warn (без blockers) -> вердикт невалиден (errors), гейт остаётся unmet."""

    def test_warn_without_blockers_invalid_verdict(self, child_root):
        _init_python_repo(child_root)
        sig_rv = dict(_QUICK_SIG, ui_changed=True)
        cwarn = lambda p: '{"kind":"reviewer-result","status":"warn","checks":[{"id":"x","status":"warn"}]}'  # noqa: E731
        it = iter([{"op": "write", "path": "src/cw.py", "content": "c=1\n"}, {"done": True}])
        rep = execution_pipeline.run_pipeline(
            "ui с ревью warn без причины", sig_rv, child_root, lambda c: next(it),
            budget={"max_model_calls": 20}, feature="cw-fn",
            commit=True, isolate=True, install_deps=False,
            review=True, reviewer_proposer=cwarn)
        assert "ux_review" in rep["gates"]["unmet"]
        assert any(r["gate"] == "ux_review" and r.get("errors") for r in (rep["reviews"] or []))


@pytest.mark.unit
class TestEvidenceRefSameBasename:
    """EvidenceRef: same-basename другой путь -> 'которого нет среди реально прочитанных'."""

    def _make_vrr(self):
        import validate_reviewer_result as vrr
        return vrr

    def _dom_ev(self, ev):
        return {"schema_version": 1, "kind": "reviewer-result", "gate": "security", "status": "pass",
                "reviewed_revision": "abc123", "checks": [{"id": "c", "status": "pass"}],
                "domain_results": [{"domain": "injection", "status": "pass",
                                    "checks": [{"id": "injection_ok", "status": "pass"}], "evidence": ev}]}

    def test_same_basename_different_path_invalid(self):
        errs = execution_pipeline._security_verdict_errors(
            self._dom_ev([{"type": "code-read", "path": "src/prod/config.py"}]),
            "abc123", ["injection"], self._make_vrr(), reviewer_reads=["tests/config.py"])
        assert any("которого нет среди реально прочитанных" in e for e in errs)


@pytest.mark.unit
class TestApprovalsRecordValid:
    """approvals._record_valid: рыхлая destructive-запись невалидна в обоих режимах."""

    def test_loose_destructive_invalid_both_modes(self):
        from ai_ops_kit.gates import approvals as a4
        loose = {"approval": "destructive", "approved_by": "u@x", "scope": ".", "reason": "ok"}
        assert a4._record_valid(loose, now=a4._now_iso(), plan_hash="x") is False
        assert a4._record_valid(loose, now=a4._now_iso(), plan_hash="x", strict=True) is False

    def test_bound_destructive_passes_nonstrict_not_strict(self):
        from ai_ops_kit.gates import approvals as a4
        bound = {"approval": "destructive", "approved_by": "u@x", "scope": ".",
                 "reason": "ok", "binds_to": "x"}
        assert a4._record_valid(bound, now=a4._now_iso(), plan_hash="x") is True
        assert a4._record_valid(bound, now=a4._now_iso(), plan_hash="x", strict=True) is False


@pytest.mark.unit
class TestHumanApprovalDomains:
    """_human_approval_domains_uncovered: Dockerfile/.github -> deployment_config; src -> []."""

    def test_dockerfile_requires_deployment_config(self, child_root):
        _init_git(child_root)
        assert "deployment_config" in execution_pipeline._human_approval_domains_uncovered(
            str(child_root), "no-wi", ["Dockerfile", "src/x.py"])

    def test_github_workflows_requires_deployment_config(self, child_root):
        _init_git(child_root)
        assert "deployment_config" in execution_pipeline._human_approval_domains_uncovered(
            str(child_root), "no-wi", [".github/workflows/deploy.yml"])

    def test_regular_src_no_human_approval(self, child_root):
        _init_git(child_root)
        assert execution_pipeline._human_approval_domains_uncovered(
            str(child_root), "no-wi", ["src/app.py", "tests/t.py"]) == []

    def test_legacy_loose_approval_does_not_close(self, child_root):
        _init_git(child_root)
        import yaml as yaml_mod
        ad = child_root / "features" / "no-wi" / "approvals"
        ad.mkdir(parents=True, exist_ok=True)
        (ad / "deployment_config.yaml").write_text(yaml_mod.safe_dump(
            {"schema_version": 1, "kind": "ApprovalRecord", "approval": "deployment_config",
             "approved_by": "u@x", "scope": ".", "reason": "ok"}, allow_unicode=True), encoding="utf-8")
        assert "deployment_config" in execution_pipeline._human_approval_domains_uncovered(
            str(child_root), "no-wi", ["Dockerfile"])
