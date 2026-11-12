"""Предрелизный шов; реальный публичный прогон идёт явно, не в обычных тестах."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from ai_ops_kit.devtools import fleet_rehearsal as rehearsal

KIT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.unit


def test_release_waits_for_rehearsal_at_exact_sha():
    jobs = yaml.safe_load((KIT / ".github/workflows/release.yml").read_text())["jobs"]
    field = jobs["field-rehearsal"]
    assert field["permissions"] == {"contents": "read"}
    assert field["steps"][0]["with"] == {"ref": "${{ github.sha }}", "persist-credentials": False}
    assert any("pytest tests/unit/test_fleet_release_gate.py -q -m release_gate" in s.get("run", "") for s in field["steps"])
    assert "field-rehearsal" in jobs["release"]["needs"]
    assert "needs.field-rehearsal.result == 'success'" in jobs["release"]["if"]
    assert "needs.full-gate.result == 'success'" in jobs["release"]["if"]


def test_duplicate_project_does_not_count_as_second_reference(tmp_path):
    cases = rehearsal.load_cases(KIT / "qualification/fleet-rehearsal.yaml")
    case = dict(cases[0], repository=cases[0]["repository"].upper())
    path = tmp_path / "fleet.yaml"
    path.write_text(yaml.safe_dump({"schema_version": 1, "cases": [cases[0], case]}))
    with pytest.raises(rehearsal.RehearsalError, match="invalid_reference_repository"):
        rehearsal.load_cases(path)


def test_worker_refuses_original_checkout_before_installer(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(rehearsal, "_trial", lambda *args: pytest.fail("installer must not run"))
    assert rehearsal.main(["--worker", str(tmp_path), "4.11.4", "apply", str(tmp_path / "unused")]) == 1
    assert "worker_requires_disposable_checkout" in capsys.readouterr().out


def test_witness_requires_installed_new_version_then_rejects_smoke(tmp_path):
    managed = tmp_path / ".ai/managed"
    managed.mkdir(parents=True)
    version = managed / "VERSION"
    version.write_text("4.11.4\n")
    witness = tmp_path / "witness"
    payload = tmp_path / "expected.json"
    payload.write_text(json.dumps({"files": {".ai/managed/engine.py": hashlib.sha256(b"new").hexdigest()},
                                   "removed": [".ai/managed/old.py"]}))
    cmd = [sys.executable, "-c", rehearsal._WITNESS, "4.13.1", str(witness), str(payload)]
    assert subprocess.run(cmd, cwd=tmp_path, check=False).returncode == 7
    assert not witness.exists()
    version.write_text("4.13.1\n")
    assert subprocess.run(cmd, cwd=tmp_path, check=False).returncode == 7
    (managed / "engine.py").write_bytes(b"new")
    (managed / "old.py").touch()
    assert subprocess.run(cmd, cwd=tmp_path, check=False).returncode == 7
    (managed / "old.py").unlink()
    config = tmp_path / ".ai-ops.yaml"
    config.write_text("parent:\n  installed_version: 4.11.4\n")
    assert subprocess.run(cmd, cwd=tmp_path, check=False).returncode == 7
    assert not witness.exists()
    config.write_text("parent:\n  installed_version: 4.13.1\n")
    assert subprocess.run(cmd, cwd=tmp_path, check=False).returncode == 9
    assert witness.read_text() == "4.13.1"


def test_rehearsal_requires_both_apply_and_rollback(monkeypatch):
    sha = "a" * 40
    monkeypatch.setattr(rehearsal, "_git", lambda _root, command, *args: sha if command == "rev-parse" else "")
    monkeypatch.setattr(rehearsal, "_checkout", lambda root, case, mirrors: (root.mkdir(), (root / "source").touch()))
    seen = []

    def worker(_kit, root, case, mode, witness):
        assert (root / "source").is_file() and root.name == mode
        seen.append((case["repository"], mode))
        if mode == "rollback" and case["repository"].endswith("dashboard-kit"):
            raise rehearsal.RehearsalError("rollback_not_proven")
        return {"status": "pass"}

    monkeypatch.setattr(rehearsal, "_worker", worker)
    report = rehearsal.rehearse(KIT, sha)
    assert len(seen) == 4
    assert report["status"] == "fail"
    assert [row["status"] for row in report["projects"]] == ["fail", "pass"]


def test_git_snapshot_keeps_effective_order_of_duplicate_keys(tmp_path):
    def git(*args):
        return subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True).stdout

    git("init", "-q")
    git("-c", "user.name=Tester", "-c", "user.email=t@t", "commit", "--allow-empty", "-qm", "test")
    for value in ("owner", "other"):
        git("config", "--local", "--add", "user.name", value)
    before = rehearsal._snapshot(tmp_path)
    git("config", "--local", "--unset-all", "user.name")
    for value in ("other", "owner"):
        git("config", "--local", "--add", "user.name", value)
    assert git("config", "--local", "--get", "user.name").strip() == "owner"
    assert rehearsal._snapshot(tmp_path) != before
    with pytest.raises(rehearsal.RehearsalError, match="unrelated_git_config_changed"):
        rehearsal._check_preservation(before, rehearsal._snapshot(tmp_path), (), {}, {}, "kit")


def test_real_worker_separates_migration_output_from_receipt(installed):
    import shutil
    import tempfile

    with tempfile.TemporaryDirectory(prefix="kit-fleet-rehearsal-") as tmp:
        case_dir = Path(tmp) / "0"
        case_dir.mkdir()
        root = shutil.copytree(installed, case_dir / "apply", symlinks=True)
        managed = root / ".ai/managed"
        old = "4.0.0"
        version = managed / "VERSION"
        version.write_text(f"{old}\n")
        checksums = managed / ".checksums.json"
        hashes = json.loads(checksums.read_bytes())
        hashes["files"]["VERSION"] = hashlib.sha256(version.read_bytes()).hexdigest()
        checksums.write_text(json.dumps(hashes))
        provenance = managed / ".provenance.json"
        prov = json.loads(provenance.read_bytes())
        prov["installed_version"] = old
        provenance.write_text(json.dumps(prov))
        cfg = root / ".ai-ops.yaml"
        config = yaml.safe_load(cfg.read_bytes())
        config["parent"]["installed_version"] = old
        cfg.write_text(yaml.safe_dump(config))
        receipt = rehearsal._worker(KIT, root, {"installed_version": old}, "apply", case_dir / "unused")
        assert receipt["smoke_checks"] >= 1 and receipt["to"] == (KIT / "VERSION").read_text().strip()
        assert (case_dir / "result-apply.json").is_file()


def test_checkout_retries_only_the_same_https_pin(tmp_path, monkeypatch):
    pin = "a" * 40
    requests = []

    def git(_root, *args, protocol=""):
        if args[0] == "fetch":
            requests.append((args, protocol))
            if len(requests) == 1:
                raise rehearsal.RehearsalError("git_fetch_failed")
        return pin if args[0] == "rev-parse" else ""

    monkeypatch.setattr(rehearsal, "_git", git)
    rehearsal._checkout(tmp_path / "child", {"repository": "owner/public", "commit": pin})
    expected = ("fetch", "--no-tags", "--depth=1", "--update-shallow", "https://github.com/owner/public.git", pin)
    assert requests == [(expected, "https"), (expected, "https")]
