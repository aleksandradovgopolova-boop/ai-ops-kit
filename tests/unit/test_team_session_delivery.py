"""Штатные init/update и переносимая конфигурация; не live-runtime приёмка."""
import json
import os
import subprocess
import sys

import pytest
import yaml

from tests.unit._installer_helpers import installed, installed_copy, _run_cli


def test_update_delivers_hooks_to_clean_clone_without_author_home(installed_copy, tmp_path):  # noqa: F811 — pytest fixture import
    root = installed_copy
    (root / "AGENTS.md").write_text("Собственные правила проекта.\n")
    cfg_path = root / ".ai-ops.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    cfg.setdefault("standard", {})["team_session"] = "required"
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True))
    result = _run_cli(root, "update", "--in-place")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Собственные правила проекта." in (root / "AGENTS.md").read_text()
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "fixture integration"], check=True, capture_output=True)
    clone = tmp_path / "independent-clone"
    subprocess.run(["git", "clone", "--quiet", str(root), str(clone)], check=True, capture_output=True)
    home = tmp_path / "independent-home"
    home.mkdir()
    env = {**os.environ, "HOME": str(home), "CODEX_HOME": str(home / "codex"),
           "PYTHONPATH": "", "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
           "GIT_CONFIG_GLOBAL": "/dev/null"}
    script = clone / ".ai/managed/templates/runtime/team_hook.py"
    assert script.is_file()
    for runtime in ("claude-code", "codex"):
        payload = {"hook_event_name": "SessionStart", "cwd": str(clone),
                   "session_id": "independent-fixture", "source": "startup"}
        proc = subprocess.run([sys.executable, str(script), "--runtime", runtime],
                              input=json.dumps(payload), text=True, capture_output=True, env=env, cwd=clone)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        context = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
        assert str(clone.resolve()) in context
        assert str(root.resolve()) not in context
    assert not (home / "codex").exists()  # личная копия правил/доверия не создавалась
    validator = clone / ".ai/managed/ai_ops_kit/validation/validate_ai_ops_child.py"
    good = subprocess.run([sys.executable, str(validator)], cwd=clone, env=env, text=True, capture_output=True)
    assert good.returncode == 0, good.stdout + good.stderr
    (clone / ".codex/hooks.json").unlink()
    bad = subprocess.run([sys.executable, str(validator)], cwd=clone, env=env, text=True, capture_output=True)
    assert bad.returncode != 0
    assert ".codex/hooks.json" in bad.stdout
    from ai_ops_kit.lifecycle import child_doctor
    (clone / "AGENTS.md").unlink()
    report = child_doctor.assess(clone)
    checks = [c for c in report["checks"] if c["check"] == "проектное подключение Claude/Codex"]
    assert checks and checks[0]["ok"] is False
    assert "AGENTS.md" in checks[0]["detail"]


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("failure", ["smoke", "missing-migration"])
def test_failed_update_restores_team_entry_bytes_and_removes_new_hooks(installed_copy, existing, failure):  # noqa: F811
    """Реальный update откатывает и отсутствовавшие, и собственные проектные входы."""
    from tests.unit._installer_helpers import INSTALLER

    root = installed_copy
    paths = ["AGENTS.md", "CLAUDE.md", ".claude/settings.json", ".codex/hooks.json"]
    for name in paths:
        path = root / name
        if existing:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'{"hooks": {}, "owner": true}\n' if name.endswith(".json")
                             else "Правила владельца.\n".encode())
        else:
            path.unlink(missing_ok=True)
    before = {name: (root / name).read_bytes() if (root / name).exists() else None for name in paths}
    cfg_path = root / ".ai-ops.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    cfg["parent"]["installed_version"] = "4.11.1"
    cfg.setdefault("standard", {})["team_session"] = "required"
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True))
    old_config = cfg_path.read_bytes()
    hook = root / ".ai/managed/templates/runtime/team_hook.py"
    hook.unlink()  # прежняя установка ещё не имела bootstrap
    # Реальный smoke наблюдает доставленные hooks/bootstrap ДО принудительной ошибки.
    probe = root.parent / "observe-then-fail.py"
    probe.write_text("""
import hashlib
import json
from pathlib import Path
root = Path.cwd()
hook = root / '.ai/managed/templates/runtime/team_hook.py'
assert hook.is_file()
for relative in ('.claude/settings.json', '.codex/hooks.json'):
    doc = json.loads((root / relative).read_text())
    for event in ('SessionStart', 'UserPromptSubmit', 'Stop'):
        assert any('team_hook.py' in item['command']
                   for group in doc['hooks'][event] for item in group['hooks'])
(root / '.ai/runtime/rollback-observed.json').write_text(json.dumps({
    'hooks_present': True, 'bootstrap_sha256': hashlib.sha256(hook.read_bytes()).hexdigest()}))
raise SystemExit(1)
""")
    # Подлинный update; checksums фиксируют старую установку без нового bootstrap.
    script = """
import importlib.util
import sys
spec = importlib.util.spec_from_file_location('rollback_installer', sys.argv[1])
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)
mod._core().write_checksums()
if sys.argv[3] == 'missing-migration':
    manifest = mod._core().manifest()
    manifest['package_migrations'] = {'chain': ['missing-rollback-probe']}
    mod._core().manifest = lambda: manifest
raise SystemExit(mod._update_ops().cmd_update(in_place=True,
    smoke_checks=[[sys.argv[2]]]))
"""
    proc = subprocess.run([sys.executable, "-c", script, str(INSTALLER), str(probe), failure], cwd=root,
                          capture_output=True, text=True, timeout=180)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    report = json.loads((root / ".ai/runtime/last-update-report.json").read_text())
    assert report["status"] == ("rolled_back" if failure == "smoke" else "failed"), proc.stdout + proc.stderr
    if failure == "smoke":
        observed = json.loads((root / ".ai/runtime/rollback-observed.json").read_text())
        assert observed["hooks_present"] is True
        assert len(observed["bootstrap_sha256"]) == 64
    assert cfg_path.read_bytes() == old_config
    assert not hook.exists()
    for name, content in before.items():
        path = root / name
        assert (path.read_bytes() if path.exists() else None) == content, name
