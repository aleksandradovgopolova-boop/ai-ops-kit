"""Review применяется повторно только при неизменных diff, базе и зависимостях."""
import subprocess

import pytest

from ai_ops_kit.engine import execution_pipeline, review_branch

pytestmark = pytest.mark.unit


@pytest.fixture
def branch(tmp_path, monkeypatch):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args], text=True).strip()
    git("init", "-q", "-b", "main")
    (tmp_path / "src.py").write_text("x=1\n")
    git("add", "src.py")
    git("-c", "user.name=fixture", "-c", "user.email=f@f", "commit", "-qm", "base")
    wp = tmp_path / ".ai/worktrees/w"
    git("worktree", "add", "-b", "ai-ops/w", str(wp))
    (wp / "src.py").write_text("x=2\n")
    subprocess.run(["git", "-C", str(wp), "add", "src.py"], check=True)
    subprocess.run(["git", "-C", str(wp), "-c", "user.name=fixture", "-c", "user.email=f@f",
                    "commit", "-qm", "change"], check=True)
    calls = []
    def reviews(*args):
        calls.append(1)
        return {}, [{"gate": "code_review", "status": "pass", "valid": True}]
    monkeypatch.setattr(execution_pipeline, "_run_reviews", reviews)
    return tmp_path, wp, git, calls


def test_same_review_reuses_persisted_verdict_even_without_new_reviewer(branch):
    root, wp, git, calls = branch
    first = review_branch.review(root, "w", lambda _: None, base="main")
    second = review_branch.review(root, "w", None, base="main")
    assert first["verdict"] == second["verdict"] == "pass"
    assert len(calls) == 1 and second["reused"] and second["reuse_source"]


def test_new_base_invalidates_review_even_when_diff_is_same(branch):
    root, wp, git, calls = branch
    review_branch.review(root, "w", lambda _: None, base="main")
    git("-c", "user.name=fixture", "-c", "user.email=f@f", "commit", "--allow-empty", "-qm", "new-base")
    result = review_branch.review(root, "w", lambda _: None, base="main")
    assert len(calls) == 2 and not result["reused"]


def test_changed_dependency_invalidates_review(branch):
    root, wp, git, calls = branch
    review_branch.review(root, "w", lambda _: None, base="main")
    (wp / "requirements.lock").write_text("changed")
    result = review_branch.review(root, "w", lambda _: None, base="main")
    assert len(calls) == 2 and not result["reused"]


def test_incomplete_review_artifact_is_not_reused(branch):
    root, wp, git, calls = branch
    review_branch.review(root, "w", lambda _: None, base="main")
    path = root / "features/w/branch-review.yaml"
    path.write_text("verdict: pass\n")
    result = review_branch.review(root, "w", None, base="main")
    assert result["verdict"] == "needs-reviewer" and not result["reused"]


def test_changed_merge_base_and_diff_invalidates_same_tree_review(branch):
    root, wp, git, calls = branch
    (root / "new.py").write_text("new=1\n")
    git("add", "new.py")
    git("-c", "user.name=fixture", "-c", "user.email=f@f", "commit", "-qm", "new-main")
    first = review_branch.review(root, "w", lambda _: None, base="main")
    before = subprocess.check_output(["git", "-C", str(wp), "rev-parse", "HEAD^{tree}"])
    subprocess.run(["git", "-C", str(wp), "reset", "--soft", "main"], check=True)
    subprocess.run(["git", "-C", str(wp), "-c", "user.name=fixture", "-c", "user.email=f@f",
                    "commit", "-qm", "new-parent-same-tree"], check=True)
    after = subprocess.check_output(["git", "-C", str(wp), "rev-parse", "HEAD^{tree}"])
    assert before == after
    result = review_branch.review(root, "w", None, base="main")
    assert "new.py" in result["changed_files"] and "new.py" not in first["changed_files"]
    assert not result["reused"] and result["verdict"] == "needs-reviewer"


def test_new_chat_identity_does_not_invalidate_review(branch, monkeypatch):
    root, wp, git, calls = branch
    monkeypatch.setenv("CODEX_THREAD_ID", "chat-one")
    review_branch.review(root, "w", lambda _: None, base="main")
    monkeypatch.setenv("CODEX_THREAD_ID", "chat-two")
    result = review_branch.review(root, "w", None, base="main")
    assert result["reused"] and len(calls) == 1
