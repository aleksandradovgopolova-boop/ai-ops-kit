"""Штатные init/update и переносимая конфигурация; не live-runtime приёмка."""
import json
import os
import subprocess
import sys

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
