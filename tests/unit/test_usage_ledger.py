"""Гранулярные тесты usage_ledger (мигрировано из test_usage_ledger_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import tempfile

import pytest

from ai_ops_kit.shared.usage_ledger import (
    aggregate,
    append,
    check,
    load_product,
    load_task,
)


@pytest.fixture
def good_record():
    return {
        "run_id": "r1", "workitem_id": "w1", "role": "implementation", "provider": "claude-cli",
        "model": "claude-code-local", "input_tokens": 100, "output_tokens": 50,
        "usage_status": "measured", "cost": 0.07, "cost_status": "measured", "trigger": "initial",
    }


@pytest.mark.unit
class TestCheck:
    def test_valid_measured_no_errors(self, good_record):
        assert check(good_record) == []

    def test_unavailable_with_tokens_error(self, good_record):
        errors = check({**good_record, "usage_status": "unavailable"})
        assert any("unavailable" in x for x in errors)

    def test_unavailable_with_none_tokens_ok(self, good_record):
        result = check({**good_record, "usage_status": "unavailable", "input_tokens": None,
                        "output_tokens": None, "cost": None, "cost_status": "unavailable"})
        assert result == []

    def test_measured_without_tokens_error(self, good_record):
        errors = check({**good_record, "input_tokens": None, "output_tokens": None})
        assert any("нечего измерять" in x for x in errors)

    def test_zero_input_tokens_valid(self, good_record):
        assert check({**good_record, "input_tokens": 0, "output_tokens": 1}) == []

    def test_unknown_trigger_error(self, good_record):
        errors = check({**good_record, "trigger": "bogus"})
        assert any("trigger" in x for x in errors)


@pytest.mark.unit
class TestAggregate:
    @pytest.fixture
    def mixed_records(self, good_record):
        return [
            good_record,
            {**good_record, "role": "code_review", "provider": "deepseek", "trigger": "review",
             "cost": 0.001, "cost_status": "estimated"},
            {"usage_status": "unavailable", "input_tokens": None, "output_tokens": None, "cost": None,
             "cost_status": "unavailable", "role": "implementation", "provider": "kimi", "trigger": "escalation"},
        ]

    def test_calls_count(self, mixed_records):
        a = aggregate(mixed_records)
        assert a["calls"] == 3
        assert a["usage_measured"] == 2
        assert a["usage_unavailable"] == 1

    def test_tokens_only_measured(self, mixed_records):
        a = aggregate(mixed_records)
        assert a["input_tokens"] == 200
        assert a["output_tokens"] == 100

    def test_cost_incomplete(self, mixed_records):
        a = aggregate(mixed_records)
        assert a["cost_complete"] is False

    def test_by_role_and_trigger(self, mixed_records):
        a = aggregate(mixed_records)
        assert a["by_role"]["implementation"] == 2
        assert a["by_trigger"]["review"] == 1


@pytest.mark.unit
class TestRoundTrip:
    @pytest.fixture
    def ledger_dir(self):
        with tempfile.TemporaryDirectory() as td:
            yield td

    @pytest.fixture
    def records(self, good_record):
        return [
            good_record,
            {**good_record, "role": "code_review", "provider": "deepseek", "trigger": "review",
             "cost": 0.001, "cost_status": "estimated"},
            {"usage_status": "unavailable", "input_tokens": None, "output_tokens": None, "cost": None,
             "cost_status": "unavailable", "role": "implementation", "provider": "kimi", "trigger": "escalation"},
        ]

    def test_append_writes_three(self, ledger_dir, records):
        n = append(ledger_dir, "w1", records, run_id="r1")
        assert n == 3

    def test_load_task_reads_three(self, ledger_dir, records):
        append(ledger_dir, "w1", records, run_id="r1")
        assert len(load_task(ledger_dir, "w1")) == 3

    def test_load_product_reads_three(self, ledger_dir, records):
        append(ledger_dir, "w1", records, run_id="r1")
        assert len(load_product(ledger_dir)) == 3

    def test_normalization_includes_run_id(self, ledger_dir, records):
        append(ledger_dir, "w1", records, run_id="r1")
        assert load_task(ledger_dir, "w1")[0].get("run_id") == "r1"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1, True, "0.1", 10**400])
def test_invalid_cost_survives_as_unknown_call_not_invalid_json(tmp_path, good_record, bad):
    import json

    assert check({**good_record, "cost": bad})
    raw = {**good_record, "cost": None, "cost_usd_est": bad}
    assert append(tmp_path, "invalid", [raw, good_record]) == 2
    for records in (load_task(tmp_path, "invalid"), load_product(tmp_path)):
        assert len(records) == 2
        assert records[0]["cost"] is None
        assert records[0]["cost_status"] == "unavailable"
        json.dumps(records, allow_nan=False)
        agg = aggregate(records)
        assert agg["calls"] == 2
        assert agg["cost"] == pytest.approx(0.07)
        assert agg["cost_unavailable"] == 1
        assert agg["cost_complete"] is False
        json.dumps(agg, allow_nan=False)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1, True, "0.1", None])
def test_old_malformed_ledger_does_not_become_complete(good_record, bad):
    import json

    agg = aggregate([{**good_record, "cost": bad}, good_record])
    assert agg["cost"] == pytest.approx(0.07)
    assert agg["cost_complete"] is False
    assert agg["cost_unavailable"] == 1
    json.dumps(agg, allow_nan=False)


def test_overflow_is_finite_lower_bound_not_complete(good_record):
    import json

    agg = aggregate([{**good_record, "cost": 1e308}] * 2)
    assert agg["calls"] == 2
    assert agg["cost"] == 1e308
    assert agg["cost_overflow"] is True
    assert agg["cost_complete"] is False
    json.dumps(agg, allow_nan=False)


def test_measured_missing_cost_is_normalized_unavailable(tmp_path, good_record):
    append(tmp_path, "missing", [{**good_record, "cost": None}])
    record = load_task(tmp_path, "missing")[0]
    assert record["cost"] is None
    assert record["cost_status"] == "unavailable"
    assert aggregate([record])["cost_complete"] is False


@pytest.mark.parametrize("prices", [[1e308, 1], [1, 1e308]])
def test_absorbed_positive_expense_is_incomplete_lower_bound(good_record, prices):
    result = aggregate([{**good_record, "cost": price} for price in prices])
    assert result["calls"] == 2
    assert result["cost"] == 1e308
    assert result["cost_precision_lost"] is True
    assert result["cost_complete"] is False


def test_unrepresentable_integer_cost_is_unknown(good_record):
    from ai_ops_kit.shared.usage_ledger import normalize

    result = normalize({**good_record, "cost": 2**53 + 1})
    assert result["cost"] is None
    assert result["cost_status"] == "unavailable"


@pytest.mark.unit
class TestDurableMerge:
    def test_identical_calls_survive_and_repeat_is_idempotent(self, tmp_path, good_record):
        from ai_ops_kit.shared import usage_ledger as ledger
        src, dst = tmp_path / "src", tmp_path / "dst"
        append(src, "w1", [good_record, good_record])
        assert ledger.merge_ledgers(dst, [src]) == 2
        assert len(load_product(dst)) == len(load_task(dst, "w1")) == 2
        assert ledger.merge_ledgers(dst, [src]) == 0
        append(src, "w1", [good_record])
        assert ledger.merge_ledgers(dst, [src]) == 1
        assert len(load_product(dst)) == len(load_task(dst, "w1")) == 3

    def test_same_input_different_output_is_two_task_calls(self, tmp_path, good_record):
        from ai_ops_kit.shared import usage_ledger as ledger
        src, dst = tmp_path / "src", tmp_path / "dst"
        append(src, "w1", [good_record, {**good_record, "output_tokens": 99, "latency": 2}])
        ledger.merge_ledgers(dst, [src])
        assert len(load_task(dst, "w1")) == 2

    def test_different_sources_are_not_content_deduplicated(self, tmp_path, good_record):
        from ai_ops_kit.shared import usage_ledger as ledger
        sources = [tmp_path / "a", tmp_path / "b"]
        for src in sources:
            append(src, "w1", [good_record])
        assert ledger.merge_ledgers(tmp_path / "dst", sources) == 2
        assert len(load_product(tmp_path / "dst")) == len(load_task(tmp_path / "dst", "w1")) == 2

    def test_stable_source_id_survives_relocated_archive(self, tmp_path, good_record):
        import shutil
        from ai_ops_kit.shared import usage_ledger as ledger
        src, dst, archive = tmp_path / "src", tmp_path / "dst", tmp_path / "archive"
        append(src, "w1", [good_record])
        identity = "run-1/w1@" + "f" * 40
        assert ledger.merge_ledgers(dst, [src], source_ids={str(src): identity}) == 1
        shutil.copytree(src, archive)
        assert ledger.merge_ledgers(dst, [archive], source_ids={str(archive): identity}) == 0
        assert len(load_product(dst)) == 1

    def test_unknown_cost_and_only_declared_fields_are_copied(self, tmp_path, good_record):
        import json
        from ai_ops_kit.shared import usage_ledger as ledger
        src, dst = tmp_path / "src", tmp_path / "dst"
        append(src, "w1", [{**good_record, "cost": None, "cost_status": "unavailable"}])
        path = src / ".ai/usage/product-ledger.jsonl"
        row = json.loads(path.read_text())
        row.update(config="DO-NOT-COPY", prompt="DO-NOT-COPY", api_key="DO-NOT-COPY")
        path.write_text(json.dumps(row) + "\n")
        ledger.merge_ledgers(dst, [src])
        assert "DO-NOT-COPY" not in (dst / ".ai/usage/product-ledger.jsonl").read_text()
        assert load_product(dst)[0]["cost"] is None
        assert aggregate(load_product(dst))["cost_complete"] is False

    def test_corrupt_source_is_not_silently_skipped(self, tmp_path, good_record):
        from ai_ops_kit.shared import usage_ledger as ledger
        src, dst = tmp_path / "src", tmp_path / "dst"
        append(src, "w1", [good_record])
        path = src / ".ai/usage/product-ledger.jsonl"
        path.write_text(path.read_text() + "{broken\n")
        with pytest.raises(ValueError):
            ledger.merge_ledgers(dst, [src])
        assert not (dst / ".ai/usage/product-ledger.jsonl").exists()
        assert path.is_file()

    def test_source_symlink_escape_is_rejected(self, tmp_path, good_record):
        from ai_ops_kit.shared import usage_ledger as ledger
        src, dst = tmp_path / "src", tmp_path / "dst"
        append(src, "w1", [good_record])
        path = src / ".ai/usage/product-ledger.jsonl"
        outside = tmp_path / "private.jsonl"
        outside.write_text(path.read_text())
        path.unlink()
        path.symlink_to(outside)
        with pytest.raises(ValueError):
            ledger.merge_ledgers(dst, [src])
        assert outside.is_file() and not (dst / ".ai/usage/product-ledger.jsonl").exists()

    def test_changed_imported_offset_is_not_false_duplicate(self, tmp_path, good_record):
        import json
        from ai_ops_kit.shared import usage_ledger as ledger
        src, dst = tmp_path / "src", tmp_path / "dst"
        append(src, "w1", [good_record])
        ledger.merge_ledgers(dst, [src])
        path = src / ".ai/usage/product-ledger.jsonl"
        row = json.loads(path.read_text())
        row["cost"] = 0.99
        path.write_text(json.dumps(row) + "\n")
        before = (dst / ".ai/usage/product-ledger.jsonl").read_bytes()
        with pytest.raises(ValueError):
            ledger.merge_ledgers(dst, [src])
        assert (dst / ".ai/usage/product-ledger.jsonl").read_bytes() == before

    def test_partial_durable_failure_can_retry_without_duplication(self, tmp_path, good_record, monkeypatch):
        from ai_ops_kit.shared import usage_ledger as ledger, lifecycle_store
        src, dst = tmp_path / "src", tmp_path / "dst"
        append(src, "w1", [good_record])
        original = lifecycle_store.durable_write_jsonl
        def fail_task(path, rows):
            return ({"ok": False, "error": "controlled"} if "features" in path.parts
                    else original(path, rows))
        monkeypatch.setattr(lifecycle_store, "durable_write_jsonl", fail_task)
        with pytest.raises(ValueError):
            ledger.merge_ledgers(dst, [src])
        assert (src / "features/w1/usage-ledger.jsonl").is_file()
        monkeypatch.setattr(lifecycle_store, "durable_write_jsonl", original)
        ledger.merge_ledgers(dst, [src])
        assert len(load_product(dst)) == len(load_task(dst, "w1")) == 1

    def test_source_append_during_save_prevents_cleanup_ack(self, tmp_path, good_record, monkeypatch):
        from ai_ops_kit.shared import usage_ledger as ledger, lifecycle_store
        src, dst = tmp_path / "src", tmp_path / "dst"
        append(src, "w1", [good_record])
        original, injected = lifecycle_store.durable_write_jsonl, []
        def mutate(path, rows):
            result = original(path, rows)
            if not injected:
                injected.append(True)
                append(src, "w1", [good_record])
            return result
        monkeypatch.setattr(lifecycle_store, "durable_write_jsonl", mutate)
        with pytest.raises(ValueError):
            ledger.merge_ledgers(dst, [src])
        assert len(load_product(src)) == 2
        monkeypatch.setattr(lifecycle_store, "durable_write_jsonl", original)
        ledger.merge_ledgers(dst, [src])
        assert len(load_product(dst)) == len(load_task(dst, "w1")) == 2

    def test_atomic_merge_does_not_lose_concurrent_destination_append(self, tmp_path, good_record, monkeypatch):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        from ai_ops_kit.shared import usage_ledger as ledger, lifecycle_store
        src, dst = tmp_path / "src", tmp_path / "dst"
        append(src, "w1", [good_record])
        append(dst, "local", [{**good_record, "workitem_id": "local"}])
        entered, release, appending = Event(), Event(), Event()
        original = lifecycle_store.durable_write_jsonl
        def delayed(path, rows):
            if path.name == "product-ledger.jsonl":
                entered.set()
                assert release.wait(5)
            return original(path, rows)
        def write_local():
            appending.set()
            return append(dst, "local", [{**good_record, "workitem_id": "local"}])
        monkeypatch.setattr(lifecycle_store, "durable_write_jsonl", delayed)
        with ThreadPoolExecutor(max_workers=2) as pool:
            merge = pool.submit(ledger.merge_ledgers, dst, [src])
            assert entered.wait(5)
            writer = pool.submit(write_local)
            assert appending.wait(5)
            release.set()
            assert merge.result(5) == 1 and writer.result(5) == 1
        assert len(load_product(dst)) == 3 and len(load_task(dst, "local")) == 2

    def test_destination_symlink_cannot_redirect_atomic_write(self, tmp_path, good_record):
        from ai_ops_kit.shared import usage_ledger as ledger
        src, dst = tmp_path / "src", tmp_path / "dst"
        append(src, "w1", [good_record])
        outside = tmp_path / "outside"
        outside.mkdir()
        (dst / ".ai").mkdir(parents=True)
        (dst / ".ai/usage").symlink_to(outside, target_is_directory=True)
        with pytest.raises(ValueError):
            ledger.merge_ledgers(dst, [src])
        assert list(outside.iterdir()) == []

    def test_jsonl_adapter_refuses_invalid_rows_before_replace(self, tmp_path):
        from ai_ops_kit.shared import lifecycle_store
        path = tmp_path / "rows.jsonl"
        path.write_text('{"old": true}\n')
        assert lifecycle_store.durable_write_jsonl(path, ["invalid"])["ok"] is False
        assert path.read_text() == '{"old": true}\n'

    def test_no_process_lock_is_an_explicit_merge_refusal(self, tmp_path, good_record, monkeypatch):
        import builtins
        from ai_ops_kit.shared import usage_ledger as ledger
        src, dst = tmp_path / "src", tmp_path / "dst"
        append(src, "w1", [good_record])
        original = builtins.__import__
        def unavailable(name, *args, **kwargs):
            if name == "fcntl":
                raise ImportError("controlled unavailable lock")
            return original(name, *args, **kwargs)
        with monkeypatch.context() as patch:
            patch.setattr(builtins, "__import__", unavailable)
            with pytest.raises(ValueError, match="блокировка"):
                ledger.merge_ledgers(dst, [src])
        assert not (dst / ".ai/usage/product-ledger.jsonl").exists()

    def test_repeat_does_not_rewrite_already_durable_ledgers(self, tmp_path, good_record, monkeypatch):
        from ai_ops_kit.shared import usage_ledger as ledger, lifecycle_store
        src, dst = tmp_path / "src", tmp_path / "dst"
        append(src, "w1", [good_record])
        ledger.merge_ledgers(dst, [src])
        def unexpected(*args, **kwargs):
            raise AssertionError("unchanged validated ledger must not be rewritten")
        monkeypatch.setattr(lifecycle_store, "durable_write_jsonl", unexpected)
        assert ledger.merge_ledgers(dst, [src]) == 0

    def test_source_io_failure_is_explicit_and_keeps_last_copy(self, tmp_path, good_record, monkeypatch):
        from pathlib import Path
        from ai_ops_kit.shared import usage_ledger as ledger
        src, dst = tmp_path / "src", tmp_path / "dst"
        append(src, "w1", [good_record])
        original = Path.read_bytes
        path = src / ".ai/usage/product-ledger.jsonl"
        before = path.read_bytes()
        def unavailable(candidate):
            if candidate == path:
                raise OSError("controlled unreadable source")
            return original(candidate)
        with monkeypatch.context() as patch:
            patch.setattr(Path, "read_bytes", unavailable)
            with pytest.raises(ValueError, match="cleanup"):
                ledger.merge_ledgers(dst, [src])
        assert path.read_bytes() == before
        assert not (dst / ".ai/usage/product-ledger.jsonl").exists()

    def test_clone_baseline_history_is_not_imported_as_new_calls(self, tmp_path, good_record):
        from ai_ops_kit.shared import usage_ledger as ledger
        src, dst = tmp_path / "clone", tmp_path / "child"
        append(src, "w1", [good_record])
        baseline = ledger.snapshot_ledgers(src)
        append(src, "w1", [good_record, good_record])
        options = {"source_baselines": {str(src): baseline}}
        assert ledger.merge_ledgers(dst, [src], **options) == 2
        assert len(load_product(dst)) == len(load_task(dst, "w1")) == 2
        assert ledger.merge_ledgers(dst, [src], **options) == 0

    def test_clone_baseline_rewrite_refuses_cleanup(self, tmp_path, good_record):
        from ai_ops_kit.shared import usage_ledger as ledger
        src, dst = tmp_path / "clone", tmp_path / "child"
        append(src, "w1", [good_record])
        baseline = ledger.snapshot_ledgers(src)
        path = src / ".ai/usage/product-ledger.jsonl"
        path.write_text(path.read_text().replace('implementation', 'code_review'))
        with pytest.raises(ValueError, match="baseline"):
            ledger.merge_ledgers(dst, [src], source_baselines={str(src): baseline})
        assert path.exists() and not (dst / ".ai/usage/product-ledger.jsonl").exists()
