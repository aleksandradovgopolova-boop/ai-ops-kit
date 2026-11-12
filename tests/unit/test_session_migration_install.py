"""Stock historical-source install/update; synthetic requests, no provider/trust calls."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest
import yaml

from ai_ops_kit.lifecycle import project_session as sessions
from ai_ops_kit.lifecycle import session_migration as migration
from ai_ops_kit.lifecycle import session_migration_store as store
from tests.unit._installer_helpers import _make_child_repo

SOURCE = Path(__file__).resolve().parents[2]
OLD = "ef6cdf6970ae3ef71724834c9ccf1e4c0824fa45"
# Установка кита — это и CI-файлы, которые он кладёт в `.github/` (обновление освежает их, #1512):
# откат установки без них оставил бы новый workflow рядом со старым кодом.
INSTALLED = migration.INSTALL + (".github",)


@pytest.mark.slow
@pytest.mark.parametrize("outcome", ["rollback", "new-turn", "no-turn-id"])
def test_stock_old_source_update_migration_and_state_rollback(tmp_path, outcome):
    available = subprocess.run(["git", "cat-file", "-e", OLD + "^{commit}"], cwd=SOURCE, capture_output=True)
    if available.returncode:
        pytest.skip("historical source ef6cdf unavailable in shallow checkout; requires full-history qualification")
    old = tmp_path / "old-kit"
    old.mkdir()
    archive = subprocess.run(["git", "archive", OLD], cwd=SOURCE, check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as package:
        package.extractall(old, filter="data")
    root = _make_child_repo(tmp_path / "child")
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONPATH": "", "PYTHONNOUSERSITE": "1", "AI_OPS_PYTHON": sys.executable}

    def run(command, *, payload=None, cwd=root):
        result = subprocess.run(command, cwd=cwd, env=env, input=payload,
                                text=True, capture_output=True, timeout=180)
        assert result.returncode == 0, result.stdout[-12000:] + result.stderr[-3000:]
        return result

    run([sys.executable, str(old / "installer/ai_ops.py"), "init", str(root)])
    config = root / ".ai-ops.yaml"
    cfg = yaml.safe_load(config.read_text())
    cfg.setdefault("standard", {})["team_session"] = "required"
    config.write_text(yaml.safe_dump(cfg, allow_unicode=True))
    run([sys.executable, str(old / "installer/ai_ops.py"), "update", "--in-place"])
    # Own product changes exist before the requests; migration must preserve these bytes.
    (root / "src/calc.py").write_text("def add(a, b):\n    return a + b  # owner change\n")
    requests = {}
    for runtime in sorted(sessions.RUNTIMES):
        payload = {"hook_event_name": "UserPromptSubmit", "cwd": str(root), "session_id": runtime + "-fixture",
                   "turn_id": "old-event", "prompt": "Synthetic migration request " + runtime}
        response = run([sys.executable, str(root / ".ai/managed/templates/runtime/team_hook.py"),
                        "--runtime", runtime], payload=json.dumps(payload))
        assert json.loads(response.stdout).get("continue") is not False, response.stdout
        requests[runtime] = sessions.load(root, runtime, runtime + "-fixture")
    before = migration.protected_files(root)
    install_before = store.inventory(root, INSTALLED)
    product_before = (root / "src/calc.py").read_bytes()
    snapshot, plan = tmp_path / "snapshot.json", tmp_path / "plan.json"
    captured = migration.capture(root, snapshot)
    run([sys.executable, str(SOURCE / "installer/ai_ops.py"), "update", "--in-place"])
    assert migration.protected_files(root) == before
    preview = migration.preview(root, snapshot, captured["sha256"], plan)
    assert preview["eligible"] == 2, store.document(plan)["preserved"]
    applied = migration.apply(root, snapshot, captured["sha256"], plan, preview["sha256"])
    assert applied["changed"] == 2
    for runtime, original in requests.items():
        saved = sessions.pending(root, runtime, runtime + "-fixture")
        assert saved["request_id"] == original["request_id"]
        assert saved["binding"]["managed_sha256"] != original["binding"]["managed_sha256"]
        assert saved["status"] == "pending" and "execution" not in saved
    assert (root / "src/calc.py").read_bytes() == product_before
    if outcome != "rollback":
        for runtime, original in requests.items():
            payload = {"hook_event_name": "UserPromptSubmit", "cwd": str(root),
                       "session_id": runtime + "-fixture", "prompt": "Additional synthetic detail",
                       "turn_id": "actual-new-turn" if outcome == "new-turn" else None}
            response = run([sys.executable, str(root / ".ai/managed/templates/runtime/team_hook.py"),
                            "--runtime", runtime], payload=json.dumps(payload))
            assert json.loads(response.stdout).get("continue") is not False, response.stdout
            saved = sessions.pending(root, runtime, runtime + "-fixture")
            assert saved["request_id"] == original["request_id"] and saved["prompt"] == original["prompt"]
            assert len(saved["input_events"]) == 1
            assert store.document(root / saved["input_events"][0])["prompt"] == payload["prompt"]
        with_new_inputs = migration.protected_files(root)
        with pytest.raises(ValueError, match="diverged|concurrent"):
            migration.rollback(root, applied["id"], preview["sha256"], plan)
        assert migration.protected_files(root) == with_new_inputs
        assert (root / "src/calc.py").read_bytes() == product_before
        return
    migration.rollback(root, applied["id"], preview["sha256"], plan)
    assert migration.protected_files(root) == before
    # State rollback is separate from installation rollback. Restore only this disposable
    # fixture's captured installation, then verify OLD code reads the identical pending IDs.
    after = store.inventory(root, INSTALLED)
    for name in set(after) - set(install_before):
        (root / name).unlink()
    for name, entry in install_before.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(store.raw(entry))
        path.chmod(entry["mode"])
    assert store.inventory(root, INSTALLED) == install_before
    for runtime, original in requests.items():
        script = ("import sys,json;sys.path.insert(0,'.ai/managed');"
                  "from ai_ops_kit.lifecycle import project_session as s;"
                  "t=s.pending('.',sys.argv[1],sys.argv[2]);print(json.dumps(t))")
        result = run([sys.executable, "-c", script, runtime, runtime + "-fixture"])
        assert json.loads(result.stdout) == original
    assert (root / "src/calc.py").read_bytes() == product_before
