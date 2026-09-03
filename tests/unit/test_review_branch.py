"""Гранулярные тесты review_branch (мигрировано из test_review_branch_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import contextlib
import io
import tempfile

import pytest

from ai_ops_kit.delivery.review_branch import (
    Path,
    _git,
    review,
)
from ai_ops_kit.engine import ai_ops_run


@pytest.fixture
def review_repo():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        for a in (("init", "-q"), ("config", "user.email", "t@t"), ("config", "user.name", "t"),
                  ("add", "-A"), ("commit", "-q", "-m", "i")):
            _git(root, *a)
        cur = _git(root, "rev-parse", "--abbrev-ref", "HEAD")[1]

        it = iter([{"op": "write", "path": "src/rv.py", "content": "x=1\n"}, {"done": True}])
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            ai_ops_run.run("рефактор", {"task_type": "ENGINEERING", "size": "small", "risk": "low",
                                        "affected_areas": ["core"], "decomposition_confirmed": True},
                           root, engine="pipeline", proposer=lambda c: next(it), execute=True,
                           feature="rv", install_deps=False, author=True)
        yield root, cur


@pytest.mark.slow
@pytest.mark.unit
class TestReview:
    def test_no_branch_verdict(self, review_repo):
        root, cur = review_repo
        r = review(root, "never", reviewer_proposer=lambda p: '{"kind":"reviewer-result","status":"pass"}', base=cur)
        assert r["verdict"] == "no-branch"

    def test_reviewer_pass(self, review_repo):
        root, cur = review_repo

        def passrev(p):
            if "--- src/rv.py ---" in p:
                return '{"kind":"reviewer-result","status":"pass","checks":[{"id":"ok","status":"pass"}]}'
            return '{"op":"read","path":"src/rv.py"}'

        r = review(root, "rv", reviewer_proposer=passrev, base=cur)
        assert r["verdict"] == "pass"
        assert any(rv["gate"] == "code_review" and rv["status"] == "pass" for rv in r["reviews"])

    def test_review_is_read_only(self, review_repo):
        root, cur = review_repo
        _, sha_before, _ = _git(root / ".ai" / "worktrees" / "rv", "rev-parse", "HEAD")

        def passrev(p):
            if "--- src/rv.py ---" in p:
                return '{"kind":"reviewer-result","status":"pass","checks":[{"id":"ok","status":"pass"}]}'
            return '{"op":"read","path":"src/rv.py"}'

        review(root, "rv", reviewer_proposer=passrev, base=cur)
        _, sha_after, _ = _git(root / ".ai" / "worktrees" / "rv", "rev-parse", "HEAD")
        assert sha_before == sha_after

    def test_reviewer_fail(self, review_repo):
        root, cur = review_repo
        failrev = lambda p: '{"kind":"reviewer-result","status":"fail","checks":[{"id":"x","status":"fail"}],"blockers":["плохо"]}'
        r = review(root, "rv", reviewer_proposer=failrev, base=cur)
        assert r["verdict"] == "needs-changes"

    def test_pass_readiness(self, review_repo):
        root, cur = review_repo

        def passrev(p):
            if "--- src/rv.py ---" in p:
                return '{"kind":"reviewer-result","status":"pass","checks":[{"id":"ok","status":"pass"}]}'
            return '{"op":"read","path":"src/rv.py"}'

        r = review(root, "rv", reviewer_proposer=passrev, base=cur)
        assert (r.get("readiness") or {}).get("ready_for_merge") is True

    def test_fail_readiness(self, review_repo):
        root, cur = review_repo
        failrev = lambda p: '{"kind":"reviewer-result","status":"fail","checks":[{"id":"x","status":"fail"}],"blockers":["плохо"]}'
        r = review(root, "rv", reviewer_proposer=failrev, base=cur)
        assert (r.get("readiness") or {}).get("ready_for_merge") is False

    def test_verdict_artifact_written(self, review_repo):
        root, cur = review_repo
        failrev = lambda p: '{"kind":"reviewer-result","status":"fail","checks":[{"id":"x","status":"fail"}],"blockers":["плохо"]}'
        review(root, "rv", reviewer_proposer=failrev, base=cur)
        ev = root / "features" / "rv" / "branch-review.yaml"
        assert ev.is_file()
        import yaml as _y
        rec = _y.safe_load(ev.read_text(encoding="utf-8"))
        assert rec.get("verdict") == "needs-changes"
        assert bool(rec.get("created_at"))

    def test_needs_reviewer(self, review_repo):
        root, cur = review_repo
        r = review(root, "rv", reviewer_proposer=None, base=cur)
        assert r["verdict"] == "needs-reviewer"
        assert (r.get("readiness") or {}).get("ready_for_merge") is False
