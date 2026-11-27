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


@pytest.mark.parametrize("value", [None, [], "secret", {"code": "secret"}])
def test_invalid_snapshot_diagnostic_is_not_projected(tmp_path, monkeypatch, value):
    monkeypatch.setattr(rp, "input_digests", lambda _: {})
    result = rp.build(tmp_path, {"complete": False, "diagnostic": value})
    assert "unavailable_diagnostic" not in result and not result["release_ready"]


def test_snapshot_diagnostic_projection_has_closed_keys_and_value_allowlists(tmp_path, monkeypatch):
    monkeypatch.setattr(rp, "input_digests", lambda _: {})
    diagnostic = {"code": "ci_changed", "pr": 10, "workflow": "docs.yml", "run_id": 55,
                  "attempt": 2, "field": "ci_signature", "payload": "SECRET", "message": "SECRET"}
    result = rp.build(tmp_path, {"complete": False, "diagnostic": diagnostic})
    assert result["unavailable_diagnostic"] == {k: v for k, v in diagnostic.items() if k not in ("payload", "message")}
    for key, values in {"pr": [True, -1, "SECRET", 2**100], "run_id": [False, 0, "SECRET"],
                        "attempt": [True, 0, "SECRET"], "workflow": ["SECRET.yml", "../docs.yml", []],
                        "field": ["SECRET", "title", {}]}.items():
        for value in values:
            unsafe = {**diagnostic, key: value}
            report = rp.build(tmp_path, {"complete": False, "diagnostic": unsafe})
            assert key not in report["unavailable_diagnostic"]
            assert not report["release_ready"] and report["publication_authorized"] is None


def test_diagnostic_only_change_does_not_change_release_semantic_fingerprint(tmp_path, monkeypatch):
    monkeypatch.setattr(rp, "input_digests", lambda _: {})
    before = rp.build(tmp_path, {"complete": False})
    after = rp.build(tmp_path, {"complete": False, "diagnostic": {"code": "ci_changed"}})
    assert after["semantic_fingerprint"] == before["semantic_fingerprint"]


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


def test_verified_prior_preserves_only_lost_ci_association(release_case):
    root, snap = release_case
    prior = rp.build(root, snap)
    for run in snap["ci"]["10"]:
        run["pull_requests"] = []
    before, old = deepcopy(snap), deepcopy(prior)
    assert not rp.build(root, snap)["implementation_evidence_complete"]
    result = rp.build(root, snap, prior=prior)
    assert result["implementation_evidence_complete"]
    assert result["implementations"][0]["ci_evidence"] == prior["implementations"][0]["ci_evidence"]
    assert not result["release_ready"] and result["publication_authorized"] is None
    assert snap == before and prior == old


@pytest.mark.parametrize("failure", ["base", "head", "merge", "pr", "duplicate", "unobserved",
                                    "checks", "run", "attempt", "policy", "repository",
                                    "conflict", "failed", "partial", "rerun", "missing_workflow"])
def test_historical_link_never_overrides_missing_or_conflicting_proof(release_case, failure):
    root, snap = release_case
    prior = rp.build(root, snap)
    for run in snap["ci"]["10"]:
        run["pull_requests"] = []
    row, run = prior["implementations"][0], snap["ci"]["10"][0]
    workflow = next(iter(row["ci_evidence"]))
    if failure in ("base", "head"):
        row[failure] = "f" * 40
    elif failure == "merge":
        row["merge_sha"] = "f" * 40
    elif failure == "pr":
        row["pr"] = 99
    elif failure == "duplicate":
        prior["implementations"].append(deepcopy(row))
    elif failure == "unobserved":
        row["ci_observed"] = False
    elif failure in ("checks", "run", "attempt"):
        row["ci_evidence"][workflow][failure] = [] if failure == "checks" else 999
    elif failure == "policy":
        prior["input_digests"][".github/workflows/pr-smoke.yml"] = "f" * 64
    elif failure == "repository":
        prior["repository"] = "foreign/repo"
    elif failure == "conflict":
        run["pull_requests"] = [{"number": 99}]
    elif failure == "failed":
        run["jobs"][0]["conclusion"] = "failure"
    elif failure == "partial":
        run["jobs"] = []
    elif failure == "rerun":
        run["run_attempt"] += 1
        run["queried_attempt"] += 1
    else:
        snap["ci"]["10"].pop(0)
    result = rp.build(root, snap, prior=prior)
    assert not result["implementation_evidence_complete"] and not result["release_ready"]


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
    # Фактический профиль stock release run 41065592704: две PR-only jobs неприменимы.
    for job in jobs:
        if job["name"] in {"full-gate / security-scan", "full-gate / delivered-footprint"}:
            job["conclusion"] = "skipped"
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


