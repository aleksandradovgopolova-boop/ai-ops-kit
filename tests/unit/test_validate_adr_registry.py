"""Гранулярные тесты validate_adr_registry (миграция из селфтеста v3.30)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from validate_adr_registry import (  # noqa: F401
    DEFAULT_DIR,
    check_registry,
    yaml,
)


def _valid_adr(aid, **over):
    d = {
        "schema_version": 1,
        "kind": "ArchitectureDecision",
        "id": aid,
        "title": "t",
        "status": "accepted",
        "context": "c",
        "decision": "d",
        "consequences": {"positive": ["p"], "negative": ["n"]},
    }
    d.update(over)
    return d


@pytest.mark.unit
def test_real_registry_is_valid():
    errs, adrs = check_registry(DEFAULT_DIR)
    assert errs == [], f"реальный decisions/adr имеет ошибки: {errs}"


@pytest.mark.unit
def test_minimal_valid_registry():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "ADR-001.yaml").write_text(yaml.safe_dump(_valid_adr("ADR-001")), encoding="utf-8")
        errs, adrs = check_registry(d)
        assert errs == [] and set(adrs) == {"ADR-001"}


@pytest.mark.unit
def test_filename_mismatch_id():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "ADR-001.yaml").write_text(yaml.safe_dump(_valid_adr("ADR-001")), encoding="utf-8")
        (d / "ADR-009.yaml").write_text(yaml.safe_dump(_valid_adr("ADR-777")), encoding="utf-8")
        errs, _ = check_registry(d)
        assert any("имя файла" in x for x in errs)


@pytest.mark.unit
def test_unidirectional_supersede():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "ADR-001.yaml").write_text(yaml.safe_dump(_valid_adr("ADR-001")), encoding="utf-8")
        (d / "ADR-002.yaml").write_text(
            yaml.safe_dump(_valid_adr("ADR-002", supersedes="ADR-001")), encoding="utf-8"
        )
        errs, _ = check_registry(d)
        assert any("несогласовано" in x for x in errs)


@pytest.mark.unit
def test_bidirectional_supersede():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "ADR-001.yaml").write_text(
            yaml.safe_dump(_valid_adr("ADR-001", status="superseded", superseded_by="ADR-002")),
            encoding="utf-8",
        )
        (d / "ADR-002.yaml").write_text(
            yaml.safe_dump(_valid_adr("ADR-002", supersedes="ADR-001")), encoding="utf-8"
        )
        errs, _ = check_registry(d)
        assert errs == []


@pytest.mark.unit
def test_dangling_related():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "ADR-001.yaml").write_text(yaml.safe_dump(_valid_adr("ADR-001")), encoding="utf-8")
        (d / "ADR-003.yaml").write_text(
            yaml.safe_dump(_valid_adr("ADR-003", related=["ADR-404"])), encoding="utf-8"
        )
        errs, _ = check_registry(d)
        assert any("related" in x for x in errs)


@pytest.mark.unit
def test_invalid_ui_impact():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "ADR-001.yaml").write_text(yaml.safe_dump(_valid_adr("ADR-001")), encoding="utf-8")
        (d / "ADR-005.yaml").write_text(
            yaml.safe_dump(_valid_adr("ADR-005", ui_impact="mega")), encoding="utf-8"
        )
        errs, _ = check_registry(d)
        assert any("UI_IMPACT" in x for x in errs)
