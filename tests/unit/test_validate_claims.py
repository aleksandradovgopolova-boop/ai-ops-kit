"""Гранулярные тесты validate_claims (миграция из селфтеста v3.30)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from validate_claims import (  # noqa: F401
    PKG,
    build,
    yaml,
)


@pytest.fixture
def claims_dir():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / "types.ts").write_text(
            "export enum MaterialStatus { DRAFT='DRAFT', ORDERED='ORDERED' }\n",
            encoding="utf-8",
        )
        cf = base / "claims.yaml"
        cf.write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "kind": "claims",
                    "claims": [
                        {
                            "id": "file-ok",
                            "type": "file-exists",
                            "source": {"path": "types.ts"},
                        },
                        {
                            "id": "symbol-ok",
                            "type": "symbol-exists",
                            "source": {"path": "types.ts", "symbol": "MaterialStatus"},
                        },
                        {
                            "id": "enum-ok",
                            "type": "enum-values",
                            "source": {
                                "path": "types.ts",
                                "values": ["DRAFT", "ORDERED"],
                            },
                        },
                        {
                            "id": "enum-drift",
                            "type": "enum-values",
                            "source": {
                                "path": "types.ts",
                                "values": ["DRAFT", "DELIVERED"],
                            },
                        },
                        {
                            "id": "file-drift",
                            "type": "file-exists",
                            "source": {"path": "missing.ts"},
                        },
                        {
                            "id": "count-ok",
                            "type": "count",
                            "source": {
                                "path": "types.ts",
                                "pattern": "'[A-Z]+'",
                                "expected": 2,
                            },
                        },
                        {
                            "id": "count-drift",
                            "type": "count",
                            "source": {
                                "path": "types.ts",
                                "pattern": "'[A-Z]+'",
                                "expected": 3,
                            },
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        yield cf


@pytest.fixture
def claims_results(claims_dir):
    return {r["id"]: r["status"] for r in build(claims_dir)}


@pytest.mark.unit
def test_file_exists_passes(claims_results):
    assert claims_results["file-ok"] == "ok"


@pytest.mark.unit
def test_symbol_exists_passes(claims_results):
    assert claims_results["symbol-ok"] == "ok"


@pytest.mark.unit
def test_enum_values_passes(claims_results):
    assert claims_results["enum-ok"] == "ok"


@pytest.mark.unit
def test_enum_drift_detected(claims_results):
    assert claims_results["enum-drift"] == "drift"


@pytest.mark.unit
def test_file_drift_detected(claims_results):
    assert claims_results["file-drift"] == "drift"


@pytest.mark.unit
def test_count_matches(claims_results):
    assert claims_results["count-ok"] == "ok"


@pytest.mark.unit
def test_count_drift_detected(claims_results):
    assert claims_results["count-drift"] == "drift"


@pytest.mark.unit
def test_kit_self_claims_pass():
    kit_claims = PKG / "knowledge" / "claims.yaml"
    if kit_claims.exists():
        bad = [r for r in build(kit_claims) if r["status"] != "ok"]
        assert bad == [], f"self-claims кита имеют drift: {bad}"
