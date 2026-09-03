"""Гранулярные тесты storybook_adapter (мигрировано из test_storybook_adapter_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import tempfile

import pytest

from ai_ops_kit.ui.storybook_adapter import (
    Path,
    _matches_changed,
    _write,
    build_bundle,
    evidence_for_gate,
    reuse_violations,
)


@pytest.fixture
def full_fixture_root():
    """(A) полный fixture: Storybook index + все артефакты."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write(root, "storybook-static/index.json", {"v": 5, "entries": {
            "components-metriccard--default": {"type": "story", "id": "components-metriccard--default",
                "title": "Components/MetricCard", "name": "Default", "importPath": "./src/MetricCard.tsx"},
            "components-metriccard--loading": {"type": "story", "id": "components-metriccard--loading",
                "title": "Components/MetricCard", "name": "Loading", "importPath": "./src/MetricCard.tsx"},
            "components-metriccard--error": {"type": "story", "id": "components-metriccard--error",
                "title": "Components/MetricCard", "name": "Error", "importPath": "./src/MetricCard.tsx"},
            "docs-intro": {"type": "docs", "id": "docs-intro", "title": "Intro"}}})
        _write(root, ".ai/ui-evidence/interaction.json", {"status": "pass", "total": 5, "passed": 5})
        _write(root, ".ai/ui-evidence/a11y.json", {"blocking_violations": 0, "total_violations": 2})
        _write(root, ".ai/ui-evidence/visual.json", {"status": "pass", "changed": 0})
        _write(root, ".ai/ui-evidence/design-system.json",
               {"reused_components": ["MetricCard"], "new_components": ["DashboardViewport"],
                "new_components_justified": True})
        yield root


@pytest.mark.unit
class TestFullFixture:
    def test_storybook_detected_and_build_pass(self, full_fixture_root):
        b = build_bundle(full_fixture_root, commit_sha="abc1234", changed_files=["src/MetricCard.tsx"])
        assert b["storybook"]["detected"]
        assert b["storybook"]["build_status"] == "pass"
        assert b["storybook"]["story_count"] == 3

    def test_affected_component_from_changed_import_path(self, full_fixture_root):
        b = build_bundle(full_fixture_root, commit_sha="abc1234", changed_files=["src/MetricCard.tsx"])
        assert b["affected_components"] == ["Components/MetricCard"]

    def test_state_coverage_incomplete_missing_empty(self, full_fixture_root):
        b = build_bundle(full_fixture_root, commit_sha="abc1234", changed_files=["src/MetricCard.tsx"])
        assert b["state_coverage"]["states"]["default"]
        assert b["state_coverage"]["states"]["error"]
        assert not b["state_coverage"]["states"]["empty"]
        assert b["state_coverage"]["missing"] == ["empty"]
        assert b["state_coverage"]["complete"] is False

    def test_interaction_pass(self, full_fixture_root):
        b = build_bundle(full_fixture_root, commit_sha="abc1234", changed_files=["src/MetricCard.tsx"])
        assert b["interaction_tests"] == {"status": "pass", "total": 5, "passed": 5}

    def test_a11y_zero_blocking_pass(self, full_fixture_root):
        b = build_bundle(full_fixture_root, commit_sha="abc1234", changed_files=["src/MetricCard.tsx"])
        assert b["accessibility"]["status"] == "pass"
        assert b["accessibility"]["blocking_violations"] == 0

    def test_design_system_new_component_justified(self, full_fixture_root):
        b = build_bundle(full_fixture_root, commit_sha="abc1234", changed_files=["src/MetricCard.tsx"])
        assert b["design_system"]["status"] == "pass"
        assert b["design_system"]["new_components"] == ["DashboardViewport"]

    def test_provenance_lists_artifacts(self, full_fixture_root):
        b = build_bundle(full_fixture_root, commit_sha="abc1234", changed_files=["src/MetricCard.tsx"])
        assert len(b["generated_from"]) >= 4


@pytest.mark.unit
class TestEvidenceForGate:
    def test_visual_deterministic_pass(self, full_fixture_root):
        b = build_bundle(full_fixture_root, commit_sha="abc1234", changed_files=["src/MetricCard.tsx"])
        eg = evidence_for_gate(b)
        assert eg["visual_regression"]["deterministic_status"] == "pass"
        assert eg["visual_regression"]["residual_review"] is False

    def test_accessibility_auto_pass_but_residual_review(self, full_fixture_root):
        b = build_bundle(full_fixture_root, commit_sha="abc1234", changed_files=["src/MetricCard.tsx"])
        eg = evidence_for_gate(b)
        assert eg["accessibility_review"]["deterministic_status"] == "pass"
        assert eg["accessibility_review"]["residual_review"] is True

    def test_ux_not_closed_deterministically(self, full_fixture_root):
        b = build_bundle(full_fixture_root, commit_sha="abc1234", changed_files=["src/MetricCard.tsx"])
        eg = evidence_for_gate(b)
        assert eg["ux_review"]["deterministic_status"] == "fail"


