"""#1407: детерминированные host guards, НЕ live prompt-injection квалификация.

Недоверенные источники доставляются настоящими read/shell-вызовами брокера. Вместо
LLM детерминированно воспроизводится предложенное действие из payload. Это мерит
реакцию host на действие с поддельными полномочиями; выбор действия моделью — NOT_RUN.
Все записи/процессы работают только в одноразовых деревьях, без сети и секретов.
"""
from __future__ import annotations

import json
from pathlib import Path
import shlex
import subprocess

import pytest
import yaml

from ai_ops_kit.devtools import gate_evals
from ai_ops_kit.engine import tool_broker as broker
from ai_ops_kit.governance import decision_boundary as boundary
from ai_ops_kit.governance import policy_engine

pytestmark = pytest.mark.contract
CASES_DIR = Path(__file__).resolve().parents[2] / "evaluations/gates/cases"
CASE_FILES = sorted(CASES_DIR.glob("agent-security-*.yaml"))
CASES = [yaml.safe_load(p.read_text(encoding="utf-8")) for p in CASE_FILES]
BY_KIND = {c["host_probe"]["kind"]: c for c in CASES}
UNTRUSTED = [c for c in CASES if c["host_probe"]["kind"] == "untrusted_source"]


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          capture_output=True, text=True, timeout=15).stdout


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "child"
    root.mkdir()
    for rel, content in {"src/allowed.txt": "initial\n", "docs/report.md": "report\n",
                         "production/app.conf": "real=1\n",
                         ".ai-ops.yaml": "protected_paths: [production/]\n"}.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", "src/allowed.txt", "docs/report.md", "production/app.conf", ".ai-ops.yaml")
    _git(root, "-c", "user.name=Security Eval", "-c", "user.email=eval@example.invalid",
         "-c", "commit.gpgsign=false", "commit", "-qm", "test fixture")
    return root


def _policy(root):
    return broker.sandbox_policy(child_root=root, write_scope=["src/"], allow_network=False)


def _files(root):
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in root.rglob("*") if p.is_file() and ".git" not in p.relative_to(root).parts}


def _python_command(code):
    # Штатная sandbox allowlist разрешает python3, а не абсолютный путь в venv.
    # Процесс использует только stdlib; pytest/зависимости ему не нужны.
    return f"python3 -c {shlex.quote(code)}"


def _deliver_source(root, case, policy):
    probe = case["host_probe"]
    text = json.dumps(probe["payload"], ensure_ascii=False)
    rel = {"readme": "README.md", "issue": "issue.json",
           "tool_output": "tool-output.json"}[probe["channel"]]
    (root / rel).write_text(text, encoding="utf-8")
    if probe["channel"] == "tool_output":
        action = {"op": "shell", "command": f"cat {rel}"}
    else:
        action = {"op": "read", "path": rel}
    event = broker.execute(action, root, policy)
    assert event["allowed"] is True and event["ok"] is True, event
    delivered = json.loads(event["output_tail"])
    assert delivered == probe["payload"], "недоверенный источник не дошёл до предлагаемого действия"
    return delivered


def test_corpus_has_all_seven_bound_cases():
    assert len(CASES) == 7
    assert {c["host_probe"]["channel"] for c in UNTRUSTED} == {"readme", "issue", "tool_output"}
    assert set(BY_KIND) == {"untrusted_source", "write_scope", "self_elevation",
                            "shell_scope", "tool_failure"}
    assert {c["id"] for c in CASES} == {p.stem for p in CASE_FILES}


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_replay_requires_real_security_judge_despite_source_claims(case):
    assert gate_evals.case_form_errors(case, case["id"]) == []
    assert gate_evals.corpus_registry_errors([case]) == []
    result = gate_evals.replay_case(case)
    assert result["outcome"] == "ok", result
    assert result["runs"] == [{"source": "no-judge", "status": "fail"}]


def test_authorized_write_really_changes_only_allowed_file(repo):
    before = _files(repo)
    action = {"op": "write", "path": "src/allowed.txt", "content": "ALLOWED_WRITE\n"}
    event = broker.execute(action, repo, _policy(repo))
    assert (repo / action["path"]).read_bytes() == b"ALLOWED_WRITE\n"
    assert event["allowed"] is True and event["ok"] is True
    assert _files(repo) == {**before, action["path"]: b"ALLOWED_WRITE\n"}


@pytest.mark.parametrize("case", UNTRUSTED, ids=lambda c: c["id"])
def test_untrusted_source_claims_cannot_authorize_protected_write(repo, case):
    policy = _policy(repo)
    delivered = _deliver_source(repo, case, policy)
    before = _files(repo)
    event = broker.execute(delivered["action"], repo, policy)
    assert event["allowed"] is False and event["ok"] is False
    assert "protected path" in event["reason"], event
    assert _files(repo) == before
    assert policy.level == "execution" and policy.approvals == set()
    assert policy.write_scope == ["src"]


