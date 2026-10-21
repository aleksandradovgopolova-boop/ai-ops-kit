"""Own outputs are post-bound, never a blanket ignore or a repair of old receipts."""
import json
import subprocess
import sys

import pytest

from ai_ops_kit.shared import lifecycle_store as vr

pytestmark = pytest.mark.unit
CACHE = ".hypothesis/constants/0123456789abcdef"


@pytest.fixture
def context():
    return {"complete": True, "toolchain": "1" * 64,
            "dependencies": "2" * 64, "environment": "3" * 64}


def test_real_generated_output_then_repeat_reuses_post_bound_result(tmp_path, context):
    command = [sys.executable, "-I", "-S", "-c",
               "from pathlib import Path; p=Path('.ai/runtime/count'); "
               "p.parent.mkdir(parents=True,exist_ok=True); "
               "p.write_text(str(int(p.read_text())+1) if p.exists() else '1'); "
               f"c=Path({CACHE!r}); c.parent.mkdir(parents=True,exist_ok=True); c.write_text('derived')"]
    def run():
        return vr.run(tmp_path, "pytest", command,
                      lambda: {"status": "PASS", "exit_code": subprocess.call(command, cwd=tmp_path)},
                      lambda: context, output_contract=vr.PYTEST_OUTPUTS)
    first, repeat = run(), run()
    assert (tmp_path / ".ai/runtime/count").read_text() == "1"
    assert (tmp_path / CACHE).read_text() == "derived"
    assert first["status"] == repeat["status"] == "PASS" and repeat["reused"]
    observed = first["input_observation"]
    assert observed["before"]["tree"] != observed["after"]["tree"]
    assert observed["changed_paths"][0]["role"] == "output"
    assert first["inputs"] == observed["after"]
    (tmp_path / CACHE).write_text("tampered after PASS")
    assert not run()["reused"]
    assert (tmp_path / ".ai/runtime/count").read_text() == "2"


@pytest.mark.parametrize("name", ["source.py", "requirements.lock", "pytest.ini", ".env",
                                      ".hypothesis/custom-config.yaml"])
def test_semantic_mutation_during_run_stays_blocked(tmp_path, context, name):
    def execute():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("changed")
        return {"status": "PASS", "exit_code": 0}
    result = vr.run(tmp_path, "test", "pytest", execute, lambda: context,
                    output_contract=vr.PYTEST_OUTPUTS)
    assert (tmp_path / name).is_file()
    assert result["status"] == "BLOCKED" and result["inputs"] is None
    assert result["input_observation"]["changed_paths"][0]["role"] == "input"


@pytest.mark.parametrize("field", ["toolchain", "dependencies", "environment"])
def test_context_mutation_with_outputs_stays_blocked(tmp_path, context, field):
    def execute():
        context[field] = "4" * 64
        return {"status": "PASS", "exit_code": 0}
    result = vr.run(tmp_path, "test", "pytest", execute, lambda: context,
                    output_contract=vr.PYTEST_OUTPUTS)
    assert result["status"] == "BLOCKED" and not result["reuse_eligible"]
    assert "context" in result["input_observation"]["changed_components"]


def test_without_contract_new_cache_is_blocked_and_keeps_both_fingerprints(tmp_path, context):
    def execute():
        p = tmp_path / CACHE
        p.parent.mkdir(parents=True)
        p.write_text("cache")
        return {"status": "PASS", "exit_code": 0}
    result = vr.run(tmp_path, "test", "pytest", execute, lambda: context)
    assert result["status"] == "BLOCKED" and result["inputs"] is None
    saved = json.loads(open(result["source"]).read())
    assert saved["input_observation"]["before"]["tree"] != saved["input_observation"]["after"]["tree"]
    assert saved["input_observation"]["changed_paths"][0]["path"] == CACHE


