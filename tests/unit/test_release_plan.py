"""Состав, доказательства и право выпуска — отдельные измеряемые факты."""
from copy import deepcopy
import json
from pathlib import Path
import shutil

import pytest
import yaml

from ai_ops_kit.devtools import release_plan as rp

ROOT = Path(__file__).resolve().parents[2]
HEAD, BASE, PRHEAD = "1" * 40, "2" * 40, "3" * 40


@pytest.fixture
def release_case(tmp_path):
    for name in rp._INPUTS:
        dest = tmp_path / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, dest)
    (tmp_path / "VERSION").write_text("4.11.4\n")
    (tmp_path / "planning/plan.yaml").write_text(yaml.safe_dump({"work": []}))
    (tmp_path / "history/plan-history.yaml").write_text("work: []\n")
    (tmp_path / "newsfragments").mkdir()
    (tmp_path / "newsfragments/new.feat.md").write_text("Новая возможность.\n")
    policy = json.loads((tmp_path / "quality/premerge-checks.json").read_text())
    runs = []
    for i, (workflow, names) in enumerate(policy.items(), start=1):
        runs.append({"id": i, "run_attempt": 1, "queried_attempt": 1,
                     "path": ".github/workflows/" + workflow, "head_sha": PRHEAD,
                     "event": "pull_request", "status": "completed", "conclusion": "success",
                     "pull_requests": [{"number": 10, "head": {"sha": PRHEAD}, "base": {"sha": BASE}}],
                     "total_jobs": len(names), "jobs": [{"name": n, "status": "completed", "conclusion": "success"} for n in names]})
    snap = {"repository": "owner/kit", "source": {"sha": HEAD, "branch": "main", "version": "4.11.4"},
            "published": {"sha": BASE, "version": "4.11.4", "tag": "v4.11.4", "id": 50},
            "commits": [{"sha": HEAD, "parents": [BASE, PRHEAD]}],
            "pulls": [{"number": 10, "merged": True, "state": "closed", "base_ref": "main",
                       "head_sha": PRHEAD, "base_sha": BASE, "merge_sha": HEAD,
                       "changed_files": 1, "closing_issues": [9]}],
            "ci": {"10": runs}, "issues": [{"number": 9, "state": "closed"}],
            "complete": True, "unchanged": True, "input_digests": rp.input_digests(tmp_path)}
    return tmp_path, snap


def test_machine_plan_uses_existing_semver_and_preserves_authority_boundary(release_case):
    root, snap = release_case
    before = deepcopy(snap)
    result = rp.build(root, snap)
    assert result["target_version"] == "4.12.0"
    assert result["composition_available"] and result["plan_ready"]
    assert result["implementation_evidence_complete"]
    assert result["issues"][0]["ci_chain_observed"]
    assert result["issues"][0]["acceptance"] == "unknown"
    assert result["release_ready"] is False and result["publication_authorized"] is None
    assert result["delivery"]["observed"] == "unknown"
    assert snap == before


@pytest.mark.parametrize("failure", ["wrong_head", "wrong_base", "skipped", "cancelled", "rerun",
                                    "partial_jobs", "duplicate_job", "old_attempt", "missing_workflow", "bool_run"])
def test_missing_or_stale_ci_does_not_confirm_implementation(release_case, failure):
    root, snap = release_case
    run = snap["ci"]["10"][0]
    if failure == "wrong_head":
        run["head_sha"] = BASE
    elif failure == "wrong_base":
        run["pull_requests"][0]["base"]["sha"] = HEAD
    elif failure in ("skipped", "cancelled"):
        run["jobs"][0]["conclusion"] = failure
    elif failure == "rerun":
        snap["ci"]["10"].append({**deepcopy(run), "id": 200, "status": "in_progress", "conclusion": None})
    elif failure == "partial_jobs":
        run["jobs"] = []
    elif failure == "duplicate_job":
        run["jobs"].append(deepcopy(run["jobs"][0]))
        run["total_jobs"] += 1
    elif failure == "old_attempt":
        run["run_attempt"] = 2
    elif failure == "missing_workflow":
        snap["ci"]["10"] = []
    else:
        run["id"] = True
    report = rp.build(root, snap)
    assert not report["implementation_evidence_complete"]
    assert not report["release_ready"]


