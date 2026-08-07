"""Селфтест kit_observability, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from kit_observability import (  # noqa: F401 — имена, которые использует тело
    Path,
    compute,
    format_text,
    usage_ledger,
)


@pytest.mark.slow
def test_kit_observability_selftest():
    """Selftest: вычисление на пустом и заполненном child_root."""
    import tempfile
    ok = True

    def expect(label: str, cond: bool):
        nonlocal ok
        if not cond:
            print(f"  FAIL: {label}")
            ok = False

    # 1. Пустой child_root — честный "no data"
    with tempfile.TemporaryDirectory() as tmpdir:
        r = compute(tmpdir)
        expect("empty: has_data=False", r["kit"]["has_data"] is False)
        expect("empty: total_cost=0", r["cost"]["total_cost_usd"] == 0.0)
        expect("empty: total_calls=0", r["cost"]["total_calls"] == 0)
        expect("empty: workitems=0", r["workitems"]["total"] == 0)
        expect("empty: delivery=0", r["delivery"]["total"] == 0)
        expect("empty: no avg_cost_per_call", "avg_cost_per_call" not in r["cost"])
        text = format_text(r)
        expect("empty: text says no data", "Нет данных" in text)

    # 2. Заполненный child_root — метрики считаются
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        # Записи usage ledger
        (root / ".ai" / "usage").mkdir(parents=True)
        records = [
            {"run_id": "r1", "role": "implementation", "provider": "openai-compatible",
             "model": "deepseek-chat", "input_tokens": 1000, "output_tokens": 500,
             "usage_status": "measured", "cost": 0.05, "cost_status": "measured",
             "latency": 2.0, "trigger": "initial", "task_type": "ENGINEERING"},
            {"run_id": "r1", "role": "review", "provider": "openai-compatible",
             "model": "deepseek-chat", "input_tokens": 200, "output_tokens": 100,
             "usage_status": "measured", "cost": 0.01, "cost_status": "measured",
             "latency": 1.0, "trigger": "review", "task_type": "ENGINEERING"},
            {"run_id": "r2", "role": "implementation", "provider": "claude-cli",
             "model": "claude-sonnet-5", "input_tokens": None, "output_tokens": None,
             "usage_status": "unavailable", "cost": None, "cost_status": "unavailable",
             "latency": None, "trigger": "initial", "task_type": "QUICK"},
        ]
        usage_ledger.append(tmpdir, "wid-1", records[:2], run_id="r1",
                           extra_context={"task_type": "ENGINEERING"})
        usage_ledger.append(tmpdir, "wid-2", [records[2]], run_id="r2",
                           extra_context={"task_type": "QUICK"})

        # Workitems
        import yaml
        (root / "features" / "wid-1").mkdir(parents=True, exist_ok=True)
        (root / "features" / "wid-1" / "workitem.yaml").write_text(
            yaml.dump({"id": "wid-1", "status": "done", "lifecycle_intent": "delivery",
                       "workflow": "ENGINEERING"}), encoding="utf-8")
        (root / "features" / "wid-2").mkdir(parents=True, exist_ok=True)
        (root / "features" / "wid-2" / "workitem.yaml").write_text(
            yaml.dump({"id": "wid-2", "status": "draft", "lifecycle_intent": "discovery",
                       "workflow": "QUICK"}), encoding="utf-8")

        # Delivery receipts
        (root / "features" / "wid-1" / "delivery-outbox").mkdir(parents=True, exist_ok=True)
        (root / "features" / "wid-1" / "delivery-outbox" / "d1.receipt.yaml").write_text(
            yaml.dump({"kind": "DeliveryReceipt", "delivery_id": "d1", "status": "reconciled",
                       "sha_verified": True, "merged": True}), encoding="utf-8")

        r = compute(tmpdir)
        expect("filled: has_data=True", r["kit"]["has_data"] is True)
        expect("filled: total_calls=3", r["cost"]["total_calls"] == 3)
        expect("filled: cost > 0", r["cost"]["total_cost_usd"] > 0)
        expect("filled: cost_complete=False (1 unavailable)", r["cost"]["cost_complete"] is False)
        expect("filled: cost_unavailable=1", r["cost"]["cost_unavailable_count"] == 1)
        expect("filled: workitems=2", r["workitems"]["total"] == 2)
        expect("filled: by_status has done", r["workitems"]["by_status"].get("done") == 1)
        expect("filled: by_status has draft", r["workitems"]["by_status"].get("draft") == 1)
        expect("filled: delivery=1", r["delivery"]["total"] == 1)
        expect("filled: sha_verified=1", r["delivery"]["sha_verified"] == 1)
        expect("filled: merged=1", r["delivery"]["merged"] == 1)
        expect("filled: success_rate=1.0", r["delivery"].get("success_rate") == 1.0)
        expect("filled: avg_cost_per_call exists", "avg_cost_per_call" in r["cost"])
        expect("filled: by_provider has openai-compatible",
               "openai-compatible" in r["cost"]["by_provider"])
        expect("filled: models by_provider", "openai-compatible" in r["models"]["by_provider"])
        expect("filled: measured_calls=2", r["models"]["measured_calls"] == 2)
        expect("filled: unavailable_calls=1", r["models"]["unavailable_calls"] == 1)

        # format_text
        text = format_text(r)
        expect("text: has cost", "Cost:" in text)
        expect("text: has workitems", "Workitems:" in text)
        expect("text: has delivery", "Delivery:" in text)
        expect("text: has unavailable warning", "unknown cost" in text)

    assert ok, "перенесённый селфтест kit_observability: см. строки FAIL в выводе"
