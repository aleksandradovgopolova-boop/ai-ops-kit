"""Селфтест validate_research_artifacts, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_research_artifacts import (  # noqa: F401 — имена, которые использует тело
    check_freshness_and_quotes,
    check_links,
    check_schema,
    dt,
)


@pytest.mark.slow
def test_validate_research_artifacts_selftest():
    rrs = {'RR-001': {}}
    evs = {'EV-001': {'request_id': 'RR-001', 'status': 'active',
                      'freshness': {'volatile': True, 'expires_at': '2026-01-01'},
                      'captured_at': '2026-07-23',
                      'source': {'url': 'https://e', 'is_primary': True}, 'citation': {}},
           'EV-002': {'request_id': 'RR-001', 'status': 'superseded', 'superseded_by': None,
                      'freshness': {'volatile': False}, 'captured_at': '2026-07-01',
                      'source': {}, 'citation': {}}}
    dps = {'DP-001': {'request_id': 'RR-001', 'evidence_ids': ['EV-001'],
                      'rationale': ['опирается на EV-001 и EV-999']}}
    link_errs = check_links(rrs, evs, dps)
    assert any('superseded без superseded_by' in e for e in link_errs), link_errs
    assert any('EV-999' in e for e in link_errs), link_errs
    f_errs, f_warns = check_freshness_and_quotes(evs, dt.date(2026, 7, 23))
    assert any('просрочен' in w for w in f_warns), f_warns
    assert any('без citation.quote' in w for w in f_warns), f_warns
    assert not f_errs, f_errs
    bad = check_schema({'schema_version': 2}, {'type': 'object',
                       'properties': {'schema_version': {'const': 1}},
                       'required': ['schema_version'], 'additionalProperties': False})
    assert bad
    print('SELFTEST-OK')
