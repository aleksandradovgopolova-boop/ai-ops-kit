"""CLI wired через Tool Broker: настоящая fixture-операция, без внешней платформы."""
import json
import shlex
import subprocess

import pytest

from ai_ops_kit.devtools.release_delivery_cli import run_contract
from ai_ops_kit.delivery.record_delivery import ReleaseBlocked
from ai_ops_kit.engine import tool_broker
from ai_ops_kit.shared import lifecycle_store as vr

pytestmark = pytest.mark.unit


@pytest.fixture
def contract(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args], text=True).strip()
    git("init", "-q")
    (tmp_path / "VERSION").write_text("fixture-1\n")
    git("add", "VERSION")
    git("-c", "user.name=fixture", "-c", "user.email=f@f", "commit", "-qm", "fixture")
    runtime = tmp_path / ".ai/runtime"
    runtime.mkdir(parents=True)
    artifact = runtime / "artifact"
    artifact.write_text("fixture payload")
    expected = {"version": "fixture-1", "sha": git("rev-parse", "HEAD"),
                "artifact_digest": "sha256:" + vr.file_digest(artifact), "environment": "fixture"}
    def command(body):
        return shlex.join(["python3", "-I", "-S", "-c", body])
    def emit(value):
        return command(f"print({json.dumps(value)!r})")
    observation = {**expected, "status": "PASS", "source": "fixture:published-file"}
    return {"expected": expected, "artifact": ".ai/runtime/artifact",
            "preflight": [{"surface": "agent", "operation": "read-fixture",
                           "command": emit({"status": "PASS", "code": "fixture"})}],
            "checks": [{"name": "fixture-ci", "command": emit({"name": "fixture-ci", "status": "PASS",
                        "source": "fixture:ci", "sha": expected["sha"], "inputs_digest": "c" * 64})}],
            "deploy_command": command("from pathlib import Path; "
                                      f"Path('.ai/runtime/published').write_text({json.dumps(observation)!r})"),
            "runtime_command": command("from pathlib import Path; print(Path('.ai/runtime/published').read_text())"),
            "public_command": command("from pathlib import Path; print(Path('.ai/runtime/published').read_text())"),
            "recovery": {"procedure": "Сверить fixture-артефакт вручную.", "automatic_rollback": False}}


def test_cli_executes_through_existing_broker(tmp_path, contract):
    result = run_contract(tmp_path, contract, "owner", tool_broker, tool_broker.sandbox_policy(tmp_path))
    assert (tmp_path / ".ai/runtime/published").is_file()
    assert result["status"] == "PASS"


def test_cli_never_uses_agent_access_as_connector_access(tmp_path, contract):
    contract["preflight"][0]["surface"] = "connector"
    with pytest.raises(ReleaseBlocked, match="доступа"):
        run_contract(tmp_path, contract, "owner", tool_broker, tool_broker.sandbox_policy(tmp_path))
    assert not (tmp_path / ".ai/runtime/published").exists()


@pytest.mark.parametrize("field,value", [("sha", "f" * 40), ("version", "wrong"), ("artifact_digest", "sha256:" + "f" * 64)])
def test_cli_rejects_wrong_source_or_artifact_identity(tmp_path, contract, field, value):
    contract["expected"][field] = value
    with pytest.raises(ReleaseBlocked):
        run_contract(tmp_path, contract, "owner", tool_broker, tool_broker.sandbox_policy(tmp_path))
    assert not (tmp_path / ".ai/runtime/published").exists()
