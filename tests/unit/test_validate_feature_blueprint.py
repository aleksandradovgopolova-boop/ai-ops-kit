"""Гранулярные тесты validate_feature_blueprint (миграция с селфтеста)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from validate_feature_blueprint import (
    make_demo,
    validate_dir,
    yaml,
)


@pytest.mark.unit
@pytest.mark.slow
class TestFeatureBlueprintValidation:

    def test_valid_blueprint(self, tmp_path):
        with tempfile.TemporaryDirectory() as td:
            assert validate_dir(make_demo(Path(td) / "a")) == []

    def test_missing_stage_file_fails(self, tmp_path):
        with tempfile.TemporaryDirectory() as td:
            errs = validate_dir(make_demo(Path(td) / "b", break_file=True))
            assert errs  # non-empty → errors present

    def test_unknown_stage_fails(self, tmp_path):
        with tempfile.TemporaryDirectory() as td:
            errs = validate_dir(make_demo(Path(td) / "c", break_stage=True))
            assert errs

    def test_lean_delivery_without_ux_architecture_valid(self, tmp_path):
        with tempfile.TemporaryDirectory() as td:
            fdir = make_demo(Path(td) / "d")
            bp = yaml.safe_load((fdir / "blueprint.yaml").read_text(encoding="utf-8"))
            bp["feature"]["profile"] = "lean"
            bp["feature"]["current_stage"] = "delivery"
            (fdir / "delivery").mkdir()
            (fdir / "delivery" / "task-plan.md").write_text("# Plan\n", encoding="utf-8")
            bp["artifacts"]["delivery"] = [{"path": "delivery/task-plan.md", "status": "draft"}]
            (fdir / "blueprint.yaml").write_text(yaml.safe_dump(bp, allow_unicode=True),
                                                  encoding="utf-8")
            assert validate_dir(fdir) == []

    def test_full_same_data_fails(self, tmp_path):
        with tempfile.TemporaryDirectory() as td:
            fdir = make_demo(Path(td) / "e")
            bp = yaml.safe_load((fdir / "blueprint.yaml").read_text(encoding="utf-8"))
            bp["feature"]["profile"] = "lean"
            bp["feature"]["current_stage"] = "delivery"
            (fdir / "delivery").mkdir()
            (fdir / "delivery" / "task-plan.md").write_text("# Plan\n", encoding="utf-8")
            bp["artifacts"]["delivery"] = [{"path": "delivery/task-plan.md", "status": "draft"}]
            (fdir / "blueprint.yaml").write_text(yaml.safe_dump(bp, allow_unicode=True),
                                                  encoding="utf-8")
            bp["feature"]["profile"] = "full"
            (fdir / "blueprint.yaml").write_text(yaml.safe_dump(bp, allow_unicode=True),
                                                  encoding="utf-8")
            assert validate_dir(fdir)  # non-empty → errors present

    def test_released_without_done_artifacts_fails(self, tmp_path):
        """Finding обкатки 6: released без единого done-артефакта -> fail."""
        with tempfile.TemporaryDirectory() as td:
            rel = make_demo(Path(td) / "r")
            bpr = yaml.safe_load((rel / "blueprint.yaml").read_text(encoding="utf-8"))
            bpr["feature"]["status"] = "released"
            for entries in bpr["artifacts"].values():
                for e in entries:
                    e["status"] = "draft"
            (rel / "blueprint.yaml").write_text(yaml.safe_dump(bpr, allow_unicode=True),
                                                 encoding="utf-8")
            assert validate_dir(rel)  # non-empty → errors present

    def test_released_with_done_but_no_delivery_receipt_fails(self, tmp_path):
        """WP5: released с done-артефактом, но без DeliveryReceipt -> fail."""
        with tempfile.TemporaryDirectory() as td:
            rel = make_demo(Path(td) / "r2")
            bpr = yaml.safe_load((rel / "blueprint.yaml").read_text(encoding="utf-8"))
            bpr["feature"]["status"] = "released"
            for entries in bpr["artifacts"].values():
                for e in entries:
                    e["status"] = "draft"
            bpr["artifacts"]["discovery"][0]["status"] = "done"
            (rel / "blueprint.yaml").write_text(yaml.safe_dump(bpr, allow_unicode=True),
                                                 encoding="utf-8")
            errs = [e for e in validate_dir(rel) if "released" in e]
            assert errs  # non-empty → errors present

    def test_released_with_sha_verified_receipt_ok(self, tmp_path):
        """WP5: released с done-артефактом И SHA-verified DeliveryReceipt -> ок."""
        with tempfile.TemporaryDirectory() as td:
            rel = make_demo(Path(td) / "r3")
            bpr = yaml.safe_load((rel / "blueprint.yaml").read_text(encoding="utf-8"))
            bpr["feature"]["status"] = "released"
            for entries in bpr["artifacts"].values():
                for e in entries:
                    e["status"] = "draft"
            bpr["artifacts"]["discovery"][0]["status"] = "done"
            (rel / "blueprint.yaml").write_text(yaml.safe_dump(bpr, allow_unicode=True),
                                                 encoding="utf-8")
            receipt = {"schema_version": 1, "kind": "DeliveryReceipt",
                        "delivery_id": "d1", "workitem_id": "demo-feature",
                        "sha_verified": True, "remote_sha": "abc123"}
            (rel / "delivery-receipt.yaml").write_text(
                yaml.safe_dump(receipt, allow_unicode=True), encoding="utf-8")
            errs = [e for e in validate_dir(rel) if "released" in e]
            assert not errs

    def test_released_with_receipt_but_sha_verified_false_fails(self, tmp_path):
        """WP5: released с DeliveryReceipt, но sha_verified=false -> fail."""
        with tempfile.TemporaryDirectory() as td:
            rel = make_demo(Path(td) / "r4")
            bpr = yaml.safe_load((rel / "blueprint.yaml").read_text(encoding="utf-8"))
            bpr["feature"]["status"] = "released"
            for entries in bpr["artifacts"].values():
                for e in entries:
                    e["status"] = "draft"
            bpr["artifacts"]["discovery"][0]["status"] = "done"
            (rel / "blueprint.yaml").write_text(yaml.safe_dump(bpr, allow_unicode=True),
                                                 encoding="utf-8")
            receipt = {"schema_version": 1, "kind": "DeliveryReceipt",
                        "delivery_id": "d1", "workitem_id": "demo-feature",
                        "sha_verified": False, "remote_sha": "abc123"}
            (rel / "delivery-receipt.yaml").write_text(
                yaml.safe_dump(receipt, allow_unicode=True), encoding="utf-8")
            errs = [e for e in validate_dir(rel) if "released" in e]
            assert errs


# ---------------------------------------------------------------------------
# Existing granular tests (preserved from original file)
# ---------------------------------------------------------------------------

def _released_with_done_artifact(root):
    """Фича в состоянии released с одним done-артефактом — предпосылка проверки расписки."""
    fdir = make_demo(root)
    bp = yaml.safe_load((fdir / "blueprint.yaml").read_text(encoding="utf-8"))
    bp["feature"]["status"] = "released"
    bp["artifacts"]["discovery"][0]["status"] = "done"
    (fdir / "blueprint.yaml").write_text(yaml.safe_dump(bp, allow_unicode=True), encoding="utf-8")
    return fdir


@pytest.mark.unit
def test_unreadable_receipt_is_not_reported_as_missing(tmp_path):
    """Битая расписка НЕ выдаётся за отсутствующую (ревизия 2026-08-11)."""
    fdir = _released_with_done_artifact(tmp_path / "corrupt")
    (fdir / "delivery-receipt.yaml").write_text("kind: \"DeliveryReceipt\nsha_verified: true\n",
                                                encoding="utf-8")
    errs = [e for e in validate_dir(fdir) if "released" in e]
    assert errs, "битая расписка перестала блокировать — fail-closed потерян"
    joined = " ".join(errs)
    assert "прочитать его не удалось" in joined, (
        f"причина названа неверно: битую расписку не отличили от отсутствующей -> {errs}")
    assert "delivery-receipt.yaml" in joined, f"не назван файл, который надо починить -> {errs}"


@pytest.mark.unit
def test_missing_receipt_does_not_claim_unreadable(tmp_path):
    """Обратная сторона: когда расписки НЕТ, про «не удалось прочитать» не говорится."""
    fdir = _released_with_done_artifact(tmp_path / "missing")
    errs = [e for e in validate_dir(fdir) if "released" in e]
    assert errs, "released без расписки перестал блокировать"
    assert "прочитать" not in " ".join(errs), (
        f"отсутствие расписки описано как нечитаемость -> {errs}")