def test_closed_only_issue_does_not_count_as_implemented(release_case):
    root, snap = release_case
    snap["pulls"][0]["closing_issues"] = []
    issue = rp.build(root, snap)["issues"][0]
    assert not issue["implementation_observed"] and not issue["ci_chain_observed"]


@pytest.mark.parametrize("key", ["complete", "unchanged", "input_digests"])
def test_incomplete_snapshot_is_unknown_not_empty_success(release_case, key):
    root, snap = release_case
    snap[key] = None
    result = rp.build(root, snap)
    assert not result["composition_available"] and not result["release_ready"]
    assert "source_unknown_or_invalid" in result["blockers"]


def test_changed_policy_invalidates_previously_observed_ci(release_case):
    root, snap = release_case
    (root / "registry/release-claims.yaml").write_text("changed: true\n")
    assert "source_unknown_or_invalid" in rp.build(root, snap)["blockers"]


def test_unlinked_merged_code_stays_in_composition_as_a_blocker(release_case):
    root, snap = release_case
    snap["pulls"] = []
    result = rp.build(root, snap)
    assert result["included_commits"] == snap["commits"]
    assert result["composition_available"] and not result["plan_ready"]
    assert result["unlinked_commits"] == [HEAD]


@pytest.mark.parametrize("kind", ["missing", "cycle", "foreign", "duplicate"])
def test_ancestry_must_be_the_complete_first_parent_line(release_case, kind):
    root, snap = release_case
    if kind == "missing":
        snap["commits"] = []
    elif kind == "cycle":
        snap["commits"][0]["parents"] = [HEAD, BASE]
    elif kind == "foreign":
        snap["commits"].append({"sha": PRHEAD, "parents": [BASE]})
    else:
        snap["commits"].append(deepcopy(snap["commits"][0]))
    assert not rp.build(root, snap)["composition_available"]


def test_dependency_done_needs_matching_implementation_evidence(release_case):
    root, snap = release_case
    (root / "planning/plan.yaml").write_text(yaml.safe_dump({"work": [
        {"id": "next-kit-release-4-12-0", "depends_on": ["required"]}]}))
    (root / "history/plan-history.yaml").write_text(yaml.safe_dump({"work": [
        {"id": "required", "status": "done", "issue": 999}]}))
    snap["input_digests"] = rp.input_digests(root)
    report = rp.build(root, snap)
    assert report["dependency_gaps"] == ["required"] and not report["plan_ready"]


def test_cycle_scoped_deferral_never_removes_merged_code(release_case):
    root, snap = release_case
    plan = {"release_intent": {"id": "kit-release", "milestone": "Выпуск", "candidate_limit": 0,
                              "deferred": {"cycle_version": "4.12.0", "issues": [9]}}}
    (root / "planning/plan.yaml").write_text(yaml.safe_dump(plan))
    snap["input_digests"] = rp.input_digests(root)
    report = rp.build(root, snap)
    assert report["deferred_issues"] == [9] and len(report["included_commits"]) == 1
    plan["release_intent"]["deferred"]["cycle_version"] = "4.13.0"
    (root / "planning/plan.yaml").write_text(yaml.safe_dump(plan))
    snap["input_digests"] = rp.input_digests(root)
    assert rp.build(root, snap)["deferred_issues"] == []


