"""Гранулярные тесты security_review_cascade (мигрировано из test_security_review_cascade_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.security.security_review_cascade import (
    check,
    run_cascade,
)

SHA = "deadbeef"


def _det_none(_):
    return {"findings": []}


def _det_one(defect="x", fid="f1"):
    return lambda _: {"findings": [{"id": fid, "defect": defect}]}


def _ver(verdict, proof=None, cites=None):
    def _v(_code, _f):
        ce = {}
        if proof is not None:
            ce = {"proof_type": proof, "detail": "d", "cited_lines": cites or [1]}
        return {"verdict": verdict, "exploit_path": "e" if verdict == "confirmed" else None,
                "counter_evidence": ce}
    return _v


@pytest.mark.unit
class TestNoFindings:
    def test_pass(self):
        r = run_cascade("safe code", SHA, _det_none, _ver("disproved"))
        assert r["final"]["status"] == "pass"
        assert check(r) == []


@pytest.mark.unit
class TestConfirmed:
    def test_fail(self):
        r = run_cascade("bad", SHA, _det_one(), _ver("confirmed"))
        assert r["final"]["status"] == "fail"
        assert r["final"]["blockers"] == ["f1"]


@pytest.mark.unit
class TestDisproved:
    def test_with_recognized_proof_passes(self):
        code = "conn.execute('SELECT * FROM u WHERE n=?', (name,))"
        r = run_cascade(code, SHA, _det_one(), _ver("disproved", "parameterized_query", [1]))
        assert r["final"]["status"] == "pass"
        assert r["final"]["downgraded_findings"] == ["f1"]

    def test_without_proof_pending_human(self):
        r = run_cascade("bad", SHA, _det_one(), _ver("disproved", proof=None))
        assert r["final"]["status"] == "pending_human"
        assert "f1" in r["final"]["pending"]

    def test_refuted_proof_pending_human(self):
        """Verifier ВРЁТ disproved parameterized_query, но код — f-string SQL."""
        code = "conn.execute(f\"SELECT * FROM u WHERE n='{name}'\")"
        r = run_cascade(code, SHA, _det_one(defect="sqli"), _ver("disproved", "parameterized_query", [1]))
        assert r["final"]["status"] == "pending_human"
        assert "f1" in r["final"]["pending"]


@pytest.mark.unit
class TestUncertain:
    def test_pending_human(self):
        r = run_cascade("bad", SHA, _det_one(), _ver("uncertain"))
        assert r["final"]["status"] == "pending_human"


@pytest.mark.unit
class TestSchemaFail:
    def test_detector_schema_fail(self):
        r = run_cascade("bad", SHA, lambda _: None, _ver("disproved"))
        assert r["final"]["status"] == "pending_human"
        assert r["schema_valid"] is False

    def test_verifier_schema_fail(self):
        r = run_cascade("bad", SHA, _det_one(), lambda _c, _f: {"verdict": "garbage"})
        assert r["final"]["status"] == "pending_human"


@pytest.mark.unit
class TestCorroboration:
    def test_md5_on_password_refuted(self):
        code = "return hashlib.md5(password.encode()).hexdigest()"
        r = run_cascade(code, SHA, _det_one(defect="weak-crypto"),
                        _ver("disproved", "checksum_not_security", [1]))
        assert r["final"]["status"] == "pending_human"

    def test_shell_true_refuted(self):
        code = "subprocess.run('ping ' + host, shell=True)"
        r = run_cascade(code, SHA, _det_one(defect="cmdi"), _ver("disproved", "safe_argv", [1]))
        assert r["final"]["status"] == "pending_human"


@pytest.mark.unit
class TestMixedFindings:
    def test_blocker_dominates(self):
        def det_two(_):
            return {"findings": [{"id": "a", "defect": "x"}, {"id": "b", "defect": "y"}]}

        def ver_mixed(_code, f):
            if f["id"] == "a":
                return {"verdict": "disproved", "counter_evidence": {"proof_type": "not_a_secret", "cited_lines": [1]}}
            return {"verdict": "confirmed", "exploit_path": "e", "counter_evidence": {}}

        r = run_cascade("x", SHA, det_two, ver_mixed)
        assert r["final"]["status"] == "fail"
        assert r["final"]["blockers"] == ["b"]


@pytest.mark.unit
class TestCheck:
    def test_pass_with_blockers_rejected(self):
        result = {
            "kind": "SecurityCascadeResult", "tested_sha": "s",
            "primary": {}, "verification": {},
            "final": {"status": "pass", "blockers": ["z"], "pending": [], "downgraded_findings": []},
        }
        assert any("fail-closed" in x for x in check(result))
