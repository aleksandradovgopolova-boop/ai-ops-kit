"""ROID: стоимость прогона привязана к РЕАЛЬНОМУ ИСХОДУ через cost_account (P1, аудит 10 ролей).

НАХОДКА АУДИТА. `providers/cost_account.cost_per_successful_change` считал стоимость одного успешно
ПРОВЕРЕННОГО изменения, но модуль был дормантным (0 не-тестовых импортёров): экономика мерилась в
вакууме, не против того, ДОСТИГ ли прогон цели. Проводка: `engine/ai_ops_run_lifecycle._finalize_run_cost`
переиспользует ту же чистую функцию с фактическими данными прогона и кладёт результат в `rep["roid"]`.

Три грани capability:
  * успешное изменение (ready_for_pr=True) -> cost_per_successful_change = число (стоимость прогона);
  * неуспешное (ready_for_pr=False) -> честное «нет успешного изменения» (cost_per_change=None),
    без деления на ноль (стоимость есть, успешных изменений нет — это потери, а не «дёшево»);
  * cost_account теперь ПРОВЕДЁН в контур — его импортирует рабочий код (не дормант).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from ai_ops_kit.engine.ai_ops_run_lifecycle import _finalize_run_cost


class _FakeOrchestrator:
    """Минимальный оркестратор: отдаёт заранее заданные call-stats, очистка контекста — no-op."""

    def __init__(self, stats):
        self._stats = stats

    def drain_call_stats(self):
        return self._stats

    def clear_call_context(self):
        return None


def _finalize(tmp_path, *, ready_for_pr, cost_usd_est):
    """Прогнать _finalize_run_cost с одним замеренным вызовом и заданным исходом -> rep."""
    rep = {"ready_for_pr": ready_for_pr}
    stats = [{"input_tokens": 1000, "output_tokens": 500, "latency_s": 4.2,
              "cost_usd_est": cost_usd_est}]
    _finalize_run_cost(
        rep, _FakeOrchestrator(stats), model="claude-x",
        jname=tmp_path / "lifecycle-journal.jsonl", fid="wi-1", attempt_id="a1",
        signals={"task_type": "feature"}, plan={"base_workflow": "standard"},
        model_resolution={}, child_root=tmp_path)
    return rep


def test_report_carries_roid_computed_by_cost_account(tmp_path):
    """Отчёт прогона несёт roid, посчитанный cost_account из фактической стоимости+исхода."""
    rep = _finalize(tmp_path, ready_for_pr=True, cost_usd_est=0.30)
    assert "roid" in rep, "отчёт прогона обязан нести секцию roid"
    roid = rep["roid"]
    # Ровно то, что вернула бы чистая cost_account на тех же данных (переиспользование, не копия).
    from ai_ops_kit.providers import cost_account
    expected = cost_account.cost_per_successful_change(
        {"calls_cost": 0.30, "latency_s": 4.2, "delivered_verified": True})
    assert roid["cost_per_successful_change"] == expected["cost_per_change"]
    assert roid["total_cost"] == expected["total_cost"] == pytest.approx(0.30)
    assert roid["delivered_verified"] is True


def test_successful_change_yields_a_number(tmp_path):
    """Успешное проверенное изменение -> cost_per_successful_change = число (стоимость прогона)."""
    rep = _finalize(tmp_path, ready_for_pr=True, cost_usd_est=0.42)
    assert rep["roid"]["cost_per_successful_change"] == pytest.approx(0.42)
    assert rep["roid"]["delivered_verified"] is True


def test_unsuccessful_change_is_honest_not_divide_by_zero(tmp_path):
    """Неуспех -> честное «нет успешного изменения» (None), стоимость видна, деления на ноль нет."""
    rep = _finalize(tmp_path, ready_for_pr=False, cost_usd_est=0.42)
    roid = rep["roid"]
    assert roid["cost_per_successful_change"] is None, \
        "без успешного проверенного изменения cost_per_change обязан быть None, а не 0/деление"
    assert roid["total_cost"] == pytest.approx(0.42), "стоимость есть даже при неуспехе (это потери)"
    assert roid["delivered_verified"] is False
    assert "нет успешного" in roid["note"], "исход неуспеха обязан быть назван честно"


def test_cost_unknown_does_not_crash(tmp_path):
    """Провайдер не вернул стоимость (cost_usd_est=None) -> roid считается без падения."""
    rep = _finalize(tmp_path, ready_for_pr=True, cost_usd_est=None)
    # cost_account трактует отсутствие стоимости как 0 (total_cost=0), исход при этом честен.
    assert rep["roid"]["delivered_verified"] is True
    assert rep["roid"]["total_cost"] == 0


def _load_dormant_module():
    path = Path(__file__).resolve().parents[1] / "contracts" / "test_dormant_inventory.py"
    spec = importlib.util.spec_from_file_location("_dormant_inventory_probe", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_cost_account_is_wired_no_longer_dormant():
    """cost_account проведён в контур: рабочий код его импортирует, и он ушёл из KNOWN_DORMANT."""
    tdi = _load_dormant_module()
    name = "ai_ops_kit.providers.cost_account"
    importers = tdi._nontest_importers(tdi._pkg_modules())
    assert importers[name], \
        "cost_account обязан иметь хотя бы один не-тестовый импортёр (проведён в контур прогона)"
    assert name not in tdi.KNOWN_DORMANT, "проведённый в контур модуль обязан уйти из KNOWN_DORMANT"
    assert name not in tdi._dormant_now(), "cost_account больше не должен числиться дормантным"
