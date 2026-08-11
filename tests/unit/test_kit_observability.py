"""Unit tests for tools/kit_observability.py (v3.28.0 R13)."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT / "tools"))

import kit_observability  # noqa: E402
import usage_ledger  # noqa: E402

pytestmark = [pytest.mark.unit]


@pytest.fixture
def empty_child(tmp_path):
    return str(tmp_path / "child")


@pytest.fixture
def populated_child(tmp_path):
    root = tmp_path / "child"
    root.mkdir()
    (root / ".ai" / "usage").mkdir(parents=True)
    (root / "features" / "wid-1").mkdir(parents=True)
    (root / "features" / "wid-2").mkdir(parents=True)

    # Usage records
    records = [
        {"run_id": "r1", "role": "implementation", "provider": "openai-compatible",
         "model": "deepseek-chat", "input_tokens": 1000, "output_tokens": 500,
         "usage_status": "measured", "cost": 0.05, "cost_status": "measured",
         "latency": 2.0, "trigger": "initial"},
        {"run_id": "r1", "role": "review", "provider": "openai-compatible",
         "model": "deepseek-chat", "input_tokens": 200, "output_tokens": 100,
         "usage_status": "measured", "cost": 0.01, "cost_status": "measured",
         "latency": 1.0, "trigger": "review"},
    ]
    usage_ledger.append(str(root), "wid-1", records, run_id="r1")

    # Workitems
    (root / "features" / "wid-1" / "workitem.yaml").write_text(
        yaml.dump({"id": "wid-1", "status": "done", "lifecycle_intent": "delivery",
                   "workflow": "ENGINEERING"}))
    (root / "features" / "wid-2" / "workitem.yaml").write_text(
        yaml.dump({"id": "wid-2", "status": "draft", "lifecycle_intent": "discovery",
                   "workflow": "QUICK"}))

    # Delivery receipt
    (root / "features" / "wid-1" / "delivery-outbox").mkdir(parents=True, exist_ok=True)
    (root / "features" / "wid-1" / "delivery-outbox" / "d1.receipt.yaml").write_text(
        yaml.dump({"kind": "DeliveryReceipt", "delivery_id": "d1", "status": "reconciled",
                   "sha_verified": True, "merged": True}))

    return str(root)


class TestEmptyChild:
    """Empty child repo — honest 'no data'."""

    def test_has_data_false(self, empty_child):
        r = kit_observability.compute(empty_child)
        assert r["kit"]["has_data"] is False

    def test_zero_costs(self, empty_child):
        r = kit_observability.compute(empty_child)
        assert r["cost"]["total_cost_usd"] == 0.0
        assert r["cost"]["total_calls"] == 0

    def test_zero_workitems(self, empty_child):
        r = kit_observability.compute(empty_child)
        assert r["workitems"]["total"] == 0

    def test_zero_delivery(self, empty_child):
        r = kit_observability.compute(empty_child)
        assert r["delivery"]["total"] == 0

    def test_no_avg_when_no_calls(self, empty_child):
        r = kit_observability.compute(empty_child)
        assert "avg_cost_per_call" not in r["cost"]

    def test_text_says_no_data(self, empty_child):
        r = kit_observability.compute(empty_child)
        text = kit_observability.format_text(r)
        assert "Нет данных" in text


class TestPopulatedChild:
    """Populated child repo — metrics computed correctly."""

    def test_has_data_true(self, populated_child):
        r = kit_observability.compute(populated_child)
        assert r["kit"]["has_data"] is True

    def test_cost_aggregated(self, populated_child):
        r = kit_observability.compute(populated_child)
        assert r["cost"]["total_calls"] == 2
        assert r["cost"]["total_cost_usd"] > 0

    def test_workitems_counted(self, populated_child):
        r = kit_observability.compute(populated_child)
        assert r["workitems"]["total"] == 2

    def test_workitem_statuses(self, populated_child):
        r = kit_observability.compute(populated_child)
        assert r["workitems"]["by_status"]["done"] == 1
        assert r["workitems"]["by_status"]["draft"] == 1

    def test_delivery_counted(self, populated_child):
        r = kit_observability.compute(populated_child)
        assert r["delivery"]["total"] == 1
        assert r["delivery"]["sha_verified"] == 1
        assert r["delivery"]["merged"] == 1

    def test_success_rate(self, populated_child):
        r = kit_observability.compute(populated_child)
        assert r["delivery"]["success_rate"] == 1.0

    def test_avg_cost_per_call(self, populated_child):
        r = kit_observability.compute(populated_child)
        assert "avg_cost_per_call" in r["cost"]
        assert r["cost"]["avg_cost_per_call"] > 0

    def test_provider_breakdown(self, populated_child):
        r = kit_observability.compute(populated_child)
        assert "openai-compatible" in r["cost"]["by_provider"]

    def test_model_breakdown(self, populated_child):
        r = kit_observability.compute(populated_child)
        assert "deepseek-chat" in r["models"]["by_model"]

    def test_text_has_sections(self, populated_child):
        r = kit_observability.compute(populated_child)
        text = kit_observability.format_text(r)
        assert "Cost:" in text
        assert "Workitems:" in text
        assert "Delivery:" in text


class TestUnreadableIsNamed:
    """Непрочитанный артефакт НАЗЫВАЕТСЯ в отчёте, а не пропускается молча.

    Ревизия 2026-08-11: загрузчики стояли на `except Exception: continue`, и битый workitem или
    расписка просто не попадали в счёт — отчёт печатал заниженное число как факт. Для инструмента,
    чья работа — говорить правду о состоянии, это худший вид ошибки: он не падает, он врёт тихо.
    Тот же принцип, что `unavailable != 0` в учёте стоимости.
    """

    def test_broken_workitem_is_reported_not_skipped(self, tmp_path):
        wi = tmp_path / "features" / "broken" / "workitem.yaml"
        wi.parent.mkdir(parents=True)
        wi.write_text('id: "не закрытая кавычка\nstatus: done\n', encoding="utf-8")

        r = kit_observability.compute(str(tmp_path))

        assert r["workitems"]["total"] == 0, "битый workitem посчитан как валидный"
        named = r["workitems"]["unreadable"]
        assert len(named) == 1, f"непрочитанный workitem не назван в отчёте: {named}"
        assert named[0]["path"] == "features/broken/workitem.yaml"
        assert named[0]["reason"], "не сказано, ПОЧЕМУ файл не прочитан"

    def test_broken_receipt_is_reported_not_skipped(self, tmp_path):
        rp = tmp_path / "features" / "f1" / "delivery-outbox" / "d1.receipt.yaml"
        rp.parent.mkdir(parents=True)
        rp.write_text("kind: [unclosed\n", encoding="utf-8")

        r = kit_observability.compute(str(tmp_path))

        assert r["delivery"]["total"] == 0, "битая расписка посчитана как доставка"
        named = r["delivery"]["unreadable"]
        assert len(named) == 1, f"непрочитанная расписка не названа: {named}"
        assert named[0]["path"] == "features/f1/delivery-outbox/d1.receipt.yaml"

    def test_clean_repo_reports_nothing_unreadable(self, populated_child):
        """Обратная сторона: на исправных данных список пуст, а не «всегда что-то есть»."""
        r = kit_observability.compute(populated_child)
        assert r["workitems"]["unreadable"] == []
        assert r["delivery"]["unreadable"] == []
