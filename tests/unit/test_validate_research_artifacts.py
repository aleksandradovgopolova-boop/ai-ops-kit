"""Granular tests for validate_research_artifacts (migrated from selftest)."""
from __future__ import annotations

import pytest

from validate_research_artifacts import (  # noqa: F401
    check_evidence_currency,
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


@pytest.fixture
def currency_data():
    """EV-660 -> EV-673 -> EV-1170: цепочка supersession, как в .research (свип 2026-09-22)."""
    evs = {
        'EV-660': {'status': 'superseded', 'superseded_by': 'EV-673'},
        'EV-673': {'status': 'superseded', 'superseded_by': 'EV-1170'},
        'EV-1170': {'status': 'active', 'superseded_by': None},
        'EV-672': {'status': 'stale', 'superseded_by': None},
    }
    return evs


@pytest.mark.unit
def test_draft_dp_on_superseded_evidence_is_error(currency_data):
    dps = {'DP-101': {'status': 'draft', 'evidence_ids': ['EV-660']}}
    errs, warns = check_evidence_currency(currency_data, dps)
    assert any('EV-660' in e and 'superseded' in e for e in errs), (errs, warns)
    assert not warns, warns


@pytest.mark.unit
def test_closed_dp_on_superseded_evidence_is_warning_not_error(currency_data):
    """Принятое решение — снимок своей даты: задним числом красным его красить нельзя."""
    dps = {'DP-108': {'status': 'accepted', 'evidence_ids': ['EV-660']}}
    errs, warns = check_evidence_currency(currency_data, dps)
    assert not errs, errs
    assert any('EV-660' in w for w in warns), warns


@pytest.mark.unit
def test_message_names_newest_successor_not_middle_of_chain(currency_data):
    """Ссылаться на середину цепочки так же неверно, как на её начало."""
    dps = {'DP-101': {'status': 'draft', 'evidence_ids': ['EV-660']}}
    errs, _ = check_evidence_currency(currency_data, dps)
    assert 'EV-1170' in errs[0], errs
    assert 'EV-673' not in errs[0], errs


@pytest.mark.unit
def test_stale_evidence_caught_without_successor(currency_data):
    dps = {'DP-113': {'status': 'draft', 'evidence_ids': ['EV-672']}}
    errs, _ = check_evidence_currency(currency_data, dps)
    assert any('EV-672' in e and 'stale' in e for e in errs), errs
    assert 'актуальная запись' not in errs[0], errs


@pytest.mark.unit
def test_active_evidence_is_silent(currency_data):
    dps = {'DP-999': {'status': 'draft', 'evidence_ids': ['EV-1170']}}
    assert check_evidence_currency(currency_data, dps) == ([], [])


@pytest.mark.unit
def test_dangling_id_left_to_check_links(currency_data):
    """Несуществующий id — не дело этой проверки; дублировать ошибку не надо."""
    dps = {'DP-999': {'status': 'draft', 'evidence_ids': ['EV-000']}}
    assert check_evidence_currency(currency_data, dps) == ([], [])


@pytest.mark.unit
def test_supersession_cycle_does_not_hang():
    """Битые данные (A->B->A) не должны вешать валидатор."""
    evs = {'EV-001': {'status': 'superseded', 'superseded_by': 'EV-002'},
           'EV-002': {'status': 'superseded', 'superseded_by': 'EV-001'}}
    dps = {'DP-001': {'status': 'draft', 'evidence_ids': ['EV-001']}}
    errs, _ = check_evidence_currency(evs, dps)
    assert len(errs) == 1 and 'EV-001' in errs[0], errs


@pytest.mark.unit
def test_schema_mismatch_detected():
    bad = check_schema(
        {'schema_version': 2},
        {'type': 'object',
         'properties': {'schema_version': {'const': 1}},
         'required': ['schema_version'], 'additionalProperties': False},
    )
    assert bad