def test_release_pauses_to_publish_ready_before_tag():
    """#1446: пульт пересобирается после всех гейтов и до тега, и это не становится гейтом."""
    job = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())["jobs"]["release"]
    steps = job["steps"]
    window = next(i for i, s in enumerate(steps) if s.get("id") == "ready_window")
    gates = [i for i, s in enumerate(steps) if "pytest" in s.get("run", "")]
    tag = next(i for i, s in enumerate(steps) if "gh release create" in s.get("run", ""))
    step = steps[window]
    assert max(gates) < window < tag
    assert "pytest" not in step["run"] and step["continue-on-error"] is True
    assert "gh workflow run status-dashboard.yml" in step["run"] and step["timeout-minutes"] <= 20
    assert job["permissions"] == {"contents": "write", "actions": "write"}


@pytest.mark.parametrize("event", ["push", "workflow_dispatch"])
def test_release_applicability_is_read_from_policy_without_writing_inputs(release_case, event):
    root, snap = release_case
    (root / "VERSION").write_text("4.12.0\n")
    snap["source"]["version"] = "4.12.0"
    (root / "newsfragments/new.feat.md").unlink()
    run = release_run(root, publishing=False)
    run["event"] = event
    snap["release_ci"] = [run]
    snap["input_digests"] = rp.input_digests(root)
    before = deepcopy(snap)
    files = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert rp.build(root, snap)["final_release_checks_observed"]
    assert snap == before
    assert files == {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("condition", [None, "always()", "github.event_name == 'push'"])
def test_unproven_release_skip_cannot_be_accepted(release_case, condition):
    root, snap = release_case
    (root / "VERSION").write_text("4.12.0\n")
    snap["source"]["version"] = "4.12.0"
    (root / "newsfragments/new.feat.md").unlink()
    snap["release_ci"] = [release_run(root)]
    path = root / ".github/workflows/package-quality.yml"
    workflow = yaml.safe_load(path.read_text())
    if condition is None:
        workflow["jobs"]["security-scan"].pop("if")
    else:
        workflow["jobs"]["security-scan"]["if"] = condition
    path.write_text(yaml.safe_dump(workflow))
    # Обновлённый snapshot не делает неизвестное условие или неожиданный SKIP успешным.
    snap["input_digests"] = rp.input_digests(root)
    result = rp.build(root, snap)
    assert not result["release_ready"]
    assert not result.get("final_release_checks_observed", False)
    if condition is not None:
        assert "source_unknown_or_invalid" in result["blockers"]


def test_changed_release_applicability_invalidates_old_snapshot(release_case):
    root, snap = release_case
    path = root / ".github/workflows/package-quality.yml"
    path.write_text(path.read_text() + "\n# changed applicability input\n")
    assert "source_unknown_or_invalid" in rp.build(root, snap)["blockers"]


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


def _selection_case(root, snap, **overrides):
    plan = {"goals": [{"id": "paused", "status": "paused"}, {"id": "first"}, {"id": "other"}],
            "current_milestone": {"id": "m1", "name": "Первая веха", "status": "todo",
                                  "linked_goals": ["paused", "first"]},
            "work": [{"id": "high", "goal": "first", "issue": 9, "status": "in_progress"},
                     {"id": "outside", "goal": "other", "issue": 12},
                     {"id": "no-link", "goal": "absent", "status": "done"},
                     {"id": "later", "goal": "paused", "issue": 11}]}
    plan.update(overrides)
    (root / "planning/plan.yaml").write_text(yaml.safe_dump(plan))
    snap["input_digests"] = rp.input_digests(root)
    return rp.build(root, snap)


def test_ranked_milestone_selection_uses_real_closing_links_and_plan_pr(release_case):
    root, snap = release_case
    (root / "history/plan-history.yaml").write_text("work: [{id: archived, goal: paused, pr: 10}]")
    report = _selection_case(root, snap)
    selection = report["selection"]
    high, archived, later, outside, unknown = selection["work"]
    assert (high["work_id"], high["goal_rank"], high["scope"], high["merged_prs"]) == ("high", 1, "in_milestone", [10])
    assert archived["work_id"] == "archived" and archived["merged_prs"] == [10]
    assert later["goal_rank"] == 3 and later["reason"] == "completed_only"
    assert outside["scope"] == "outside_milestone" and outside["goal_rank"] == 2
    assert unknown["scope"] == "unknown" and unknown["goal_rank"] is None and not unknown["merged_prs"]
    assert selection["prioritized_milestone_prs"] == [10] and not selection["unmapped_prs"]
    assert report["issues"][0]["acceptance"] == "unknown" and not report["release_ready"]


def test_cycle_deferral_keeps_linked_code_and_only_changes_named_version(release_case):
    root, snap = release_case
    intent = {"id": "cut", "milestone": "m1", "candidate_limit": 0,
              "deferred": {"cycle_version": "4.12.0", "issues": [9, 12, 90]}}
    report = _selection_case(root, snap, release_intent=intent)
    selection = report["selection"]
    row = selection["work"][0]
    assert row["reason"] == "deferred_for_version" and row["merged_prs"] == [10]
    assert selection["unmapped_deferred_issues"] == [90] and selection["prioritized_milestone_prs"] == []
    assert report["included_commits"] == snap["commits"] and report["issues"][0]["acceptance"] == "unknown"
    intent["deferred"]["cycle_version"] = "4.13.0"
    report = _selection_case(root, snap, release_intent=intent)
    assert report["selection"]["prioritized_milestone_prs"] == [10] and report["deferred_issues"] == []


@pytest.mark.parametrize("override", [
    {"current_milestone": None}, {"current_milestone": {"id": "missing-fields"}},
    {"goals": [{"id": "first", "status": "typo"}]},
    {"release_intent": {"id": "different", "milestone": "Другая веха", "candidate_limit": 0}},
])
def test_selection_marks_unproven_milestone_unknown_without_removing_merges(release_case, override):
    root, snap = release_case
    snap["pulls"][0]["closing_issues"] = [42]
    snap["issues"].append({"number": 42, "state": "closed"})
    report = _selection_case(root, snap, **override)
    selection = report["selection"]
    assert selection["milestone"] is None and selection["prioritized_milestone_prs"] is None
    assert all(row["scope"] == "unknown" and row["reason"] == "completed_only" for row in selection["work"])
    if "goals" in override:
        assert all(row["goal_rank"] is None for row in selection["work"])
    assert selection["unmapped_prs"] == [{"pr": 10, "closing_issues": [42], "reason": "merged_change",
                                         "scope": "unknown", "goal_rank": None}]
    assert report["included_commits"] == snap["commits"]


def test_explanation_binds_payload_and_preserves_input_and_legacy_transition(release_case):
    from ai_ops_kit.devtools import release_plan_state as state
    root, snap = release_case
    report = _selection_case(root, snap)
    before = deepcopy(snap)
    assert rp.build(root, snap) == report and snap == before and rp.input_digests(root) == snap["input_digests"]
    legacy = dict(report)
    del legacy["selection"]
    assert rp.semantic_fingerprint(legacy) == report["semantic_fingerprint"]
    assert state.payload_digest(legacy) != state.payload_digest(report)
    assert not state.project(report, legacy)["transition"]["changed"]


def test_idle_and_invalid_release_inputs_have_no_selection(release_case):
    root, snap = release_case
    snap["source"]["sha"] = BASE
    snap["commits"] = []
    (root / "newsfragments/new.feat.md").unlink()
    report = _selection_case(root, snap)
    assert report["cycle_state"] == "idle" and "selection" not in report
    snap["complete"] = False
    report = rp.build(root, snap)
    assert report["cycle_state"] == "unknown" and "selection" not in report


def test_milestone_pr_order_follows_goals_without_reordering_included_commits(release_case):
    root, snap = release_case
    earlier = "4" * 40
    snap["commits"][0]["parents"][0] = earlier
    snap["commits"].append({"sha": earlier, "parents": [BASE]})
    snap["pulls"].append(dict(snap["pulls"][0], number=3, merge_sha=earlier, closing_issues=[11]))
    snap["issues"].append({"number": 11, "state": "closed"})
    first = _selection_case(root, snap)
    assert first["selection"]["prioritized_milestone_prs"] == [10, 3]
    reordered = _selection_case(root, snap, goals=[{"id": "paused"}, {"id": "first"}, {"id": "other"}])
    assert reordered["selection"]["prioritized_milestone_prs"] == [3, 10]
    assert first["included_commits"] == reordered["included_commits"]
    assert first["semantic_fingerprint"] == reordered["semantic_fingerprint"]
    assert first["input_fingerprint"] != reordered["input_fingerprint"]


def test_historical_issue_link_is_not_an_inclusion_in_this_cycle(release_case):
    root, snap = release_case
    historical = dict(snap["pulls"][0], number=20, merge_sha="5" * 40, published_ancestor=BASE)
    snap["dependency_pulls"] = [historical]
    snap["pulls"][0]["closing_issues"] = []
    report = _selection_case(root, snap)
    assert report["issues"][0]["implementation_observed"] and report["issues"][0]["linked_prs"] == [20]
    high = report["selection"]["work"][0]
    assert high["reason"] == "completed_only" and high["merged_prs"] == []
    assert report["selection"]["prioritized_milestone_prs"] == []


@pytest.mark.parametrize("work_pr", ["https://github.com/owner/kit/pull/5",
                                     "https://github.com/foreign/kit/pull/10", "10", "#10",
                                     False, True, 10.0, ["10"], {"number": 10}])
def test_archive_evidence_is_not_a_pr_identity_or_a_release_blocker(release_case, work_pr):
    root, snap = release_case
    baseline = _selection_case(root, snap)
    archived = {"id": "legacy", "status": "done", "result": "Проверено", "pr": work_pr,
                "evidence": "отчёт", "closed_at": "2026-11-27", "issue": {"number": 9}}
    assert rp.plan_validate.validate_history([archived])["errors"] == []
    (root / "history/plan-history.yaml").write_text(yaml.safe_dump({"work": [archived]}))
    report = _selection_case(root, snap)
    for key in ("included_commits", "composition_available", "plan_ready", "release_ready", "semantic_fingerprint",
                "implementations", "blockers", "selection"):
        assert report[key] == baseline[key]


@pytest.mark.parametrize("issue, work_pr, goal", [(True, True, {"id": "first"}), (9.0, 10.0, False),
                                                  ("9", ["10"], ["first"]), ([9], {"number": 10}, None)])
def test_optional_active_work_fields_do_not_bind_unknown_links(release_case, issue, work_pr, goal):
    root, snap = release_case
    snap["pulls"][0].update(number=1, closing_issues=[1, 9])
    snap["issues"].append({"number": 1, "state": "closed"})
    report = _selection_case(root, snap, work=[{"id": "active", "pr": work_pr, "issue": issue, "goal": goal}])
    assert report["composition_available"] and report["included_commits"] == snap["commits"]
    row, = report["selection"]["work"]
    assert row["scope"] == "unknown" and row["issue"] is None and row["goal_rank"] is None
    assert row["merged_prs"] == [] and report["selection"]["unmapped_prs"][0]["pr"] == 1


def test_exact_url_and_independent_closing_issue_each_bind_with_unknown_goal(release_case):
    root, snap = release_case
    archived = {"id": "linked", "status": "done", "pr": "https://github.com/owner/kit/pull/10",
                "result": "Проверено", "issue": []}
    (root / "history/plan-history.yaml").write_text(yaml.safe_dump({"work": [archived]}))
    milestone = {"id": "m", "name": "Веха", "status": "todo", "linked_goals": ["only"]}
    work = [{"id": "active", "status": "in_progress", "issue": 9, "pr": {"number": 12}},
            {"id": "unknown-goal", "goal": "external", "issue": 9}]
    report = _selection_case(root, snap, goals=[{"id": "only"}], current_milestone=milestone, work=work)
    rows = {w["work_id"]: w for w in report["selection"]["work"]}
    assert all(w["merged_prs"] == [10] for w in rows.values()) and len(rows) == 3
    assert rows["active"]["goal"] == "only" and rows["active"]["scope"] == "in_milestone"
    assert rows["linked"]["goal"] is None and rows["linked"]["scope"] == "unknown"
    assert rows["unknown-goal"]["scope"] == "unknown" and rows["unknown-goal"]["goal_rank"] is None


@pytest.mark.parametrize("archive", [[], [{"id": "other"}], {"version": 1}, None])
def test_incomplete_work_inventory_preserves_composition_without_selection(release_case, archive):
    root, snap = release_case
    before = _selection_case(root, snap)
    (root / "history/plan-history.yaml").write_text(yaml.safe_dump(archive))
    report = _selection_case(root, snap)
    for key in ("included_commits", "composition_available", "plan_ready", "release_ready", "semantic_fingerprint",
                "implementations", "blockers"):
        assert report[key] == before[key]
    assert "selection" in before and "selection" not in report


@pytest.mark.parametrize("failure", ["duplicate_work", "invalid_pr_number", "invalid_closing_issue"])
def test_source_identity_failure_still_blocks_release_with_legacy_work(release_case, failure):
    root, snap = release_case
    archived = {"id": "high" if failure == "duplicate_work" else "legacy", "pr": {"number": 10}}
    (root / "history/plan-history.yaml").write_text(yaml.safe_dump({"work": [archived]}))
    if failure == "invalid_pr_number":
        snap["pulls"][0]["number"] = True
    if failure == "invalid_closing_issue":
        snap["pulls"][0]["closing_issues"] = ["9"]
    report = _selection_case(root, snap)
    assert not report["composition_available"] and "source_unknown_or_invalid" in report["blockers"]
    assert "selection" not in report and not report["release_ready"]
