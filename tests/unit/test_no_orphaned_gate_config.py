"""B1: config/quality-gates.yaml is an orphaned duplicate of quality/gates.yaml (SoT).

The file must NOT exist. If recreated, the validator must detect it (fail-closed).
"""
from __future__ import annotations

import importlib
import shutil
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PKG_ROOT / "config"


def test_orphaned_gate_config_does_not_exist():
    """config/quality-gates.yaml must not exist — quality/gates.yaml is the SoT."""
    orphaned = CONFIG_DIR / "quality-gates.yaml"
    assert not orphaned.exists(), (
        "config/quality-gates.yaml is an orphaned duplicate of quality/gates.yaml (SoT). "
        "Delete it."
    )


def test_validator_detects_orphaned_gate_config(tmp_path):
    """If config/quality-gates.yaml is recreated, the validator must return non-zero.

    We copy the validator to a temp dir with a fake VERSION and config/ to test it
    in isolation from the real repo.
    """
    # Set up a fake package root
    fake_pkg = tmp_path / "pkg"
    fake_pkg.mkdir()
    (fake_pkg / "VERSION").write_text("0.0.0")

    # Copy the validator into the fake package at the same relative path
    validator_src = PKG_ROOT / "ai_ops_kit" / "validation" / "validate_ai_first_config.py"
    validator_dst = fake_pkg / "ai_ops_kit" / "validation"
    validator_dst.mkdir(parents=True)
    shutil.copy(validator_src, validator_dst / "validate_ai_first_config.py")

    # Create config dir with the orphaned file
    fake_config = fake_pkg / "config"
    fake_config.mkdir()
    (fake_config / "quality-gates.yaml").write_text("version: 1\ngates:\n  analysis: [x]\n")
    # Write required sibling configs
    (fake_config / "agents.yaml").write_text("version: 1\nagent_groups: {}\n")
    (fake_config / "model-routing.yaml").write_text(
        "version: 1\nroutes:\n  default:\n    tasks: [x]\n"
    )
    (fake_config / "tool-permissions.yaml").write_text(
        "version: 1\nmodes:\n  default:\n    allowed: []\n    denied: []\n"
    )
    (fake_config / "protected-paths.yaml").write_text(
        "version: 1\nprotected_paths:\n  - path: /x\n    approval: true\n"
    )
    # Create agents dir
    (fake_pkg / "agents").mkdir()

    # Import the validator from the fake location
    import sys
    import types

    # Load the module from the fake path
    spec = importlib.util.spec_from_file_location(
        "validate_ai_first_config_test",
        str(validator_dst / "validate_ai_first_config.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # The module resolved PKG_ROOT from VERSION — should be fake_pkg
    assert mod.CONFIG_DIR == fake_config, (
        f"Validator should use fake config dir, got {mod.CONFIG_DIR}"
    )

    # Run the validator — it must detect the orphaned file
    result = mod.main()
    assert result == 1, (
        "Validator must return non-zero when config/quality-gates.yaml exists"
    )
    assert any("quality-gates.yaml" in e for e in mod.errors), (
        "Validator error must mention the orphaned quality-gates.yaml"
    )
