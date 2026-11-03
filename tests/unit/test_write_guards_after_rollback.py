"""Installed R1 policy guards survive the real R5 failed-update rollback."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import yaml

from tests.unit._installer_helpers import INSTALLER, _make_child_repo, _run_cli


def test_failed_same_version_update_restores_enforced_child_policy(tmp_path):
    root = _make_child_repo(tmp_path / "child")
    fixture_codex_dir = tmp_path / "codex-fixture"
    env = {**os.environ, "CODEX_HOME": str(fixture_codex_dir),
           "GIT_CONFIG_GLOBAL": "/dev/null", "PYTHONDONTWRITEBYTECODE": "1"}
    initialized = _run_cli(root, "init", ".", env=env)
    assert initialized.returncode == 0, initialized.stdout + initialized.stderr
    config = root / ".ai-ops.yaml"
    data = yaml.safe_load(config.read_text())
    data["protected_paths"] = ["private-assets/"]
    config.write_text(yaml.safe_dump(data, allow_unicode=True))
    original_config = config.read_bytes()
    entry = root / "ai-ops"
    entry.write_bytes(b"old owner entrypoint\n")
    original_entry = entry.read_bytes()
    observed = tmp_path / "observed.json"
    probe = tmp_path / "negative-smoke.py"
    probe.write_text(f'''
import json
from pathlib import Path
import sys
root = Path.cwd()
managed = root / '.ai/managed'
sys.path.insert(0, str(managed))
from ai_ops_kit.engine import tool_broker as broker
assert Path(broker.__file__).resolve().is_relative_to(managed.resolve())
assert (root / 'ai-ops').read_bytes() != {original_entry!r}
action = {{'op': 'write', 'path': 'private-assets/probe.txt', 'content': 'harmless fixture'}}
policy = broker.Policy(level='controlled-write', write_scope=['private-assets/'], child_root=root)
denied = broker.execute(action, root, policy)
assert not denied['allowed'] and not denied['ok']
(root / '.ai-ops.yaml').write_text('protected_paths: [')
try:
    broker.Policy(level='controlled-write', write_scope=['private-assets/'], child_root=root)
except broker.PolicyLoadError:
    invalid_refused = True
else:
    raise AssertionError('malformed policy became usable')
Path({str(observed)!r}).write_text(json.dumps({{'installed_guard_executed': True,
                                              'malformed_policy_refused': invalid_refused}}))
raise SystemExit(1)
''')
    driver = '''
import importlib.util
from pathlib import Path
import sys
spec = importlib.util.spec_from_file_location('integration_installer', sys.argv[1])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
raise SystemExit(module._update_ops().cmd_update(in_place=True, smoke_checks=[[sys.argv[2]]]))
'''
    result = subprocess.run([sys.executable, "-c", driver, str(INSTALLER), str(probe)],
                            cwd=root, env=env, capture_output=True, text=True, timeout=180)
    assert result.returncode == 1, result.stdout + result.stderr
    assert json.loads(observed.read_text()) == {"installed_guard_executed": True,
                                               "malformed_policy_refused": True}
    report = json.loads((root / ".ai/runtime/last-update-report.json").read_text())
    assert report["status"] == "rolled_back", report
    assert config.read_bytes() == original_config
    assert entry.read_bytes() == original_entry
    assert not (root / "private-assets/probe.txt").exists()
    after = subprocess.run([sys.executable, "-c", '''
from pathlib import Path
import sys
root = Path.cwd()
sys.path.insert(0, str(root / '.ai/managed'))
from ai_ops_kit.engine import tool_broker as broker
policy = broker.Policy(level='controlled-write', write_scope=['private-assets/'], child_root=root)
result = broker.execute({'op': 'write', 'path': 'private-assets/probe.txt', 'content': 'fixture'}, root, policy)
assert not result['allowed'] and not result['ok']
assert not (root / 'private-assets/probe.txt').exists()
'''], cwd=root, env=env, capture_output=True, text=True, timeout=30)
    assert after.returncode == 0, after.stdout + after.stderr
