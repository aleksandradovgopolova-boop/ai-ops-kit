"""Гранулярные тесты data_classification (мигрировано из test_data_classification_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import pytest

from data_classification import (
    DEMO,
    _load,
    _policy_class,
    classify,
    validate_policy,
)


@pytest.fixture
def policy():
    return {"schema_version": 1, "kind": "DataClassificationPolicy", "id": "DCP-001",
            "default_class": "internal", "strict_unknown": False,
            "rules": [{"path_prefix": "secrets/", "class": "secret"},
                      {"path_prefix": "src/private/", "class": "confidential"}]}


@pytest.mark.unit
class TestClassifyMarkers:
    def test_public_marker_does_not_lower(self):
        assert classify("# data-class: public\nx=1\n") == "internal"

    def test_confidential_marker_raises(self):
        assert classify("# data-class: confidential\nx=1\n") == "confidential"

    def test_secret_always_secret(self):
        assert classify("# data-class: public\nsk-ant-api03deadbeefcafe\n") == "secret"


@pytest.mark.unit
class TestClassifyWithPolicy:
    def test_secrets_path_is_secret(self, policy):
        assert classify("y=1\n", "secrets/x.py", policy) == "secret"

    def test_private_path_is_confidential(self, policy):
        assert classify("y=1\n", "src/private/x.py", policy) == "confidential"

    def test_public_marker_does_not_lower_on_confidential_path(self, policy):
        assert classify("# data-class: public\n", "src/private/x.py", policy) == "confidential"

    def test_longest_prefix_wins(self):
        pol = {"rules": [{"path_prefix": "src/", "class": "internal"},
                         {"path_prefix": "src/private/", "class": "confidential"}]}
        assert _policy_class(pol, "src/private/a.py") == "confidential"

    def test_strict_unknown_is_confidential(self, policy):
        assert classify("x=1\n", "weird/x.py", policy, strict=True) == "confidential"

    def test_non_strict_unknown_is_internal(self, policy):
        assert classify("x=1\n", "weird/x.py", policy) == "internal"


@pytest.mark.unit
class TestValidatePolicy:
    def test_valid_policy_passes(self, policy):
        assert validate_policy(policy) == []

    def test_bad_class_in_rule(self, policy):
        assert any("class" in x for x in validate_policy({**policy, "rules": [{"path_prefix": "a/", "class": "vibes"}]}))

    def test_bad_default_class(self, policy):
        assert any("default_class" in x for x in validate_policy({**policy, "default_class": "x"}))

    def test_real_demo_dcp_valid(self):
        if DEMO.is_dir():
            assert all(validate_policy(_load(f)) == [] for f in sorted(DEMO.glob("DCP-*.yaml")))
