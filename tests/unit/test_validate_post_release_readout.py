"""Гранулярные тесты validate_post_release_readout (миграция из селфтеста v3.30)."""
from __future__ import annotations

import copy

import pytest

from validate_post_release_readout import (  # noqa: F401
    DEMO,
    SCHEMA,
    _load,
    check,
    json,
)


@pytest.fixture
def example_prr():
    """Пример PRR из схемы."""
    return json.loads(SCHEMA.read_text(encoding="utf-8"))["examples"][0]


@pytest.mark.unit
def test_schema_example_is_valid(example_prr):
    """Пример PRR валиден (watch, not_run downstream)."""
    assert check(example_prr) == []


@pytest.mark.unit
def test_real_readout_demo_is_consistent():
    """Реальный readout-demo целостен."""
    if DEMO.is_dir():
        for f in sorted(DEMO.glob("PRR-*.yaml")):
            assert check(_load(f)) == [], f


@pytest.mark.unit
def test_healthy_continue_with_downstream_not_run_is_error(example_prr):
    """healthy_continue при not_run downstream -> ошибка."""
    hc = copy.deepcopy(example_prr)
    hc["readout_decision"] = "healthy_continue"
    errs = check(hc)
    assert any("downstream_ci=pass" in x for x in errs), errs


@pytest.mark.unit
def test_valid_healthy_continue(example_prr):
    """healthy_continue при pass+healthy+0 promise_broken -> валиден."""
    hc = copy.deepcopy(example_prr)
    hc["downstream_ci"] = {"status": "pass", "ref": None}
    hc["product_health"] = {"band": "healthy", "score": 90}
    hc["readout_decision"] = "healthy_continue"
    assert check(hc) == []


@pytest.mark.unit
def test_sha_verified_false_is_error(example_prr):
    """sha_verified=false -> ошибка (readout только верифицированной доставки)."""
    nv = copy.deepcopy(example_prr)
    nv["delivery_receipt"]["sha_verified"] = False
    errs = check(nv)
    assert any("ВЕРИФИЦИРОВАННОЙ" in x for x in errs), errs


@pytest.mark.unit
def test_rollback_without_negative_signal_is_error(example_prr):
    """rollback без негативного сигнала -> ошибка."""
    hc = copy.deepcopy(example_prr)
    hc["downstream_ci"] = {"status": "pass", "ref": None}
    hc["product_health"] = {"band": "healthy", "score": 90}
    hc["readout_decision"] = "healthy_continue"
    rb = copy.deepcopy(hc)
    rb["readout_decision"] = "rollback"
    errs = check(rb)
    assert any("негативного сигнала" in x for x in errs), errs


@pytest.mark.unit
def test_promise_broken_with_healthy_continue_is_error(example_prr):
    """promise_broken>0 + healthy_continue -> ошибка."""
    hc = copy.deepcopy(example_prr)
    hc["downstream_ci"] = {"status": "pass", "ref": None}
    hc["product_health"] = {"band": "healthy", "score": 90}
    hc["readout_decision"] = "healthy_continue"
    pbk = copy.deepcopy(hc)
    pbk["evolution"] = {"promise_broken": 1, "cost_realized": 0}
    errs = check(pbk)
    assert any("promise_broken>0" in x for x in errs), errs


@pytest.mark.unit
def test_rollback_with_downstream_fail_is_valid(example_prr):
    """rollback при downstream=fail -> валиден."""
    rb = copy.deepcopy(example_prr)
    rb["downstream_ci"] = {"status": "fail", "ref": None}
    rb["readout_decision"] = "rollback"
    assert check(rb) == []


@pytest.mark.unit
def test_broken_id_is_error(example_prr):
    """Битый id -> ошибка."""
    errs = check({**example_prr, "id": "PRR1"})
    assert any("id должен" in x for x in errs), errs
