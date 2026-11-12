"""Предрелизное обновление и откат на закреплённых снимках публичных проектов."""
import json
import os
from pathlib import Path

import pytest

from ai_ops_kit.devtools import fleet_rehearsal


@pytest.mark.release_gate
@pytest.mark.slow
def test_public_projects_upgrade_and_roll_back():
    kit = Path(__file__).resolve().parents[2]
    result = fleet_rehearsal.rehearse(kit, os.environ["GITHUB_SHA"])
    assert result["status"] == "pass", json.dumps(result, ensure_ascii=False, indent=2)
