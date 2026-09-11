"""Характеристика delivery-барьера в run() (open_pr + ready) — ДО выноса (K6-глубина).

Замер сессии 2026-08-26: канонический pipeline_run идёт с open_pr=False, поэтому блок доставки
(DeliveryIntent -> внешнее действие -> DeliveryReceipt, governance-gate, outcome_unknown,
fail-closed барьеры) в контроллере не гонялся ни одним тестом. Эти тесты пинят наблюдаемое
поведение доставки на ТЕКУЩЕМ коде, чтобы вынос блока в _deliver(ctx, rep, ...) был проверяемо
поведение-сохраняющим.

Внешнее действие (execution_pipeline._deliver_pr) замокано; движок исполняется по-настоящему
(execute=True), коммитит в worktree и отдаёт delivery_plan, за которым и идёт доставка.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]

from ai_ops_kit.engine import ai_ops_run
from ai_ops_kit.shared import lifecycle_store as _ls


def _git_repo(root: Path):
    for a in (("init", "-q"), ("config", "user.email", "t@t"), ("config", "user.name", "t")):
        subprocess.run(["git", "-C", str(root), *a], capture_output=True)
    (root / "src").mkdir(exist_ok=True)
    (root / "f").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "i"], capture_output=True)
    cur = subprocess.run(["git", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    return cur


def _run_delivery(root, *, deliver_status="opened", head_sha_matches=True, feature="deliv"):
    """Прогнать run() с open_pr=True и замоканным _deliver_pr; вернуть отчёт."""
    cur = _git_repo(root)
    ps = iter([{"op": "write", "path": "src/a.py", "content": "a=1\n"}, {"done": True}])

    def fake_deliver(work_root, branch, base_ref, base_sha, base_binding, csha, wid, task, delivery_id=None):
        pr = {"url": "https://example.test/pr/1", "number": 1,
              "head_sha": (csha if head_sha_matches else "deadbeef")}
        return {"status": deliver_status, "pr": pr}

    with patch("ai_ops_kit.engine.execution_pipeline._deliver_pr", side_effect=fake_deliver) as m:
        rep = ai_ops_run.run(
            task_text="добавить a",
            signals={"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]},
            child_root=root, engine="pipeline", provider_name="mock",
            proposer=lambda c: next(ps), execute=True, open_pr=True, base=cur, feature=feature,
            install_deps=False)
    return rep, m


@pytest.fixture(scope="module")
def delivered(tmp_path_factory):
    root = tmp_path_factory.mktemp("deliv_ok")
    return (root, *_run_delivery(root, feature="delivok"))


@pytest.mark.unit
class TestDeliveryOpensPR:
    """ready + open_pr + внешнее действие opened + sha сходится -> delivered, Intent/Receipt durable."""

    def test_deliver_pr_was_called(self, delivered):
        _, _, m = delivered
        assert m.called, "внешнее действие доставки не вызвано — блок доставки не достигнут"

    def test_overall_status_delivered(self, delivered):
        _, rep, _ = delivered
        assert rep.get("overall_status") == "delivered"
        assert rep["delivery"]["status"] == "opened"
        assert rep["delivery"]["sha_verified"] is True

    def test_intent_and_receipt_written(self, delivered):
        root, rep, _ = delivered
        did = rep["delivery"]["delivery_id"]
        obx = root / "features" / "delivok" / "delivery-outbox"
        assert (obx / f"{did}.intent.yaml").is_file()
        assert (obx / f"{did}.receipt.yaml").is_file()

    def test_journal_has_intent_and_receipt(self, delivered):
        root, _, _ = delivered
        jr = _ls.journal_read(root / "features" / "delivok" / "lifecycle-journal.jsonl")
        kinds = {e["kind"] for e in jr["events"]}
        assert "delivery_intent" in kinds and "delivery_receipt" in kinds

    def test_governance_gate_recorded(self, delivered):
        """governance по умолчанию observe: решение записано в rep, доставка не остановлена."""
        _, rep, _ = delivered
        assert "delivery" in (rep.get("governance") or {})


@pytest.mark.unit
class TestDeliveryOutcomeUnknown:
    """Неоднозначный POST -> outcome_unknown + reconciliation_required, Receipt НЕ пишется."""

    def test_outcome_unknown_marks_reconciliation(self, tmp_path):
        root = tmp_path / "deliv_unk"; root.mkdir()
        rep, _ = _run_delivery(root, deliver_status="outcome_unknown", feature="delivunk")
        assert rep.get("overall_status") == "delivery-outcome-unknown"
        assert rep["delivery"]["reconciliation_required"] is True
        did = rep["delivery"]["delivery_id"]
        obx = root / "features" / "delivunk" / "delivery-outbox"
        assert (obx / f"{did}.intent.yaml").is_file()
        assert not (obx / f"{did}.receipt.yaml").is_file()   # confirmed Receipt не пишется


@pytest.mark.unit
class TestReconcileNonFinalReceipt:
    """#400: ложный sha_verified=false (гонка чтения head_sha, P0) больше не залипает — реконсиляция
    перепроверяет НЕ-финальный receipt против свежего remote и повышает до подтверждённого. Раньше
    _unresolved_intents считал доставку решённой, как только файл receipt есть, и remote, уже
    совпавший с коммитом, не сверялся — приходилось руками удалять файл леджера."""

    def _seed(self, root, fid, did, *, sha_verified):
        obx = root / "features" / fid / "delivery-outbox"
        obx.mkdir(parents=True, exist_ok=True)
        _ls.durable_write(obx / f"{did}.intent.yaml",
                          {"schema_version": 1, "kind": "DeliveryIntent", "delivery_id": did,
                           "workitem_id": fid, "repository": "o/r", "branch": "ai-ops/x",
                           "base_ref": "main", "base_sha": "b0", "commit_sha": "c0ffee",
                           "status": "completed"},
                          require_keys=("kind", "delivery_id", "commit_sha", "repository"))
        _ls.durable_write(obx / f"{did}.receipt.yaml",
                          {"schema_version": 1, "kind": "DeliveryReceipt", "delivery_id": did,
                           "workitem_id": fid, "repository": "o/r", "branch": "ai-ops/x",
                           "commit_sha": "c0ffee", "base_ref": "main", "status": "updated",
                           "remote_sha": "stale", "sha_verified": sha_verified},
                          require_keys=("kind", "delivery_id", "status"))
        return obx

    def test_nonfinal_selected_final_ignored(self, tmp_path):
        self._seed(tmp_path, "featA", "d1", sha_verified=False)   # ложный false
        self._seed(tmp_path, "featB", "d2", sha_verified=True)    # окончателен
        fd = tmp_path / "features"
        assert [d for d, _ in ai_ops_run._nonfinal_receipt_intents(fd, "featA")] == ["d1"]
        assert ai_ops_run._nonfinal_receipt_intents(fd, "featB") == []

    def test_reconcile_upgrades_false_to_verified(self, tmp_path):
        obx = self._seed(tmp_path, "featA", "d1", sha_verified=False)
        fd = tmp_path / "features"

        def fake_reconcile(child_root, branch):
            # remote теперь совпадает с commit_sha -> строгая идентичность проходит
            return {"status": "found", "repository": "o/r", "head_sha": "c0ffee", "base_ref": "main",
                    "url": "https://example.test/pr/5", "number": 5, "pr_state": "open", "merged": False,
                    "checks": {"status": "absent", "total": 0, "failed": 0, "pending": 0, "success": 0}}

        with patch("ai_ops_kit.delivery.pr_open.reconcile_delivery", side_effect=fake_reconcile):
            res = ai_ops_run._reconcile_pending_delivery(fd, "featA", str(tmp_path))
        assert res and res[0]["status"] == "reconciled"
        rec = _ls.load_guarded(obx / "d1.receipt.yaml", kind="DeliveryReceipt")["data"]
        assert rec["sha_verified"] is True    # ложный false вылечен без ручного удаления леджера
