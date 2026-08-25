"""B4: Invariant claims honest — docs don't claim runtime enforcement for invariants.

The invariant catalog (docs/api/invariants.md) must:
1. Reference the real path (ai_ops_kit/gates/invariants.py, not tools/invariants.py)
2. State that checks are synthetic (not runtime-enforced)
3. Use package imports (from ai_ops_kit.gates.invariants), not flat imports
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2]
INV_DOC = PKG / "docs" / "api" / "invariants.md"


@pytest.mark.unit
def test_invariants_doc_references_real_path():
    """Doc must not reference tools/invariants.py (phantom path)."""
    text = INV_DOC.read_text(encoding="utf-8")
    assert "tools/invariants.py" not in text, (
        "docs/api/invariants.md references phantom tools/invariants.py; "
        "real path is ai_ops_kit/gates/invariants.py"
    )


@pytest.mark.unit
def test_invariants_doc_states_synthetic_check():
    """Doc must state that invariants are checked on synthetic data, not runtime."""
    text = INV_DOC.read_text(encoding="utf-8")
    assert "синтетич" in text.lower() or "synthetic" in text.lower(), (
        "docs/api/invariants.md must state checks are synthetic (not runtime-enforced)"
    )


@pytest.mark.unit
def test_invariants_doc_uses_package_import():
    """Usage example must use package import, not flat import."""
    text = INV_DOC.read_text(encoding="utf-8")
    assert "from invariants import" not in text, (
        "docs/api/invariants.md uses flat import 'from invariants import'; "
        "must use 'from ai_ops_kit.gates.invariants import'"
    )
    assert "ai_ops_kit.gates.invariants" in text
