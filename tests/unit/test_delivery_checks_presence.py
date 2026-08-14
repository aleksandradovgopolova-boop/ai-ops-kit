"""R-41: контур доставки обязан отличать «проверок не было» от «проверки прошли».

Находка (2026-08-14): PR мог выглядеть готовым к мержу, не имея ни одного прогона, и кит этого не
видел — `pr_open` возвращал `pr_state`/`merged`, но понятия «у SHA есть проверки» не существовало.
Половину дыры закрыла защита ветки в самом ките; здесь закрыта вторая половина — та, что касается
ДОЧЕК, где настройки репозитория киту не подчиняются.

Сетевые вызовы подменяются: проверяется разбор ответа и вердикт, а не доступность GitHub.
"""
from __future__ import annotations

import pytest

import pr_open

pytestmark = pytest.mark.unit


def _fake_api(monkeypatch, check_runs=None, statuses=None, fail=False):
    """Подменить _gh_request: отдаём заранее заданные ответы двух эндпоинтов."""
    def fake(url, token, data=None, method="GET"):
        if fail:
            return None, "URLError"
        if url.endswith("/check-runs"):
            return {"check_runs": check_runs or []}, None
        if url.endswith("/status"):
            return {"statuses": statuses or []}, None
        return {}, None
    monkeypatch.setattr(pr_open, "_gh_request", fake)


class TestChecksFacts:
    """Три исхода различимы. Смешать «нет» и «не знаю» — значит завести новую ложь вместо старой."""

    def test_zero_runs_is_absent_not_success(self, monkeypatch):
        _fake_api(monkeypatch)
        res = pr_open._checks_for_sha("o", "r", "sha", "t")
        assert res["status"] == "absent", res
        assert res["total"] == 0
        assert pr_open.checks_verified(res) is False, "ноль прогонов выдан за проверенную доставку"

    def test_api_failure_is_unavailable_not_absent(self, monkeypatch):
        _fake_api(monkeypatch, fail=True)
        res = pr_open._checks_for_sha("o", "r", "sha", "t")
        assert res["status"] == "unavailable", res
        assert pr_open.checks_verified(res) is False

    def test_green_check_runs_are_verified(self, monkeypatch):
        _fake_api(monkeypatch, check_runs=[
            {"status": "completed", "conclusion": "success"},
            {"status": "completed", "conclusion": "skipped"},
        ])
        res = pr_open._checks_for_sha("o", "r", "sha", "t")
        assert (res["status"], res["total"], res["failed"], res["pending"]) == ("found", 2, 0, 0)
        assert pr_open.checks_verified(res) is True

    @pytest.mark.parametrize("runs,label", [
        pytest.param([{"status": "completed", "conclusion": "failure"}], "упавший", id="failed"),
        pytest.param([{"status": "in_progress", "conclusion": None}], "незавершённый", id="pending"),
        pytest.param([{"status": "completed", "conclusion": "timed_out"}], "по таймауту", id="timed-out"),
    ])
    def test_not_green_is_not_verified(self, monkeypatch, runs, label):
        _fake_api(monkeypatch, check_runs=runs)
        res = pr_open._checks_for_sha("o", "r", "sha", "t")
        assert pr_open.checks_verified(res) is False, f"{label} прогон засчитан как проверка"

    def test_classic_statuses_count_too(self, monkeypatch):
        """Внешний CI ставит commit statuses, а не check-runs. Иначе такая дочка выглядела бы
        как «проверок нет» — правило начало бы врать против неё."""
        _fake_api(monkeypatch, check_runs=[], statuses=[{"state": "success"}])
        res = pr_open._checks_for_sha("o", "r", "sha", "t")
        assert res["status"] == "found" and res["total"] == 1
        assert pr_open.checks_verified(res) is True

    def test_failing_classic_status_blocks_verdict(self, monkeypatch):
        _fake_api(monkeypatch, statuses=[{"state": "failure"}])
        assert pr_open.checks_verified(pr_open._checks_for_sha("o", "r", "sha", "t")) is False


class TestInvariantForbidsFabricatedVerdict:
    """Вердикт нельзя проставить мимо фактов — это инвариант, а не соглашение."""

    def test_verified_without_runs_violates_invariant(self):
        from ai_ops_kit.gates import invariants
        check = invariants.check_invariant
        assert check("INV-DELIVERY-004", checks_verified=True, checks_total=0) is False
        assert check("INV-DELIVERY-004", checks_verified=True, checks_total=None) is False
        assert check("INV-DELIVERY-004", checks_verified=True, checks_total=3) is True
        # расписка без вердикта проверок (в т.ч. старая, до R-41) инвариант не нарушает
        assert check("INV-DELIVERY-004", checks_verified=False, checks_total=0) is True
        assert check("INV-DELIVERY-004") is True
