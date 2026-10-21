"""Регрессии reuse: реальные исполнения, fail-closed и содержимое входов."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ai_ops_kit.shared import lifecycle_store as vr
from ai_ops_kit.gates import evidence_collector, verification_tiers

pytestmark = pytest.mark.unit


@pytest.fixture
def context():
    return {"complete": True, "toolchain": "1" * 64,
            "dependencies": "2" * 64, "environment": "3" * 64}


@pytest.fixture
def runner(tmp_path, context):
    counter = tmp_path / ".ai/runtime/count"
    counter.parent.mkdir(parents=True)
    command = [sys.executable, "-c", "from pathlib import Path; "
               f"p=Path({str(counter)!r}); p.write_text(str(int(p.read_text())+1) if p.exists() else '1')"]
    def execute():
        rc = subprocess.call(command)
        return {"status": "PASS" if rc == 0 else "FAIL", "exit_code": rc}
    def run(**kwargs):
        return vr.run(tmp_path, "static", command, execute, lambda: context, **kwargs)
    return run, counter


def test_repeat_without_changes_reuses_real_subprocess(runner):
    run, counter = runner
    first, second = run(), run()
    assert counter.read_text() == "1"  # Побочный эффект сначала доказан.
    assert first["status"] == second["status"] == "PASS"
    assert not first["reused"] and second["reused"]
    assert Path(second["source"]).is_file() and second["reason"]


@pytest.mark.parametrize("name", ["source.py", "requirements.lock", "pytest.ini", ".env", "new_dependency.py"])
def test_changed_input_invalidates_receipt(tmp_path, runner, name):
    run, counter = runner
    run()
    (tmp_path / name).write_text("changed")
    result = run()
    assert counter.read_text() == "2"
    assert not result["reused"] and "изменились" in result["reason"]


@pytest.mark.parametrize("field", ["toolchain", "dependencies", "environment"])
def test_context_change_invalidates(tmp_path, context, runner, field):
    run, counter = runner
    run()
    context[field] = "4" * 64
    assert not run()["reused"]
    assert counter.read_text() == "2"


def test_flags_and_ci_scope_cannot_reuse_local(tmp_path, context, runner):
    run, counter = runner
    run()
    assert not run(extra={"flags": ["--strict"]})["reused"]
    assert not run(scope="ci:required")["reused"]
    assert counter.read_text() == "3"


@pytest.mark.parametrize("status", ["FAIL", "SKIP", "BLOCKED", "NOT_RUN"])
def test_non_pass_never_satisfies_next_check(tmp_path, context, status):
    calls = []
    def execute():
        calls.append(status)
        return {"status": status, "exit_code": 0}
    for _ in range(2):
        result = vr.run(tmp_path, "test", "test", execute, lambda: context)
        assert result["status"] == status and not result["reused"]
    assert len(calls) == 2


@pytest.mark.parametrize("damage", ["missing", "truncated", "exit", "inputs", "digest", "timestamp"])
def test_missing_or_unverifiable_evidence_runs_again(runner, damage):
    run, counter = runner
    result = run()
    path = Path(result["source"])
    if damage == "missing":
        path.unlink()
    elif damage == "truncated":
        path.write_text("{")
    else:
        value = json.loads(path.read_text())
        key = {"exit": "exit_code", "inputs": "inputs", "digest": "evidence_digest", "timestamp": "completed_at"}[damage]
        del value[key]
        path.write_text(json.dumps(value))
    assert not run()["reused"]
    assert counter.read_text() == "2"


def test_unknown_context_does_not_allow_skip(tmp_path):
    calls = []
    def execute():
        calls.append(1)
        return {"status": "PASS", "exit_code": 0}
    for _ in range(2):
        result = vr.run(tmp_path, "build", "build", execute, lambda: {})
        assert not result["reused"] and not result["reuse_eligible"]
    assert len(calls) == 2


def test_input_mutating_check_cannot_cache_its_success(tmp_path, context):
    def execute():
        (tmp_path / "src.py").write_text("mutation")
        return {"status": "PASS", "exit_code": 0}
    result = vr.run(tmp_path, "test", "test", execute, lambda: context)
    assert (tmp_path / "src.py").read_text() == "mutation"
    assert result["inputs"] is None and not result["reuse_eligible"]
    assert result["status"] == "BLOCKED"


def test_receipt_does_not_store_command_output_or_secrets(tmp_path, context, monkeypatch):
    monkeypatch.setenv("FIXTURE_PASSWORD", "secret-value-do-not-persist")
    result = vr.run(tmp_path, "test", "token=secret-value-do-not-persist",
                    lambda: {"status": "PASS", "exit_code": 0, "output": os.environ["FIXTURE_PASSWORD"]},
                    lambda: context)
    assert "secret-value" not in Path(result["source"]).read_text()


def test_new_python_process_reuses_persisted_result(tmp_path, context):
    script = ("import json,sys; from pathlib import Path; "
              "from ai_ops_kit.shared import lifecycle_store as r; "
              f"context={context!r}; "
              "print(json.dumps(r.run(Path(sys.argv[1]),'check','cmd',"
              "lambda: {'status':'PASS','exit_code':0},lambda:context)))")
    first = json.loads(subprocess.check_output([sys.executable, "-c", script, str(tmp_path)]))
    second = json.loads(subprocess.check_output([sys.executable, "-c", script, str(tmp_path)]))
    assert not first["reused"] and second["reused"]


class Policy:
    allowed = True
    def decide(self, action):
        return {"allow": self.allowed}


class Broker:
    calls = 0
    @staticmethod
    def _revision(root):
        return "a" * 40

    def execute(self, action, root, policy):
        self.calls += 1
        return {"allowed": policy.allowed, "ok": policy.allowed,
                "exit_code": 0 if policy.allowed else None, "reason": "observed denial"}


def test_collector_reuses_but_respects_new_policy_denial(tmp_path, context):
    profile = {"stacks": [{"language": "demo", "commands": {"test": "true"}}]}
    broker, policy = Broker(), Policy()
    for _ in range(2):
        result = evidence_collector.collect(profile, tmp_path, policy, broker=broker,
                                             verification_context=lambda: context)
        assert result["checks"]["test"]["status"] == "pass"
    assert broker.calls == 1
    policy.allowed = False
    result = evidence_collector.collect(profile, tmp_path, policy, broker=broker,
                                         verification_context=lambda: context)
    assert result["checks"]["test"]["status"] == "fail"
    assert broker.calls == 2


def test_ready_for_review_runs_previously_skipped_required_test(tmp_path, context):
    (tmp_path / "README.md").write_text("docs")
    profile = {"stacks": [{"language": "demo", "commands": {"test": "true"}}],
               "required_checks": {"ready_for_review": ["test"]}}
    broker, policy = Broker(), Policy()
    draft = evidence_collector.collect(profile, tmp_path, policy, ["README.md"], broker, "draft",
                                        verification_context=lambda: context)
    assert broker.calls == 0 and draft["verification"]["tier"] == "skip"
    for _ in range(2):
        ready = evidence_collector.collect(profile, tmp_path, policy, ["README.md"], broker,
                                            "ready_for_review", verification_context=lambda: context)
        assert ready["checks"]["test"]["status"] == "pass"
    assert broker.calls == 1


def test_missing_required_stage_command_is_blocked(tmp_path, context):
    profile = {"stacks": [], "required_checks": {"ready_for_review": ["test"]}}
    result = evidence_collector.collect(profile, tmp_path, Policy(), ["README.md"], Broker(),
                                        "ready_for_review", verification_context=lambda: context)
    assert result["checks"]["test"]["execution_status"] == "BLOCKED"
    assert result["gate_evidence"]["implementation_verification"]["status"] == "fail"
    assert "tests_passed" not in result["not_applicable"]


def test_risk_classes_combine_and_unknown_dependency_is_full(tmp_path):
    files = ["docs/guide.md", "src/Page.tsx", "src/state.ts", "api/route.py", "db/migrations/001.sql", "infra/main.tf"]
    result = verification_tiers.select_tests(files, str(tmp_path))
    assert set(result["risk_classes"]) == {"documents", "visual", "ui_state_navigation", "backend_api", "db_migrations", "infra"}
    assert result["tier"] == "full" and result["unknown_inputs"]
    assert all(check["reason"] for check in result["check_plan"])


def test_one_line_migration_is_high_risk(tmp_path):
    p = tmp_path / "migration.sql"
    p.write_text("DROP TABLE x;")
    result = verification_tiers.select_tests([p.name], str(tmp_path))
    assert result["tier"] == "full" and "db_migrations" in result["risk_classes"]


def test_executable_mode_change_invalidates_real_command(tmp_path, context):
    script = tmp_path / "probe.sh"
    script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(0o755)
    calls = []
    def execute():
        calls.append(1)
        try:
            code = subprocess.call([str(script)])
            return {"status": "PASS" if code == 0 else "FAIL", "exit_code": code}
        except PermissionError:
            return {"status": "BLOCKED", "exit_code": None}
    first = vr.run(tmp_path, "probe", "./probe.sh", execute, lambda: context)
    assert first["status"] == "PASS"
    script.chmod(0o644)
    second = vr.run(tmp_path, "probe", "./probe.sh", execute, lambda: context)
    assert second["status"] == "BLOCKED" and not second["reused"] and len(calls) == 2


def test_risk_plan_includes_transitive_importer_domain(tmp_path):
    (tmp_path / "shared.py").write_text("x=1\n")
    (tmp_path / "ui").mkdir()
    (tmp_path / "ui/state.py").write_text("from shared import x\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_state.py").write_text("from ui.state import x\ndef test_x():\n assert x == 1\n")
    profile = {"stacks": [{"language": "python", "commands": {"test": "pytest tests/ -q"}}]}
    result = verification_tiers.select_tests(["shared.py"], str(tmp_path), profile=profile)
    assert result["tier"] == "affected"
    assert "ui/state.py" in result["dependency_paths"]
    assert "ui_state_navigation" in result["risk_classes"]


def test_receipt_does_not_dirty_verified_worktree(tmp_path, context):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args], text=True)
    git("init", "-q")
    (tmp_path / "src.py").write_text("x=1\n")
    git("add", "src.py")
    git("-c", "user.name=fixture", "-c", "user.email=f@f", "commit", "-qm", "base")
    worktree = tmp_path / ".ai/worktrees/test"
    git("worktree", "add", "--detach", str(worktree))
    result = vr.run(worktree, "test", "true", lambda: {"status": "PASS", "exit_code": 0}, lambda: context)
    assert Path(result["source"]).is_file()
    assert not Path(result["source"]).is_relative_to(tmp_path)
    assert vr.state_root(worktree) == vr.state_root(tmp_path)
    assert subprocess.check_output(["git", "-C", str(worktree), "status", "--porcelain"], text=True) == ""


def test_main_merge_intent_keeps_full_scope_without_changed_paths(tmp_path, context):
    profile = {"stacks": [{"language": "demo", "commands": {"test": "true"}}]}
    broker = Broker()
    result = evidence_collector.collect(profile, tmp_path, Policy(), broker=broker,
                                         lifecycle_intent="merge_candidate",
                                         verification_context=lambda: context)
    assert result["verification"]["tier"] == "full"
    assert broker.calls == 1 and result["checks"]["test"]["status"] == "pass"


def test_main_unknown_intent_refuses_before_processes(tmp_path, context):
    broker = Broker()
    with pytest.raises(ValueError, match="unknown verification intent"):
        evidence_collector.collect({"stacks": []}, tmp_path, Policy(), broker=broker,
                                   lifecycle_intent="unknown", verification_context=lambda: context)
    assert broker.calls == 0


@pytest.mark.parametrize("intent,scope,flags", [
    ("draft", "pr-current-python", ["--pr"]),
    ("ready_for_review", "pr-current-python", ["--pr"]),
    ("merge_candidate", "pr-current-python", ["--pr"]),
    ("release_candidate", "full-current-python", []),
])
def test_main_impact_profiles_are_preserved_with_receipts(tmp_path, monkeypatch, intent, scope, flags):
    from ai_ops_kit.devtools import impact_check_cli
    observed = []
    monkeypatch.setattr(impact_check_cli, "changed_paths", lambda *a: ["infra/main.tf"])
    def record(root, check, command, execute, context, **kwargs):
        observed.append((command, kwargs))
        return {"status": "PASS"}  # dispatch-only unit test; no command is claimed executed
    monkeypatch.setattr(impact_check_cli.receipts, "run", record)
    assert impact_check_cli.main(["--root", str(tmp_path), "--intent", intent]) == 0
    assert observed[0][0] == ["bash", "scripts/check-full.sh", *flags]
    assert observed[0][1]["scope"] == scope


def test_receipts_preserve_clean_ordinary_checkout_and_reuse_after_resume(tmp_path, context):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Fixture",
                    "-c", "user.email=f@f", "commit", "--allow-empty", "-qm", "fixture"], check=True)
    calls = []
    def execute():
        calls.append(1)
        return {"status": "PASS", "exit_code": 0}
    first = vr.run(repo, "fixture", "true", execute, lambda: context)
    assert Path(first["source"]).is_file()
    assert not Path(first["source"]).is_relative_to(repo)
    assert subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain"], text=True) == ""
    second = vr.run(repo, "fixture", "true", execute, lambda: context)
    assert second["reused"] and len(calls) == 1
    (repo / "source.py").write_text("changed")
    third = vr.run(repo, "fixture", "true", execute, lambda: context)
    assert not third["reused"] and len(calls) == 2