def test_read_model_has_no_write_side_effects(release_case):
    root, snap = release_case
    before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert rp.build(root, snap)["composition_available"]
    assert before == {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_semantic_transition_ignores_run_ids_but_not_ready_or_policy_failure(release_case):
    root, snap = release_case
    before = rp.build(root, snap)
    for run in snap["ci"]["10"]:
        run["id"] += 10
    after = rp.build(root, snap)
    assert before["semantic_fingerprint"] == after["semantic_fingerprint"]
    snap["ci"]["10"][0]["conclusion"] = "failure"
    assert before["semantic_fingerprint"] != rp.build(root, snap)["semantic_fingerprint"]


def release_run(root, *, publishing=True):
    workflow = yaml.safe_load((root / ".github/workflows/release.yml").read_text())
    policy = json.loads((root / "quality/premerge-checks.json").read_text())
    expected = [s["name"] for s in workflow["jobs"]["release"]["steps"] if "pytest" in s.get("run", "")]
    jobs = [{"name": name, "status": "completed", "conclusion": "success"} for name in
            ["check", *["full-gate / " + n for n in policy["package-quality.yml"]]]]
    jobs.append({"name": "release", "status": "in_progress" if publishing else "completed",
                 "conclusion": None if publishing else "success", "steps": [
                     {"name": n, "status": "completed", "conclusion": "success"} for n in expected]})
    return {"id": 800, "run_attempt": 1, "queried_attempt": 1, "path": ".github/workflows/release.yml",
            "head_sha": HEAD, "head_branch": "main", "event": "push", "status": "in_progress" if publishing else "completed",
            "conclusion": None if publishing else "success", "total_jobs": len(jobs), "jobs": jobs}


def test_ready_can_be_observed_after_actual_gates_before_publication(release_case):
    root, snap = release_case
    (root / "VERSION").write_text("4.12.0\n")
    snap["source"]["version"] = "4.12.0"
    (root / "newsfragments/new.feat.md").unlink()
    snap["input_digests"] = rp.input_digests(root)
    snap["release_ci"] = [release_run(root)]
    result = rp.build(root, snap)
    assert result["release_ready"] and result["final_release_checks_observed"]
    assert result["target_version"] == "4.12.0"
    assert result["publication_authorized"] is None
    assert result["published"]["version"] == "4.11.4"


@pytest.mark.parametrize("failure", ["old_sha", "cancelled", "failed", "skipped_gate", "mutation_pending", "wrong_attempt", "truncated"])
def test_final_stock_release_proofs_cannot_be_replaced_by_pr_success(release_case, failure):
    root, snap = release_case
    (root / "VERSION").write_text("4.12.0\n")
    snap["source"]["version"] = "4.12.0"
    (root / "newsfragments/new.feat.md").unlink()
    snap["input_digests"] = rp.input_digests(root)
    run = release_run(root)
    snap["release_ci"] = [run]
    if failure == "old_sha":
        run["head_sha"] = BASE
    elif failure in ("cancelled", "failed"):
        run["status"], run["conclusion"] = "completed", failure
    elif failure == "skipped_gate":
        run["jobs"][1]["conclusion"] = "skipped"
    elif failure == "mutation_pending":
        run["jobs"][-1]["steps"][0]["status"] = "in_progress"
    elif failure == "wrong_attempt":
        run["queried_attempt"] = 2
    else:
        run["jobs"].pop(0)
    assert not rp.build(root, snap)["release_ready"]


def test_historical_dependency_uses_separate_ci_and_published_ancestry_without_expanding_cut(release_case):
    root, snap = release_case
    (root / "planning/plan.yaml").write_text(yaml.safe_dump({"work": [
        {"id": "next-kit-release-4-12-0", "depends_on": ["previous-release-prerequisite"]}]}))
    (root / "history/plan-history.yaml").write_text(yaml.safe_dump({"work": [
        {"id": "previous-release-prerequisite", "status": "done", "pr": 11}]}))
    historic = {**deepcopy(snap["pulls"][0]), "number": 11, "merge_sha": BASE, "head_sha": "4" * 40,
                "base_sha": "5" * 40, "closing_issues": [], "published_ancestor": BASE}
    snap["dependency_pulls"] = [historic]
    runs = deepcopy(snap["ci"]["10"])
    for run in runs:
        run["head_sha"] = "4" * 40
        run["pull_requests"] = [{"number": 11, "head": {"sha": "4" * 40}, "base": {"sha": "5" * 40}}]
    snap["ci"]["11"] = runs
    snap["input_digests"] = rp.input_digests(root)
    report = rp.build(root, snap)
    assert report["plan_ready"] and report["dependency_gaps"] == []
    assert len(report["included_commits"]) == 1 and report["included_commits"][0]["sha"] == HEAD
    assert report["dependency_implementations"][0]["merge_sha"] == BASE
    historic["published_ancestor"] = HEAD
    assert not rp.build(root, snap)["plan_ready"]


def test_dependency_cycle_cannot_become_ready_even_if_each_row_says_done(release_case):
    root, snap = release_case
    (root / "planning/plan.yaml").write_text(yaml.safe_dump({"work": [
        {"id": "next-kit-release-4-12-0", "depends_on": ["a"]}]}))
    (root / "history/plan-history.yaml").write_text(yaml.safe_dump({"work": [
        {"id": "a", "status": "done", "pr": 10, "depends_on": ["b"]},
        {"id": "b", "status": "done", "pr": 10, "depends_on": ["a"]}]}))
    snap["input_digests"] = rp.input_digests(root)
    assert "source_unknown_or_invalid" in rp.build(root, snap)["blockers"]


def test_previous_minor_field_evidence_does_not_earn_target_stable_channel(release_case):
    root, snap = release_case
    path = root / "registry/release-claims.yaml"
    claims = yaml.safe_load(path.read_text())
    claims["channel"] = "stable"
    claims["field_evidence"] = [{"repo": "first", "version": "4.11.4", "outcome": "ok"},
                                {"repo": "second", "version": "4.11.4", "outcome": "ok"}]
    path.write_text(yaml.safe_dump(claims))
    snap["input_digests"] = rp.input_digests(root)
    result = rp.build(root, snap)
    assert not result["channel"]["earned"] and not result["channel"]["policy_valid_for_target"]
    assert "channel_evidence_missing" in result["blockers"] and not result["release_ready"]


def test_known_empty_cut_after_publication_is_idle_not_an_api_failure(release_case):
    root, snap = release_case
    (root / "newsfragments/new.feat.md").unlink()
    snap.update(commits=[], pulls=[], ci={})
    snap["published"]["sha"] = HEAD
    snap["input_digests"] = rp.input_digests(root)
    result = rp.build(root, snap)
    assert result["cycle_state"] == "idle" and result["composition_available"]
    assert result["target_version"] is None and result["plan_ready"]
    assert result["blockers"] == [] and result["release_ready"] is False
    assert result["issues"][0]["implementation_observed"] is False


def test_changed_code_without_release_notes_does_not_look_like_idle(release_case):
    root, snap = release_case
    (root / "newsfragments/new.feat.md").unlink()
    snap["input_digests"] = rp.input_digests(root)
    report = rp.build(root, snap)
    assert report["cycle_state"] != "idle"
    assert "unreleased_changes_without_fragments" in report["blockers"]
    assert not report["release_ready"]


def test_cleared_merged_ci_association_and_spoofed_run_title_stay_unknown(release_case):
    root, snap = release_case
    for run in snap['ci']['10']:
        run['pull_requests'] = []
        # GitHub drops the association after merge. An untrusted title cannot restore it.
        run['display_title'] = f'ci-src:v1 pr=10 h={PRHEAD} b={BASE} m={HEAD} w={HEAD}'
        run['source_proof'] = {'verified': True, 'tested_merge': HEAD,
                               'head': PRHEAD, 'base': BASE, 'workflow_path': run['path'],
                               'producer_sha256': 'a'*64}
    result = rp.build(root, snap)
    assert result['composition_available'] and result['plan_ready']
    assert not result['implementation_evidence_complete'] and not result['release_ready']
    assert 'implementation_ci_incomplete' in result['blockers']


def test_unknown_dependency_still_blocks_plan_with_lost_ci_associations(release_case):
    root, snap = release_case
    for run in snap['ci']['10']:
        run['pull_requests'] = []
    (root / 'planning/plan.yaml').write_text(yaml.safe_dump({'work': [
        {'id': 'next-kit-release-4-12-0', 'depends_on': ['missing-acceptance']}]}))
    snap['input_digests'] = rp.input_digests(root)
    result = rp.build(root, snap)
    assert result['composition_available'] and not result['plan_ready']
    assert result['dependency_gaps'] == ['missing-acceptance']
    assert not result['release_ready']


def test_defining_plan_with_lost_ci_associations_preserves_inputs(release_case):
    root, snap = release_case
    for run in snap['ci']['10']:
        run['pull_requests'] = []
    before = deepcopy(snap)
    files = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    result = rp.build(root, snap)
    assert result['plan_ready'] and not result['release_ready']
    assert snap == before
    assert files == {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
