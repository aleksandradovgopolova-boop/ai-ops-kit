"""Committed security evidence must survive checkout changes without reading local files."""
import subprocess

import pytest

from ai_ops_kit.security import security_pack, security_scan
from tests.unit._installer_helpers import _make_child_repo

pytestmark = pytest.mark.unit


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args])


def commit(root):
    git(root, "add", "-A")
    git(root, "commit", "-qm", "fixture")
    return git(root, "rev-parse", "HEAD").decode().strip()


def test_committed_dependency_survives_dirty_file_and_later_head(tmp_path):
    repo = _make_child_repo(tmp_path / "repo")
    manifest = repo / "тест\nнагрузки" / "requirements.txt"
    manifest.parent.mkdir()
    manifest.write_text("existing==1\n")
    base = commit(repo)
    manifest.write_text("existing==1\nexample==2\n")
    revision = commit(repo)
    manifest.write_text("existing==1\n")
    commit(repo)
    manifest.unlink()
    status = git(repo, "status", "--porcelain=v1", "-z")
    result = security_pack.run_pack(repo, base=base, revision=revision)
    findings = [f for domain in result["results"] for f in domain["findings"]]
    assert {f["name"] for f in findings if f["type"] == "new_dependency"} == {"example"}
    assert result["scan_scope"]["head_sha"] == revision
    assert security_scan._git_changed_files(repo, base, revision) == [manifest.relative_to(repo).as_posix()]
    assert git(repo, "status", "--porcelain=v1", "-z") == status and not manifest.exists()


def test_deleted_path_is_not_read_from_recreated_local_file(tmp_path):
    repo = _make_child_repo(tmp_path / "repo")
    manifest = repo / "requirements.txt"
    manifest.write_text("old==1\n")
    base = commit(repo)
    manifest.unlink()
    revision = commit(repo)
    manifest.write_text("local==2\n")
    result = security_pack.run_pack(repo, base=base, revision=revision)
    assert not any(f["type"] == "new_dependency" for d in result["results"] for f in d["findings"])
    assert manifest.read_text() == "local==2\n"


def test_changed_symlink_is_not_followed(tmp_path):
    repo = _make_child_repo(tmp_path / "repo")
    base = git(repo, "rev-parse", "HEAD").decode().strip()
    outside = tmp_path / "outside"
    outside.write_text("private\n")
    (repo / "pointer").symlink_to(outside)
    revision = commit(repo)
    with pytest.raises(RuntimeError, match="тип изменённого Git-объекта"):
        security_pack.run_pack(repo, base=base, revision=revision)
    assert outside.read_text() == "private\n"


def test_missing_blob_fails_instead_of_empty_clean_scan(tmp_path):
    repo = _make_child_repo(tmp_path / "repo")
    base = git(repo, "rev-parse", "HEAD").decode().strip()
    (repo / "new.txt").write_text("unique test fixture\n")
    revision = commit(repo)
    oid = git(repo, "rev-parse", revision + ":new.txt").decode().strip()
    (repo / ".git/objects" / oid[:2] / oid[2:]).unlink()
    with pytest.raises(RuntimeError, match="git cat-file"):
        security_pack.run_pack(repo, base=base, revision=revision)


def test_pipeline_checks_requested_revision_after_checkout_advances(tmp_path):
    from ai_ops_kit.engine import pipeline_readiness
    repo = _make_child_repo(tmp_path / "repo")
    base = git(repo, "rev-parse", "HEAD").decode().strip()
    manifest = repo / "requirements.txt"
    manifest.write_text("example==2\n")
    revision = commit(repo)
    manifest.unlink()
    commit(repo)
    gates, result, signals = pipeline_readiness._evaluate_security(
        repo, repo, "task", revision, True, {}, {}, review=False,
        strict_judge_qualified=False, security_reviewer_proposer=None, reviewer_proposer=None,
        budget=None, base_revision=base)
    assert result["scan_scope"]["head_sha"] == revision
    assert signals["dependency_addition"] and gates["security"]["status"] != "pass"
