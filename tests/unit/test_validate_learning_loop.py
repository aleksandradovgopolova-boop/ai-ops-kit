"""Granular tests for validate_learning_loop (migrated from selftest)."""
from __future__ import annotations

import tempfile

import pytest

from validate_learning_loop import (
    Path,
    adrreg,
    check_loop,
    flreg,
    yaml,
)


def _adr(aid):
    return {"schema_version": 1, "kind": "ArchitectureDecision", "id": aid, "title": "t",
            "status": "accepted", "context": "c", "decision": "d",
            "consequences": {"positive": ["p"], "negative": ["n"]}}


def _fl(fid, follow_up):
    return {"schema_version": 1, "kind": "FeatureLearning", "id": fid, "feature": "feature:x",
            "hypothesis": "h",
            "validation": {"method": "m", "status": "done", "result": "r"},
            "outcome": {"verdict": "confirmed", "expected": "e", "actual": "a"},
            "follow_up": follow_up, "status": "validated"}


# --- Real registry ---

class TestRealRegistry:
    @pytest.mark.slow
    @pytest.mark.unit
    def test_real_loop_is_consistent(self):
        real_errs, real_stats = check_loop(flreg.DEFAULT_DIR, adrreg.DEFAULT_DIR)
        assert real_errs == [], f"resolved={real_stats.get('adr_refs_resolved')}"


# --- Loop checks with temp dirs ---

class TestLoopChecks:
    @pytest.mark.unit
    def test_follow_up_adr_resolves(self):
        with tempfile.TemporaryDirectory() as ad, tempfile.TemporaryDirectory() as fd:
            adp, flp = Path(ad), Path(fd)
            (adp / "ADR-001.yaml").write_text(yaml.safe_dump(_adr("ADR-001")), encoding="utf-8")
            (flp / "FL-001.yaml").write_text(yaml.safe_dump(_fl("FL-001", ["ADR-001"])), encoding="utf-8")
            e, s = check_loop(flp, adp)
            assert e == []
            assert s["adr_refs_resolved"] == 1

    @pytest.mark.unit
    def test_dangling_adr_reference_breaks_loop(self):
        with tempfile.TemporaryDirectory() as ad, tempfile.TemporaryDirectory() as fd:
            adp, flp = Path(ad), Path(fd)
            (adp / "ADR-001.yaml").write_text(yaml.safe_dump(_adr("ADR-001")), encoding="utf-8")
            (flp / "FL-002.yaml").write_text(yaml.safe_dump(_fl("FL-002", ["ADR-404"])), encoding="utf-8")
            e, _ = check_loop(flp, adp)
            assert any("ADR-404" in x for x in e)

    @pytest.mark.unit
    def test_weak_references_do_not_break_loop(self):
        with tempfile.TemporaryDirectory() as ad, tempfile.TemporaryDirectory() as fd:
            adp, flp = Path(ad), Path(fd)
            (adp / "ADR-001.yaml").write_text(yaml.safe_dump(_adr("ADR-001")), encoding="utf-8")
            (flp / "FL-003.yaml").write_text(
                yaml.safe_dump(_fl("FL-003", ["RR-008", "DP-108", "feature:checkout"])), encoding="utf-8")
            e, _ = check_loop(flp, adp)
            assert e == []

    @pytest.mark.unit
    def test_broken_adr_registry_reports_fix(self):
        with tempfile.TemporaryDirectory() as ad, tempfile.TemporaryDirectory() as fd:
            adp, flp = Path(ad), Path(fd)
            (adp / "ADR-001.yaml").write_text(yaml.safe_dump(_adr("ADR-001")), encoding="utf-8")
            (flp / "FL-003.yaml").write_text(
                yaml.safe_dump(_fl("FL-003", ["RR-008", "DP-108", "feature:checkout"])), encoding="utf-8")
            (adp / "ADR-777.yaml").write_text(
                yaml.safe_dump({**_adr("ADR-001"), "id": "ADR-999"}), encoding="utf-8")
            e, _ = check_loop(flp, adp)
            assert any("ADR-реестр невалиден" in x for x in e)
