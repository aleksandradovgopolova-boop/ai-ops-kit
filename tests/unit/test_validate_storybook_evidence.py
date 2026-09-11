"""Granular tests for validate_storybook_evidence (migrated from selftest)."""
from __future__ import annotations

import json
import tempfile

import pytest

from validate_storybook_evidence import (  # noqa: F401
    BUILD,
    PKG,
    Path,
    SCHEMA,
    STATUS3,
    check,
    sys,
)


@pytest.fixture
def good_bundle():
    """Build a valid bundle from the real storybook adapter."""
    from ai_ops_kit.ui import storybook_adapter

    def _w(root, rel, obj):
        p = Path(root) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(obj), encoding="utf-8")

    with tempfile.TemporaryDirectory() as td:
        _w(
            td,
            "storybook-static/index.json",
            {
                "v": 5,
                "entries": {
                    "c--default": {
                        "type": "story",
                        "id": "c--default",
                        "title": "C",
                        "name": "Default",
                        "importPath": "./C.tsx",
                    },
                    "c--loading": {
                        "type": "story",
                        "id": "c--loading",
                        "title": "C",
                        "name": "Loading",
                        "importPath": "./C.tsx",
                    },
                    "c--empty": {
                        "type": "story",
                        "id": "c--empty",
                        "title": "C",
                        "name": "Empty",
                        "importPath": "./C.tsx",
                    },
                    "c--error": {
                        "type": "story",
                        "id": "c--error",
                        "title": "C",
                        "name": "Error",
                        "importPath": "./C.tsx",
                    },
                },
            },
        )
        _w(td, ".ai/ui-evidence/interaction.json", {"status": "pass", "total": 3, "passed": 3})
        _w(
            td,
            ".ai/ui-evidence/a11y.json",
            {"blocking_violations": 0, "total_violations": 1},
        )
        _w(td, ".ai/ui-evidence/visual.json", {"status": "pass", "changed": 0})
        _w(
            td,
            ".ai/ui-evidence/design-system.json",
            {
                "reused_components": ["C"],
                "new_components": [],
                "new_components_justified": True,
            },
        )
        return storybook_adapter.build_bundle(td, commit_sha="abc", changed_files=["C.tsx"])


@pytest.mark.unit
@pytest.mark.slow
class TestValidateStorybookEvidence:
    """Validation of storybook evidence bundles."""

    def test_valid_bundle_passes(self, good_bundle):
        assert check(good_bundle) == []

    def test_a11y_pass_with_blocking_violations_produces_error(self, good_bundle):
        bad_a11y = json.loads(json.dumps(good_bundle))
        bad_a11y["accessibility"] = {
            "status": "pass",
            "blocking_violations": 3,
            "total_violations": 3,
        }
        assert any("blocking_violations>0" in x for x in check(bad_a11y))

    def test_interaction_pass_with_passed_lt_total_produces_error(self, good_bundle):
        bad_inter = json.loads(json.dumps(good_bundle))
        bad_inter["interaction_tests"] = {"status": "pass", "total": 5, "passed": 3}
        assert any("passed=total" in x for x in check(bad_inter))

    def test_state_coverage_complete_with_uncovered_required_produces_error(
        self, good_bundle
    ):
        bad_sc = json.loads(json.dumps(good_bundle))
        bad_sc["state_coverage"] = {
            "required": ["default", "empty"],
            "states": {"default": True, "empty": False},
            "missing": [],
            "complete": True,
        }
        errs = check(bad_sc)
        assert any("missing несогласован" in x for x in errs) or any(
            "complete" in x for x in errs
        )

    def test_design_system_pass_with_unjustified_new_component_produces_error(
        self, good_bundle
    ):
        bad_ds = json.loads(json.dumps(good_bundle))
        bad_ds["design_system"] = {
            "status": "pass",
            "reused_components": [],
            "new_components": ["AdHoc"],
            "new_components_justified": False,
        }
        assert any("без обоснования" in x for x in check(bad_ds))

    def test_extra_key_in_section_produces_error(self, good_bundle):
        bad_key = json.loads(json.dumps(good_bundle))
        bad_key["accessibility"]["nonsense"] = 1
        assert any("лишний ключ" in x for x in check(bad_key))

    def test_wrong_kind_produces_error(self, good_bundle):
        bad_kind = json.loads(json.dumps(good_bundle))
        bad_kind["kind"] = "Nope"
        assert any("kind" in x for x in check(bad_kind))

    def test_new_component_duplicating_catalog_produces_reuse_error(self, good_bundle):
        dup = json.loads(json.dumps(good_bundle))
        dup["component_catalog"] = ["c", "button"]
        dup["design_system"] = {
            "status": "pass",
            "reused_components": [],
            "new_components": ["Button"],
            "new_components_justified": True,
        }
        assert any("reuse" in x for x in check(dup))

    def test_unique_new_component_no_reuse_error(self, good_bundle):
        dup = json.loads(json.dumps(good_bundle))
        dup["component_catalog"] = ["c", "button"]
        dup["design_system"] = {
            "status": "pass",
            "reused_components": [],
            "new_components": ["BrandNewThing"],
            "new_components_justified": True,
        }
        assert not any("reuse" in x for x in check(dup))

    def test_validator_enums_match_schema(self):
        sch = json.loads(SCHEMA.read_text(encoding="utf-8"))
        sec_enum = set(sch["properties"]["interaction_tests"]["properties"]["status"]["enum"])
        build_enum = set(sch["properties"]["storybook"]["properties"]["build_status"]["enum"])
        assert sec_enum == STATUS3
        assert build_enum == BUILD
