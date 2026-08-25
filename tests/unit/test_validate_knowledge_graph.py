"""Granular tests for validate_knowledge_graph (migrated from selftest)."""
from __future__ import annotations

import pytest

from validate_knowledge_graph import (
    Path,
    load_dictionary,
    make_demo,
    tempfile,
    validate_graph,
)


@pytest.fixture(scope="module")
def dictionary():
    return load_dictionary()


# --- Graph validation ---

class TestGraphValidation:
    @pytest.mark.unit
    def test_valid_graph(self, dictionary):
        types, rels = dictionary
        with tempfile.TemporaryDirectory() as td:
            assert validate_graph(make_demo(Path(td) / "a"), types, rels) == []

    @pytest.mark.unit
    def test_dangling_reference_fails(self, dictionary):
        types, rels = dictionary
        with tempfile.TemporaryDirectory() as td:
            errs = validate_graph(make_demo(Path(td) / "b", dangling=True), types, rels)
            assert len(errs) > 0

    @pytest.mark.unit
    def test_invalid_relation_fails(self, dictionary):
        types, rels = dictionary
        with tempfile.TemporaryDirectory() as td:
            errs = validate_graph(make_demo(Path(td) / "c", bad_relation=True), types, rels)
            assert len(errs) > 0