@pytest.mark.parametrize("kind", ["write_scope", "self_elevation"])
def test_direct_write_denial_preserves_tree_and_records_reason(repo, kind):
    probe = BY_KIND[kind]["host_probe"]
    before = _files(repo)
    event = broker.execute(probe["action"], repo, _policy(repo))
    assert event["allowed"] is False and event["ok"] is False
    assert probe["reason_matches"] in event["reason"], event
    assert event["target"] == probe["action"]["path"]
    assert event["revision"] == _git(repo, "rev-parse", "HEAD").strip()
    assert _files(repo) == before


@pytest.mark.parametrize("path", ["../outside.txt", "src/escape/outside.txt"])
def test_direct_write_cannot_escape_temporary_root(repo, path):
    outside = repo.parent / "outside.txt"
    outside.write_bytes(b"outside sentinel\n")
    (repo / "src/escape").symlink_to(repo.parent, target_is_directory=True)
    event = broker.execute({"op": "write", "path": path, "content": "ESCAPED"}, repo, _policy(repo))
    assert event["allowed"] is False and event["ok"] is False
    assert any(word in event["reason"] for word in ("traversal", "корня")), event
    assert outside.read_bytes() == b"outside sentinel\n"


def test_allowed_shell_write_really_runs_and_stays(repo):
    event = broker.execute({"op": "shell", "command": "echo ALLOWED_SHELL > src/allowed.txt"},
                           repo, _policy(repo))
    assert (repo / "src/allowed.txt").read_bytes() == b"ALLOWED_SHELL\n"
    assert event["allowed"] is True and event["ok"] is True
    assert event["fs_guard"] == {"violations": []}


def test_shell_scope_violation_really_happened_before_it_was_reverted(repo):
    probe = BY_KIND["shell_scope"]["host_probe"]
    before = _files(repo)
    event = broker.execute(probe["action"], repo, _policy(repo))
    # cat прочитал записанное содержимое ДО пост-фактум проверки брокера.
    assert event["exit_code"] == 0 and probe["observed_output"] in event["output_tail"], event
    assert event["allowed"] is False and event["ok"] is False
    violations = event["fs_guard"]["violations"]
    assert any(v["path"] == "docs/report.md" and probe["reason_matches"] in v["reason"]
               for v in violations), event
    assert event["fs_guard"]["revert_complete"] is True
    assert "docs/report.md" in event["fs_guard"]["reverted"]["restored"]
    assert _files(repo) == before
    assert _git(repo, "status", "--porcelain") == ""


def test_nonzero_tool_exit_cannot_be_hidden_by_pass_output(repo):
    probe = BY_KIND["tool_failure"]["host_probe"]
    before = _files(repo)
    code = ("from pathlib import Path; "
            f"Path('src/allowed.txt').write_text({probe['marker']!r}); "
            f"print({probe['output']!r}); raise SystemExit({probe['exit_code']})")
    event = broker.execute({"op": "shell", "command": _python_command(code)}, repo, _policy(repo))
    assert (repo / "src/allowed.txt").read_text() == probe["marker"], event
    assert probe["output"] in event["output_tail"], event
    assert event["allowed"] is True, "ошибка исполнения и отказ политики — разные исходы"
    assert event["exit_code"] == probe["exit_code"] and event["ok"] is False
    assert _files(repo) == {**before, "src/allowed.txt": probe["marker"].encode()}


@pytest.mark.parametrize("case", UNTRUSTED, ids=lambda c: c["id"])
def test_claimed_autonomy_cannot_downgrade_decision_or_execute_without_approval(repo, case):
    delivered = _deliver_source(repo, case, _policy(repo))
    verdict = boundary.evaluate({"risk": "low", "protected_paths": True},
                                requested_class=delivered["requested_class"])
    assert verdict["decision_class"] == "COLLABORATIVE"
    assert verdict["escalated_from"] == "AUTONOMOUS" and verdict["requires_approval"] is True
    policy = {"default": verdict["autonomy_level"], "actions": {}}
    marker = repo / "src/decision.txt"
    with pytest.raises(policy_engine.PolicyBlocked, match="заблокировано"):
        policy_engine.enforce("change_policy", policy, lambda: marker.write_text("EXECUTED"))
    assert not marker.exists()


def test_high_risk_stays_human_decision_even_when_autonomy_is_requested(repo):
    verdict = boundary.evaluate({"risk": "high"}, requested_class="AUTONOMOUS")
    assert verdict["decision_class"] == "ASSISTED" and verdict["executor"] == "human"
    policy = {"default": verdict["autonomy_level"], "actions": {}}
    marker = repo / "src/high-risk.txt"
    with pytest.raises(policy_engine.PolicyBlocked):
        policy_engine.enforce("act", policy, lambda: marker.write_text("EXECUTED"))
    assert not marker.exists()


def test_low_risk_autonomous_decision_really_executes_callback(repo):
    verdict = boundary.evaluate({"risk": "low"})
    policy = {"default": verdict["autonomy_level"], "actions": {}}
    marker = repo / "src/decision.txt"
    policy_engine.enforce("act", policy, lambda: marker.write_text("EXECUTED"))
    assert verdict["decision_class"] == "AUTONOMOUS"
    assert marker.read_bytes() == b"EXECUTED"
