"""Granular tests for validate_release_claims (migrated from selftest)."""
from __future__ import annotations

import pytest

from validate_release_claims import (  # noqa: F401
    DEFAULT,
    PKG,
    _runtime_status,
    check,
    derived_counts,
    derived_gate_counts,
    derived_verification_counts,
    mvp_gates_are_blocking,
    yaml,
)


@pytest.fixture
def base_claims():
    checks, agents = derived_counts(PKG)
    vf = (PKG / "VERSION").read_text(encoding="utf-8").strip()
    st = _runtime_status(PKG, "generic-orchestrator", "parallel_execution")
    _g, _m = derived_gate_counts()
    _vt, _vc = derived_verification_counts()
    scopes = {n: {"obtained_by": "CI", "covers": "x", "does_not_cover": "y"}
              for n in ("full-current-python", "compatibility-matrix")}
    return {
        "registry_type": "release-claims", "version": vf,
        "checks_count": checks, "agents_count": agents,
        "gates_count": _g, "mvp_blocking_count": _m,
        "validators_count": _vt, "validators_externally_tested": _vc,
        "evidence_scopes": scopes,
        "docs_must_reference_version": ["README.md"],
        "channel": "qualification",
        "channels": {
            "qualification": {"requires": ["own_ci_green"]},
            "stable": {"requires": ["own_ci_green", "field_evidence"],
                       "field_evidence_min_repos": 2},
        },
        "runtime_capabilities": [{
            "runtime": "generic-orchestrator",
            "capability": "parallel_execution", "status": st,
        }],
    }


@pytest.mark.unit
def test_consistent_claims_no_errors(base_claims):
    assert check(base_claims) == []


@pytest.mark.unit
def test_claims_without_channel_raises(base_claims):
    no_chan = {k: v for k, v in base_claims.items() if k != "channel"}
    assert check(no_chan) != []


@pytest.mark.unit
def test_stable_without_field_evidence_raises(base_claims):
    assert check({**base_claims, "channel": "stable"}) != []


@pytest.mark.unit
def test_stable_with_two_field_repos_is_valid(base_claims):
    vf = base_claims["version"]
    assert check({**base_claims, "channel": "stable",
                  "field_evidence": [{"repo": "a", "version": vf, "outcome": "ok"},
                                     {"repo": "b", "version": vf, "outcome": "ok"}]}) == []


@pytest.mark.unit
def test_version_mismatch_raises(base_claims):
    assert any("claims отстали" in x for x in check({**base_claims, "version": "0.0.0"}))


@pytest.mark.unit
def test_stale_checks_count_raises(base_claims):
    assert any("checks_count" in x for x in check({**base_claims, "checks_count": 91}))


@pytest.mark.unit
def test_stale_agents_count_raises(base_claims):
    assert any("agents_count" in x for x in check({**base_claims, "agents_count": 1}))


@pytest.mark.unit
def test_stale_gates_count_raises(base_claims):
    assert any("gates_count" in x for x in check({**base_claims, "gates_count": 999}))


@pytest.mark.unit
def test_stale_mvp_blocking_count_raises(base_claims):
    assert any("mvp_blocking_count" in x for x in check({**base_claims, "mvp_blocking_count": 999}))


@pytest.mark.unit
def test_mvp_gates_are_actually_blocking():
    assert mvp_gates_are_blocking() == []


@pytest.mark.unit
def test_stale_external_validator_coverage_raises(base_claims):
    assert any("validators_externally_tested" in x
               for x in check({**base_claims, "validators_externally_tested": 0}))


@pytest.mark.unit
def test_runtime_capability_drift_raises(base_claims):
    assert any("дрейф" in x for x in check({
        **base_claims,
        "runtime_capabilities": [{
            "runtime": "generic-orchestrator",
            "capability": "parallel_execution", "status": "unsupported",
        }],
    }))


@pytest.mark.unit
def test_forbidden_stale_marker_present_in_readme_raises(base_claims):
    assert any("устаревший маркер" in x
               for x in check({**base_claims, "forbidden_stale_markers": ["Открытая"]}))


@pytest.mark.unit
def test_forbidden_stale_marker_absent_is_ok(base_claims):
    assert not any("устаревший маркер" in x
                   for x in check({**base_claims, "forbidden_stale_markers": ["NONEXISTENT-STALE-XYZ-9999"]}))


@pytest.mark.unit
def test_readme_does_not_reference_version_raises(base_claims):
    bad_doc = {**base_claims, "version": "vNONEXISTENT-9.9.9"}
    assert any("не ссылается на текущую версию" in x for x in check(bad_doc))


@pytest.mark.unit
def test_real_release_claims_yaml_is_consistent():
    if DEFAULT.exists():
        errs = check(yaml.safe_load(DEFAULT.read_text(encoding="utf-8")))
        assert errs == [], f"real release-claims.yaml errors: {errs}"
