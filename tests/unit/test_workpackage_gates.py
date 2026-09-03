"""Гранулярные тесты workpackage_executor: hard-stop, ошибки провайдера, ревью-гейты, агрегатные проверки.

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import contextlib
import io
import tempfile

import pytest

from workpackage_executor import (
    Path,
    _aggregate_close_security,
    _aggregate_code_review,
    _hard_stop,
    execute_sequence,
    json,
)

import atomic_planner

from _workpackage_helpers import (
    _author,
    _mkrepo,
    _pass_reviewer,
    _prop_for,
)


# ─── _hard_stop ────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestHardStop:
    def test_no_commit_stop(self):
        assert _hard_stop({"commit": {"sha": None}}) == "no-commit"

    def test_regression_stop(self):
        assert _hard_stop({"commit": {"sha": "a"}, "baseline": {"regressions": ["test"]}}) == "regression"

    def test_security_fail_stop(self):
        assert _hard_stop({"commit": {"sha": "a"}, "security_scan": {"overall": "fail"}}) == "security-fail"

    def test_reviewer_fail_stop(self):
        assert _hard_stop({"commit": {"sha": "a"}, "reviews": [{"gate": "code_review", "status": "fail"}]}) == "reviewer-blocked"

    def test_reviewer_warn_blocking_stop(self):
        assert _hard_stop({"commit": {"sha": "a"},
                           "reviews": [{"gate": "code_review", "status": "warn", "closed_as": "blocked"}]}) == "reviewer-blocked"

    def test_gate_results_fail_stop(self):
        assert _hard_stop({"commit": {"sha": "a"}, "reviews": [],
                           "gates": {"gate_results": [{"gate": "code_review", "status": "fail",
                                     "evidence": ["independent reviewer verdict @ abc"]}]}}) == "reviewer-blocked"

    def test_reviewer_warn_nonblocking_no_stop(self):
        assert _hard_stop({"commit": {"sha": "a"},
                           "reviews": [{"gate": "code_review", "status": "warn", "closed_as": "warn"}]}) is None

    def test_scope_violation_stop(self):
        assert _hard_stop({"commit": {"sha": "a"}, "loop": {"denied_reasons": ["'x' вне write_scope ['src']"]}}) == "scope-violation"

    def test_awaiting_evidence_no_stop(self):
        assert _hard_stop({"commit": {"sha": "a"}, "gates": {"blocked": True, "unmet": ["requirements"]}}) is None

    def test_blocked_push_not_scope_violation(self):
        assert _hard_stop({"commit": {"sha": "a"}, "loop": {"denied_reasons": ["git push запрещён политикой"]}}) is None

    def test_security_scan_blocked_stop(self):
        assert _hard_stop({"commit": {"sha": "a"}, "security_scan": {"overall": "blocked"}}) == "security-fail"

    def test_security_gate_fail_no_approval(self):
        def _g(blk):
            return {"commit": {"sha": "a"}, "gates": {"gate_results": [
                {"gate": "security", "status": "fail", "blockers": [blk]}]}}
        assert _hard_stop(_g("dependencies: нет валидного ApprovalRecord")) == "security-gate-fail"

    def test_security_gate_fail_scanner_crash(self):
        def _g(blk):
            return {"commit": {"sha": "a"}, "gates": {"gate_results": [
                {"gate": "security", "status": "fail", "blockers": [blk]}]}}
        assert _hard_stop(_g("security scan упал (fail-closed): boom")) == "security-gate-fail"

    def test_security_gate_fail_no_pass(self):
        def _g(blk):
            return {"commit": {"sha": "a"}, "gates": {"gate_results": [
                {"gate": "security", "status": "fail", "blockers": [blk]}]}}
        assert _hard_stop(_g("security-reviewer не вынес pass")) == "security-gate-fail"

    def test_needs_review_awaiting_no_stop(self):
        assert _hard_stop({"commit": {"sha": "a"}, "security_scan": {"overall": "needs_review"},
                           "gates": {"gate_results": [{"gate": "security", "status": "fail",
                           "blockers": ["нужен независимый security-reviewer/человек по доменам: input_validation"]}]}}) is None


# ─── Provider exception handling ───────────────────────────────────────────────

@pytest.mark.unit
class TestProviderException:
    def test_connection_reset_honest_failure(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            rx = Path(td)
            cur_x = _mkrepo(td)
            pkgs_x = atomic_planner.decompose(three_area_sig, wid="seqx", child_root=rx)["work_packages"]

            def prop_boom(pkg):
                return lambda c: {"done": True}

            def boom_author(prompt):
                raise ConnectionResetError("[Errno 54] Connection reset by peer")

            seq_x = execute_sequence("x", three_area_sig, rx, pkgs_x, prop_boom, feature="seqx",
                                     base=cur_x, author=True, author_proposer=boom_author, review=False)
            p0 = seq_x["packages"][0] if seq_x.get("packages") else {}
            assert bool(p0.get("stop_reason"))
            assert "error" in (p0.get("stop_reason") or "")

    def test_failure_classified_network_retryable(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            rx = Path(td)
            cur_x = _mkrepo(td)
            pkgs_x = atomic_planner.decompose(three_area_sig, wid="seqx", child_root=rx)["work_packages"]

            def prop_boom(pkg):
                return lambda c: {"done": True}

            def boom_author(prompt):
                raise ConnectionResetError("[Errno 54] Connection reset by peer")

            seq_x = execute_sequence("x", three_area_sig, rx, pkgs_x, prop_boom, feature="seqx",
                                     base=cur_x, author=True, author_proposer=boom_author, review=False)
            p0 = seq_x["packages"][0] if seq_x.get("packages") else {}
            assert (p0.get("failure") or {}).get("failure_class") == "network"
            assert (p0.get("failure") or {}).get("retryable") is True
            assert (p0.get("failure") or {}).get("exception_type") == "ConnectionResetError"
            assert (p0.get("failure") or {}).get("traceback_hash")

    def test_chain_stops_at_failed_package(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            rx = Path(td)
            cur_x = _mkrepo(td)
            pkgs_x = atomic_planner.decompose(three_area_sig, wid="seqx", child_root=rx)["work_packages"]

            def prop_boom(pkg):
                return lambda c: {"done": True}

            def boom_author(prompt):
                raise ConnectionResetError("[Errno 54] Connection reset by peer")

            seq_x = execute_sequence("x", three_area_sig, rx, pkgs_x, prop_boom, feature="seqx",
                                     base=cur_x, author=True, author_proposer=boom_author, review=False)
            assert seq_x.get("stopped_at") == pkgs_x[0]["id"]
            assert len(seq_x["packages"]) == 1
            assert seq_x["executed_all"] is False
            assert seq_x["ready_all"] is False

    def test_per_package_snapshot_saved(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            rx = Path(td)
            cur_x = _mkrepo(td)
            pkgs_x = atomic_planner.decompose(three_area_sig, wid="seqx", child_root=rx)["work_packages"]

            def prop_boom(pkg):
                return lambda c: {"done": True}

            def boom_author(prompt):
                raise ConnectionResetError("[Errno 54] Connection reset by peer")

            execute_sequence("x", three_area_sig, rx, pkgs_x, prop_boom, feature="seqx",
                             base=cur_x, author=True, author_proposer=boom_author, review=False)
            assert (rx / "features" / "seqx" / "work-packages" / pkgs_x[0]["id"] / "report.json").is_file()


# ─── open_pr not ready ─────────────────────────────────────────────────────────

@pytest.mark.unit
class TestOpenPrNotReady:
    def test_not_ready_all_pr_not_opened(self, two_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(two_area_sig, wid="seqpr", child_root=root)["work_packages"]

            def prop_pr(pkg):
                it = iter([{"op": "write", "path": f"src/{pkg['id']}.py", "content": "x=1\n"}, {"done": True}])
                return lambda c: next(it)

            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                seqpr = execute_sequence("рефактор", two_area_sig, root, pkgs, prop_pr, feature="seqpr",
                                         base=cur, open_pr=True)
            dpr = seqpr.get("delivery") or {}
            assert seqpr["ready_all"] is False
            assert dpr.get("status") == "not-attempted"
            assert seqpr.get("draft_pr") is None
            assert dpr.get("requested") is True


# ─── Reviewer fail/warn stops chain ───────────────────────────────────────────

@pytest.mark.unit
class TestReviewerFailStopsChain:
    def test_reviewer_fail_stops_chain(self, three_area_sig):
        def fail_reviewer(prompt):
            return json.dumps({"kind": "reviewer-result", "status": "fail",
                               "checks": [{"id": "c", "status": "fail"}], "blockers": ["FAIL"]})

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seqr", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                seqr = execute_sequence("рефактор с fail-ревью", three_area_sig, root, pkgs, _prop_for,
                                        feature="seqr", base=cur, author=True, author_proposer=_author,
                                        review=True, reviewer_proposer=fail_reviewer)
            ids_seen = [p["id"] for p in seqr["packages"]]
            assert seqr["stopped_at"] == pkgs[0]["id"]
            assert seqr["executed_all"] is False
            assert seqr["packages"][0]["stop_reason"] == "reviewer-blocked"
            assert pkgs[2]["id"] not in ids_seen


@pytest.mark.unit
class TestReviewerWarnBlockingStopsChain:
    def test_reviewer_warn_blocking_stops_chain(self, three_area_sig):
        warn_reviewer = lambda p: ('{"kind":"reviewer-result","status":"warn",'
                                   '"checks":[{"id":"c","status":"warn"}],"blockers":["сомнение по API"]}')

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seqw", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                seqw = execute_sequence("рефактор с warn-ревью", three_area_sig, root, pkgs, _prop_for,
                                        feature="seqw", base=cur, author=True, author_proposer=_author,
                                        review=True, reviewer_proposer=warn_reviewer)
            ids_w = [p["id"] for p in seqw["packages"]]
            assert seqw["stopped_at"] == pkgs[0]["id"]
            assert seqw["executed_all"] is False
            assert seqw["packages"][0]["stop_reason"] == "reviewer-blocked"
            assert pkgs[2]["id"] not in ids_w


# ─── aggregate code_review ─────────────────────────────────────────────────────

@pytest.mark.unit
class TestAggregateCodeReview:
    def test_no_verdict_ok_false(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            nover = lambda p: "я не буду выносить структурный вердикт, просто текст"
            ok_nv, _ = _aggregate_code_review(root, cur, cur, {"task_type": "ENGINEERING"}, nover, True)
            assert ok_nv is False

    def test_no_review_requested_ok_true(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            ok_nr, _ = _aggregate_code_review(root, cur, cur, {}, None, False)
            assert ok_nr is True


# ─── aggregate_close_security ──────────────────────────────────────────────────

@pytest.mark.unit
class TestAggregateCloseSecurity:
    def test_generic_reviewer_does_not_close_security(self):
        import approvals as _appr_t
        isha = "a" * 40
        agg_nr = {"overall": "needs_review", "needs_review": ["rate_limiting"], "results": []}
        gen_reviewer = lambda *a, **k: "VERDICT: pass"
        r_i, _ = _aggregate_close_security(dict(agg_nr), Path("."), None, isha, {}, gen_reviewer, True,
                                           security_reviewer_proposer=None, strict_judge_qualified=False,
                                           wid=None, child_root=None)
        assert r_i.get("overall") == "needs_review"
        assert r_i.get("closed_by") is None

    def test_human_approval_on_integration_sha_closes(self):
        import approvals as _appr_t
        isha = "a" * 40
        agg_nr = {"overall": "needs_review", "needs_review": ["rate_limiting"], "results": []}
        gen_reviewer = lambda *a, **k: "VERDICT: pass"
        with tempfile.TemporaryDirectory() as hd:
            _appr_t.write_record(hd, "seq-agg", approval="rate_limiting", approved_by="human@owner",
                                 scope="security rate_limiting", reason="человек одобрил integration-SHA",
                                 created_at="2026-07-29", binds_to=isha, expires_at="2026-12-31",
                                 risk="high", source="human")
            r_ii, _ = _aggregate_close_security(dict(agg_nr), Path(hd), None, isha, {}, gen_reviewer, True,
                                                security_reviewer_proposer=None, strict_judge_qualified=False,
                                                wid="seq-agg", child_root=hd)
            assert r_ii.get("overall") == "clear"
            assert r_ii.get("closed_by") == "human-approval-integration-sha"

    def test_approval_on_different_sha_does_not_close(self):
        import approvals as _appr_t
        isha = "a" * 40
        agg_nr = {"overall": "needs_review", "needs_review": ["rate_limiting"], "results": []}
        gen_reviewer = lambda *a, **k: "VERDICT: pass"
        with tempfile.TemporaryDirectory() as hd:
            _appr_t.write_record(hd, "seq-agg", approval="rate_limiting", approved_by="human@owner",
                                 scope="security rate_limiting", reason="человек одобрил integration-SHA",
                                 created_at="2026-07-29", binds_to=isha, expires_at="2026-12-31",
                                 risk="high", source="human")
            r_iii, _ = _aggregate_close_security(dict(agg_nr), Path(hd), None, "b" * 40, {}, gen_reviewer, True,
                                                 security_reviewer_proposer=None, strict_judge_qualified=False,
                                                 wid="seq-agg", child_root=hd)
            assert r_iii.get("overall") == "needs_review"


# ─── Package block stops sequence ──────────────────────────────────────────────

@pytest.mark.unit
class TestPackageBlockStopsSequence:
    def test_secret_boundary_blocks_package(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            wp = atomic_planner.decompose(three_area_sig, wid="seqb", child_root=root)
            pkgs = wp["work_packages"]

            def sig_for(pkg):
                return {"secret_boundary": True} if pkg["id"] == pkgs[1]["id"] else {}

            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                seq2 = execute_sequence("рефактор с блоком", three_area_sig, root, pkgs, _prop_for,
                                        feature="seqb", base=cur, signals_for=sig_for,
                                        author=True, author_proposer=_author)
            ids_seen = [p["id"] for p in seq2["packages"]]
            assert seq2["stopped_at"] == pkgs[1]["id"]
            assert pkgs[0]["id"] in seq2["completed"]
            assert pkgs[2]["id"] not in ids_seen
            assert seq2["executed_all"] is False