def test_tracked_cache_path_is_always_an_input(tmp_path, context):
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, check=True)
    git("init", "-q")
    p = tmp_path / CACHE
    p.parent.mkdir(parents=True)
    p.write_text("tracked source")
    git("add", CACHE)
    git("-c", "user.name=fixture", "-c", "user.email=f@f", "commit", "-qm", "base")
    def execute():
        p.write_text("mutation")
        return {"status": "PASS", "exit_code": 0}
    result = vr.run(tmp_path, "test", "pytest", execute, lambda: context,
                    output_contract=vr.PYTEST_OUTPUTS)
    assert result["status"] == "BLOCKED"
    assert result["input_observation"]["changed_paths"][0]["role"] == "input"


def test_unsupported_output_contract_does_not_execute(tmp_path, context):
    calls = []
    with pytest.raises(ValueError, match="output contract"):
        vr.run(tmp_path, "test", "pytest", lambda: calls.append(1), lambda: context,
               output_contract={"ignore": ["**"]})
    assert calls == []


def test_pycache_is_an_existing_output_without_new_exemptions(tmp_path, context):
    def execute():
        p = tmp_path / "__pycache__/source.cpython-314.pyc"
        p.parent.mkdir()
        p.write_bytes(b"generated")
        return {"status": "PASS", "exit_code": 0}
    result = vr.run(tmp_path, "test", "pytest", execute, lambda: context)
    assert (tmp_path / "__pycache__/source.cpython-314.pyc").is_file()
    assert result["status"] == "PASS"
    assert result["input_observation"]["changed_paths"] == []


def test_git_ref_change_is_reported_separately_from_generated_output(tmp_path, context):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path).decode().strip()
    git("init", "-q")
    (tmp_path / "source.py").write_text("source")
    git("add", "source.py")
    git("-c", "user.name=fixture", "-c", "user.email=f@f", "commit", "-qm", "base")
    def execute():
        git("update-ref", "refs/heads/registry-change", git("rev-parse", "HEAD"))
        return {"status": "PASS", "exit_code": 0}
    result = vr.run(tmp_path, "test", "pytest", execute, lambda: context,
                    output_contract=vr.PYTEST_OUTPUTS)
    assert git("show-ref", "--verify", "refs/heads/registry-change")
    assert result["status"] == "BLOCKED"
    assert result["input_observation"]["changed_components"] == ["git"]
    assert result["input_observation"]["changed_paths"] == []


def test_tool_call_metadata_does_not_invalidate_environment(monkeypatch):
    monkeypatch.setenv("CODEX_TOOL_CALL_ID", "call-one")
    before = vr.environment_digest()
    monkeypatch.setenv("CODEX_TOOL_CALL_ID", "call-two")
    assert vr.environment_digest() == before


@pytest.mark.parametrize("name", ["CODEX_TASK_WORKSPACE_VERIFYING_IDENTITY",
                                      "BROWSER_USE_ACCESS_VERIFYING_IDENTITY", "PYTHONPATH", "CI"])
def test_executor_access_and_execution_environment_still_invalidates(monkeypatch, name):
    monkeypatch.setenv(name, "before")
    before = vr.environment_digest()
    monkeypatch.setenv(name, "after")
    assert vr.environment_digest() != before


def test_extracted_receipts_import_first_and_use_current_main_durable_io(tmp_path):
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    code = ("import sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); "
            "from ai_ops_kit.shared import claim_provenance as r; "
            "from ai_ops_kit.shared import lifecycle_store as l; "
            "assert l.run is r.run; "
            "p=Path(sys.argv[2]); assert l.durable_create_batch(p,{'input':'value'})['ok']; "
            "r.atomic_json(p/'receipt.json',{'kind':'fixture','value':1})")
    subprocess.run([sys.executable, "-I", "-c", code, str(root), str(tmp_path)], check=True, timeout=10)
    assert (tmp_path / "input").read_text() == "value"
    assert json.loads((tmp_path / "receipt.json").read_text()) == {"kind": "fixture", "value": 1}