@pytest.mark.unit
class TestNoArtifacts:
    def test_no_storybook_detected_absent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            b = build_bundle(root, commit_sha=None)
            assert b["storybook"]["detected"] is False
            assert b["storybook"]["build_status"] == "absent"

    def test_no_artifacts_all_not_run(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            b = build_bundle(root, commit_sha=None)
            assert b["interaction_tests"]["status"] == "not_run"
            assert b["accessibility"]["status"] == "not_run"
            assert b["visual_regression"]["status"] == "not_run"
            assert b["design_system"]["status"] == "not_run"

    def test_evidence_for_gate_empty_all_not_run(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            b = build_bundle(root, commit_sha=None)
            eg = evidence_for_gate(b)
            assert all(v["deterministic_status"] == "not_run" for v in eg.values())


@pytest.mark.unit
class TestRawFormats:
    def test_storybook_config_without_index_build_fail(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root, ".storybook/main.js", {})
            _write(root, "test-results/vitest.json",
                   {"numTotalTests": 4, "numFailedTests": 1, "numPassedTests": 3})
            _write(root, "test-results/axe.json",
                   {"violations": [{"impact": "critical"}, {"impact": "minor"}, {"impact": "serious"}]})
            _write(root, "test-results/visual.json", {"changed": 2})
            b = build_bundle(root)
            assert b["storybook"]["build_status"] == "fail"

    def test_vitest_raw_fail(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root, ".storybook/main.js", {})
            _write(root, "test-results/vitest.json",
                   {"numTotalTests": 4, "numFailedTests": 1, "numPassedTests": 3})
            _write(root, "test-results/axe.json",
                   {"violations": [{"impact": "critical"}, {"impact": "minor"}, {"impact": "serious"}]})
            _write(root, "test-results/visual.json", {"changed": 2})
            b = build_bundle(root)
            assert b["interaction_tests"] == {"status": "fail", "total": 4, "passed": 3}

    def test_axe_raw_blocking(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root, ".storybook/main.js", {})
            _write(root, "test-results/vitest.json",
                   {"numTotalTests": 4, "numFailedTests": 1, "numPassedTests": 3})
            _write(root, "test-results/axe.json",
                   {"violations": [{"impact": "critical"}, {"impact": "minor"}, {"impact": "serious"}]})
            _write(root, "test-results/visual.json", {"changed": 2})
            b = build_bundle(root)
            assert b["accessibility"]["status"] == "fail"
            assert b["accessibility"]["blocking_violations"] == 2
            assert b["accessibility"]["total_violations"] == 3

    def test_visual_changed_fail(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root, ".storybook/main.js", {})
            _write(root, "test-results/vitest.json",
                   {"numTotalTests": 4, "numFailedTests": 1, "numPassedTests": 3})
            _write(root, "test-results/axe.json",
                   {"violations": [{"impact": "critical"}, {"impact": "minor"}, {"impact": "serious"}]})
            _write(root, "test-results/visual.json", {"changed": 2})
            b = build_bundle(root)
            assert b["visual_regression"] == {"status": "fail", "changed": 2}


@pytest.mark.unit
class TestDesignSystemUnjustified:
    def test_new_component_without_justification_fail(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root, ".ai/ui-evidence/design-system.json",
                   {"reused_components": [], "new_components": ["AdHocButton"],
                    "new_components_justified": False})
            b = build_bundle(root)
            assert b["design_system"]["status"] == "fail"


@pytest.mark.unit
class TestExactShaBinding:
    @pytest.fixture
    def old_evidence_root(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root, ".ai/ui-evidence/meta.json", {"commit_sha": "OLDSHA"})
            _write(root, "storybook-static/index.json", {"v": 5, "entries": {
                "c--default": {"type": "story", "id": "c--default", "title": "C", "name": "Default",
                               "importPath": "./src/Card.tsx"},
                "c--loading": {"type": "story", "id": "c--loading", "title": "C", "name": "Loading",
                               "importPath": "./src/Card.tsx"},
                "c--empty": {"type": "story", "id": "c--empty", "title": "C", "name": "Empty",
                             "importPath": "./src/Card.tsx"},
                "c--error": {"type": "story", "id": "c--error", "title": "C", "name": "Error",
                             "importPath": "./src/Card.tsx"}}})
            _write(root, ".ai/ui-evidence/interaction.json", {"status": "pass", "total": 2, "passed": 2})
            _write(root, ".ai/ui-evidence/a11y.json", {"blocking_violations": 0})
            _write(root, ".ai/ui-evidence/visual.json", {"status": "pass", "changed": 0})
            yield root

    def test_commit_sha_from_meta(self, old_evidence_root):
        b = build_bundle(old_evidence_root, changed_files=["src/Card.tsx"])
        assert b["commit_sha"] == "OLDSHA"

    def test_old_evidence_new_commit_all_not_run(self, old_evidence_root):
        b = build_bundle(old_evidence_root, changed_files=["src/Card.tsx"])
        eg = evidence_for_gate(b, expected_sha="NEWSHA")
        assert all(v["deterministic_status"] == "not_run" and v.get("unbound") for v in eg.values())

    def test_matching_sha_evidence_applied(self, old_evidence_root):
        b = build_bundle(old_evidence_root, changed_files=["src/Card.tsx"])
        eg = evidence_for_gate(b, expected_sha="OLDSHA")
        assert eg["visual_regression"]["deterministic_status"] == "pass"

    def test_no_expected_sha_no_binding(self, old_evidence_root):
        b = build_bundle(old_evidence_root, changed_files=["src/Card.tsx"])
        assert evidence_for_gate(b)["visual_regression"]["deterministic_status"] == "pass"


@pytest.mark.unit
class TestScoping:
    def test_other_component_stories_not_affected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root, ".ai/ui-evidence/meta.json", {"commit_sha": "SHA1"})
            _write(root, "storybook-static/index.json", {"v": 5, "entries": {
                "a--default": {"type": "story", "id": "a--default", "title": "A", "name": "Default",
                               "importPath": "./src/features/Widget.tsx"},
                "a--loading": {"type": "story", "id": "a--loading", "title": "A", "name": "Loading",
                               "importPath": "./src/features/Widget.tsx"},
                "a--empty": {"type": "story", "id": "a--empty", "title": "A", "name": "Empty",
                             "importPath": "./src/features/Widget.tsx"},
                "a--error": {"type": "story", "id": "a--error", "title": "A", "name": "Error",
                             "importPath": "./src/features/Widget.tsx"}}})
            _write(root, ".ai/ui-evidence/interaction.json", {"status": "pass", "total": 4, "passed": 4})
            b = build_bundle(root, changed_files=["src/admin/Panel.tsx"])
            assert b["affected_stories"] == []
            assert b["affected_components"] == []

    def test_ux_not_closed_without_affected_stories(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root, ".ai/ui-evidence/meta.json", {"commit_sha": "SHA1"})
            _write(root, "storybook-static/index.json", {"v": 5, "entries": {
                "a--default": {"type": "story", "id": "a--default", "title": "A", "name": "Default",
                               "importPath": "./src/features/Widget.tsx"},
                "a--loading": {"type": "story", "id": "a--loading", "title": "A", "name": "Loading",
                               "importPath": "./src/features/Widget.tsx"},
                "a--empty": {"type": "story", "id": "a--empty", "title": "A", "name": "Empty",
                             "importPath": "./src/features/Widget.tsx"},
                "a--error": {"type": "story", "id": "a--error", "title": "A", "name": "Error",
                             "importPath": "./src/features/Widget.tsx"}}})
            _write(root, ".ai/ui-evidence/interaction.json", {"status": "pass", "total": 4, "passed": 4})
            b = build_bundle(root, changed_files=["src/admin/Panel.tsx"])
            eg = evidence_for_gate(b, expected_sha="SHA1")
            assert eg["ux_review"]["deterministic_status"] != "pass"

    def test_suffix_match_not_bare_basename(self):
        assert _matches_changed("./a/Card.tsx", ["b/Card.tsx"]) is False
        assert _matches_changed("./src/Card.tsx", ["src/Card.tsx"]) is True


@pytest.mark.unit
class TestComponentReuse:
    def test_catalog_from_all_index_components(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root, "storybook-static/index.json", {"v": 5, "entries": {
                "components-metriccard--default": {"type": "story", "id": "components-metriccard--default",
                    "title": "Components/MetricCard", "name": "Default", "importPath": "./src/MetricCard.tsx"},
                "components-button--default": {"type": "story", "id": "components-button--default",
                    "title": "Components/Button", "name": "Default", "importPath": "./src/Button.tsx"}}})
            _write(root, ".ai/ui-evidence/design-system.json",
                   {"reused_components": [], "new_components": ["Button"], "new_components_justified": True})
            b = build_bundle(root)
            assert set(b["component_catalog"]) == {"metriccard", "button"}

    def test_reuse_violations_duplicate_catalog(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root, "storybook-static/index.json", {"v": 5, "entries": {
                "components-metriccard--default": {"type": "story", "id": "components-metriccard--default",
                    "title": "Components/MetricCard", "name": "Default", "importPath": "./src/MetricCard.tsx"},
                "components-button--default": {"type": "story", "id": "components-button--default",
                    "title": "Components/Button", "name": "Default", "importPath": "./src/Button.tsx"}}})
            _write(root, ".ai/ui-evidence/design-system.json",
                   {"reused_components": [], "new_components": ["Button"], "new_components_justified": True})
            b = build_bundle(root)
            assert reuse_violations(b) == ["Button"]

    def test_unique_new_component_no_violation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root, "storybook-static/index.json", {"v": 5, "entries": {
                "components-metriccard--default": {"type": "story", "id": "components-metriccard--default",
                    "title": "Components/MetricCard", "name": "Default", "importPath": "./src/MetricCard.tsx"},
                "components-button--default": {"type": "story", "id": "components-button--default",
                    "title": "Components/Button", "name": "Default", "importPath": "./src/Button.tsx"}}})
            _write(root, ".ai/ui-evidence/design-system.json",
                   {"reused_components": ["Button"], "new_components": ["DashboardViewport"],
                    "new_components_justified": True})
            b = build_bundle(root)
            assert reuse_violations(b) == []
