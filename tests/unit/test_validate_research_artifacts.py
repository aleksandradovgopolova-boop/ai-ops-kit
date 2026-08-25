"""Granular tests for validate_research_artifacts (migrated from selftest)."""
from __future__ import annotations

import pytest

from validate_research_artifacts import (  # noqa: F401
    check_freshness_and_quotes,
    check_links,
    check_schema,
    dt,
)


@pytest.fixture
def sample_data():
    rrs = {'RR-001': {}}
    evs = {
        'EV-001': {
            'request_id': 'RR-001', 'status': 'active',
            'freshness': {'volatile': True, 'expires_at': '2026-01-01'},
            'captured_at': '2026-07-23',
            'source': {'url': 'https://e', 'is_primary': True}, 'citation': {},
        },
        'EV-002': {
            'request_id': 'RR-001', 'status': 'superseded', 'superseded_by': None,
            'freshness': {'volatile': False}, 'captured_at': '2026-07-01',
            'source': {}, 'citation': {},
        },
    }
    dps = {'DP-001': {'request_id': 'RR-001', 'evidence_ids': ['EV-001'],
                      'rationale': ['опирается на EV-001 и EV-999']}}
    return rrs, evs, dps


@pytest.mark.unit
def test_superseded_without_superseded_by_detected(sample_data):
    rrs, evs, dps = sample_data
    link_errs = check_links(rrs, evs, dps)
    assert any('superseded без superseded_by' in e for e in link_errs), link_errs


@pytest.mark.unit
def test_dangling_evidence_reference_detected(sample_data):
    rrs, evs, dps = sample_data
    link_errs = check_links(rrs, evs, dps)
    assert any('EV-999' in e for e in link_errs), link_errs


@pytest.mark.unit
def test_expired_freshness_warning(sample_data):
    _, evs, _ = sample_data
    f_errs, f_warns = check_freshness_and_quotes(evs, dt.date(2026, 7, 23))
    assert any('просрочен' in w for w in f_warns), f_warns


@pytest.mark.unit
def test_missing_citation_quote_warning(sample_data):
    _, evs, _ = sample_data
    f_errs, f_warns = check_freshness_and_quotes(evs, dt.date(2026, 7, 23))
    assert any('без citation.quote' in w for w in f_warns), f_warns


@pytest.mark.unit
def test_no_freshness_errors(sample_data):
    _, evs, _ = sample_data
    f_errs, _ = check_freshness_and_quotes(evs, dt.date(2026, 7, 23))
    assert not f_errs, f_errs


@pytest.mark.unit
def test_schema_mismatch_detected():
    bad = check_schema(
        {'schema_version': 2},
        {'type': 'object',
         'properties': {'schema_version': {'const': 1}},
         'required': ['schema_version'], 'additionalProperties': False},
    )
    assert bad
