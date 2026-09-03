"""Гранулярные тесты run_handoff (мигрировано из test_run_handoff_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import subprocess
import tempfile

import pytest

from ai_ops_kit.engine.run_handoff import (
    Path,
    _git,
    build_handoff,
    resume_preflight,
    yaml,
)


@pytest.fixture
def ready_report():
    return {
        "workitem_id": "feat-x", "ready_for_pr": True,
        "commit": {"sha": "a" * 40, "branch": "ai-ops/feat-x", "evidence_on_exact_sha": True},
        "loop": {"applied_writes": 2, "stopped": "done"},
        "gates": {"evaluated": ["requirements", "code_review"], "unmet": []},
        "not_yet": [], "checks": {},
    }


@pytest.fixture
def blocked_report():
    return {
        "workitem_id": "feat-y", "ready_for_pr": False,
        "commit": {"sha": "b" * 40, "branch": "ai-ops/feat-y", "evidence_on_exact_sha": True},
        "loop": {"applied_writes": 1, "stopped": "done"},
        "gates": {"evaluated": ["requirements", "security"], "unmet": ["security"]},
        "security_scan": {"secrets": [{"path": "a"}], "new_dependencies": [], "injection_flags": []},
        "not_yet": ["draft PR"], "checks": {},
    }


@pytest.mark.unit
class TestBuildHandoffReady:
    def test_kind(self, ready_report):
        assert build_handoff(ready_report)["kind"] == "RunHandoff"

    def test_resume_from_revision(self, ready_report):
        assert build_handoff(ready_report)["resume_from_revision"] == "a" * 40

    def test_next_action_pr(self, ready_report):
        assert "PR" in build_handoff(ready_report)["next_action"]

    def test_verification_passed(self, ready_report):
        assert set(build_handoff(ready_report)["verification"]["passed"]) == {"requirements", "code_review"}


@pytest.mark.unit
class TestBuildHandoffBlocked:
    def test_next_action_gates(self, blocked_report):
        assert "security" in build_handoff(blocked_report)["next_action"]

    def test_known_risks_secrets(self, blocked_report):
        assert any("секрет" in r for r in build_handoff(blocked_report)["known_risks"])

    def test_verification_failed(self, blocked_report):
        assert "security" in build_handoff(blocked_report)["verification"]["failed"]


@pytest.mark.unit
class TestBaseBinding:
    def test_base_sha_preserved(self):
        h = build_handoff({
            "workitem_id": "bb", "ready_for_pr": True,
            "commit": {"sha": "c" * 40, "branch": "ai-ops/bb", "evidence_on_exact_sha": True},
            "base_binding": {"kind": "BaseBinding", "base_ref": "main",
                             "base_sha": "d" * 40, "mode": "auto", "source": "upstream"},
            "loop": {"applied_writes": 1, "stopped": "done"}, "gates": {}, "checks": {},
        })
        assert h.get("base_binding", {}).get("base_sha") == "d" * 40


@pytest.mark.slow
@pytest.mark.unit
class TestResumePreflight:
    def _setup_repo(self):
        td = tempfile.mkdtemp()
        root = Path(td)
        subprocess.run(["git", "-C", td, "init", "-q"])
        subprocess.run(["git", "-C", td, "config", "user.email", "t@t"])
        subprocess.run(["git", "-C", td, "config", "user.name", "t"])
        (root / "f").write_text("x", encoding="utf-8")
        subprocess.run(["git", "-C", td, "add", "-A"])
        subprocess.run(["git", "-C", td, "commit", "-q", "-m", "i"])
        return td, root

    def test_no_handoff_cannot_resume(self):
        td, root = self._setup_repo()
        pf = resume_preflight(root, "nope")
        assert pf["can_resume"] is False

    def test_handoff_exists_can_resume(self):
        td, root = self._setup_repo()
        rc, head, _ = _git(root, "rev-parse", "HEAD")
        fdir = root / "features" / "feat-z"
        fdir.mkdir(parents=True)
        (fdir / "run-handoff.yaml").write_text(yaml.safe_dump(
            {"kind": "RunHandoff", "workitem_id": "feat-z", "resume_from_revision": head,
             "next_action": "продолжить", "open_questions": []}), encoding="utf-8")
        pf = resume_preflight(root, "feat-z", base="master")
        assert pf["can_resume"] is True

    def test_no_branch_revalidation(self):
        td, root = self._setup_repo()
        rc, head, _ = _git(root, "rev-parse", "HEAD")
        fdir = root / "features" / "feat-z"
        fdir.mkdir(parents=True)
        (fdir / "run-handoff.yaml").write_text(yaml.safe_dump(
            {"kind": "RunHandoff", "workitem_id": "feat-z", "resume_from_revision": head,
             "next_action": "продолжить", "open_questions": []}), encoding="utf-8")
        pf = resume_preflight(root, "feat-z", base="master")
        assert pf["revalidation_needed"] is True

    def test_next_action_carried(self):
        td, root = self._setup_repo()
        rc, head, _ = _git(root, "rev-parse", "HEAD")
        fdir = root / "features" / "feat-z"
        fdir.mkdir(parents=True)
        (fdir / "run-handoff.yaml").write_text(yaml.safe_dump(
            {"kind": "RunHandoff", "workitem_id": "feat-z", "resume_from_revision": head,
             "next_action": "продолжить", "open_questions": []}), encoding="utf-8")
        pf = resume_preflight(root, "feat-z", base="master")
        assert pf["next_action"] == "продолжить"

    def test_base_advanced_revalidation(self):
        td, root = self._setup_repo()
        rc, head, _ = _git(root, "rev-parse", "HEAD")
        fdir = root / "features" / "feat-z"
        fdir.mkdir(parents=True)
        (fdir / "run-handoff.yaml").write_text(yaml.safe_dump(
            {"kind": "RunHandoff", "workitem_id": "feat-z", "resume_from_revision": head,
             "next_action": "продолжить", "open_questions": []}), encoding="utf-8")
        (root / "g").write_text("y", encoding="utf-8")
        subprocess.run(["git", "-C", td, "add", "-A"])
        subprocess.run(["git", "-C", td, "commit", "-q", "-m", "advance"])
        cur = _git(root, "rev-parse", "--abbrev-ref", "HEAD")[1]
        pf = resume_preflight(root, "feat-z", base=cur)
        assert pf["revalidation_needed"] is True
        assert any("вперёд" in r for r in pf["reasons"])

    def test_unresolvable_base_revalidation(self):
        td, root = self._setup_repo()
        rc, head, _ = _git(root, "rev-parse", "HEAD")
        fdir = root / "features" / "feat-z"
        fdir.mkdir(parents=True)
        (fdir / "run-handoff.yaml").write_text(yaml.safe_dump(
            {"kind": "RunHandoff", "workitem_id": "feat-z", "resume_from_revision": head,
             "next_action": "продолжить", "open_questions": []}), encoding="utf-8")
        pf = resume_preflight(root, "feat-z", base="no-such-branch-xyz")
        assert pf["revalidation_needed"] is True
        assert any("не удалось разрешить" in r for r in pf["reasons"])

    def test_fast_forward_base_not_rewritten(self):
        td, root = self._setup_repo()
        rc, head, _ = _git(root, "rev-parse", "HEAD")
        fdir = root / "features" / "feat-z"
        fdir.mkdir(parents=True)
        (fdir / "run-handoff.yaml").write_text(yaml.safe_dump(
            {"kind": "RunHandoff", "workitem_id": "feat-z", "resume_from_revision": head,
             "next_action": "продолжить", "open_questions": []}), encoding="utf-8")
        (root / "g").write_text("y", encoding="utf-8")
        subprocess.run(["git", "-C", td, "add", "-A"])
        subprocess.run(["git", "-C", td, "commit", "-q", "-m", "advance"])
        cur = _git(root, "rev-parse", "--abbrev-ref", "HEAD")[1]
        pf = resume_preflight(root, "feat-z", base=cur)
        assert pf.get("base_rewritten") is False

    def test_base_rewritten_orphan(self):
        td, root = self._setup_repo()
        for a in (("init", "-q"), ("config", "user.email", "t@t"), ("config", "user.name", "t")):
            pass  # already set up
        (root / "f").write_text("x", encoding="utf-8")
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "base-A")
        base_A = _git(root, "rev-parse", "HEAD")[1]
        cur = _git(root, "rev-parse", "--abbrev-ref", "HEAD")[1]
        _git(root, "checkout", "-q", "-b", "ai-ops/rw")
        (root / "w").write_text("work", encoding="utf-8")
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "work")
        work_sha = _git(root, "rev-parse", "HEAD")[1]
        _git(root, "checkout", "-q", cur)
        fdir = root / "features" / "rw"
        fdir.mkdir(parents=True)
        (fdir / "run-handoff.yaml").write_text(yaml.safe_dump(
            {"kind": "RunHandoff", "workitem_id": "rw", "resume_from_revision": work_sha,
             "base_binding": {"kind": "BaseBinding", "base_ref": cur, "base_sha": base_A,
                              "mode": "auto", "source": "upstream"},
             "next_action": "продолжить", "open_questions": []}), encoding="utf-8")
        # force-push base to orphan
        _git(root, "checkout", "-q", "--orphan", "reborn")
        (root / "z").write_text("reborn", encoding="utf-8")
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "unrelated")
        reborn_sha = _git(root, "rev-parse", "HEAD")[1]
        _git(root, "branch", "-f", cur, reborn_sha)
        _git(root, "checkout", "-q", cur)
        pf = resume_preflight(root, "rw", base=cur)
        assert pf.get("base_rewritten") is True
        assert any("ПЕРЕПИСАН" in r for r in pf["reasons"])

    def test_empty_handoff_fail_closed(self):
        td, root = self._setup_repo()
        rc, head, _ = _git(root, "rev-parse", "HEAD")
        cur = _git(root, "rev-parse", "--abbrev-ref", "HEAD")[1]
        _git(root, "checkout", "-q", "-b", "ai-ops/rw2")
        (root / "w").write_text("work", encoding="utf-8")
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "work")
        _git(root, "rev-parse", "HEAD")[1]
        _git(root, "checkout", "-q", cur)
        fdir = root / "features" / "rw2"
        fdir.mkdir(parents=True)
        (fdir / "run-handoff.yaml").write_text("", encoding="utf-8")
        pf = resume_preflight(root, "rw2", base=cur)
        assert pf["can_resume"] is False
        assert any("повреждён" in r for r in pf["reasons"])

    def test_broken_yaml_handoff_fail_closed(self):
        td, root = self._setup_repo()
        cur = _git(root, "rev-parse", "--abbrev-ref", "HEAD")[1]
        _git(root, "checkout", "-q", "-b", "ai-ops/rw3")
        (root / "w").write_text("work", encoding="utf-8")
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "work")
        _git(root, "checkout", "-q", cur)
        fdir = root / "features" / "rw3"
        fdir.mkdir(parents=True)
        (fdir / "run-handoff.yaml").write_text("kind: RunHandoff\n:::not yaml:::\n  - [", encoding="utf-8")
        pf = resume_preflight(root, "rw3", base=cur)
        assert pf["can_resume"] is False
