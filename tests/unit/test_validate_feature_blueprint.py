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

    def test_released_with_outbox_receipt_ok(self, tmp_path):
        """Регрессия: расписка в РЕАЛЬНОМ приёмнике features/<id>/delivery-outbox/*.receipt.yaml
        (куда пишут все продюсеры) удовлетворяет проверку. До фикса читались только запасные
        пути, куда никто не пишет, — честно доставленная функция всё равно валилась."""
        with tempfile.TemporaryDirectory() as td:
            rel = make_demo(Path(td) / "ob")
            bpr = yaml.safe_load((rel / "blueprint.yaml").read_text(encoding="utf-8"))
            bpr["feature"]["status"] = "released"
            for entries in bpr["artifacts"].values():
                for e in entries:
                    e["status"] = "draft"
            bpr["artifacts"]["discovery"][0]["status"] = "done"
            (rel / "blueprint.yaml").write_text(yaml.safe_dump(bpr, allow_unicode=True),
                                                 encoding="utf-8")
            outbox = rel / "delivery-outbox"
            outbox.mkdir()
            receipt = {"schema_version": 1, "kind": "DeliveryReceipt",
                        "delivery_id": "d1", "workitem_id": "demo-feature",
                        "sha_verified": True, "remote_sha": "abc123"}
            (outbox / "d1.receipt.yaml").write_text(
                yaml.safe_dump(receipt, allow_unicode=True), encoding="utf-8")
            errs = [e for e in validate_dir(rel) if "released" in e]
            assert not errs

    def test_released_with_outbox_receipt_sha_false_fails(self, tmp_path):
        """Расписка в приёмнике, но sha_verified=false -> проверка НЕ удовлетворена."""
        with tempfile.TemporaryDirectory() as td:
            rel = make_demo(Path(td) / "obf")
            bpr = yaml.safe_load((rel / "blueprint.yaml").read_text(encoding="utf-8"))
            bpr["feature"]["status"] = "released"
            for entries in bpr["artifacts"].values():
                for e in entries:
                    e["status"] = "draft"
            bpr["artifacts"]["discovery"][0]["status"] = "done"
            (rel / "blueprint.yaml").write_text(yaml.safe_dump(bpr, allow_unicode=True),
                                                 encoding="utf-8")
            outbox = rel / "delivery-outbox"
            outbox.mkdir()
            receipt = {"schema_version": 1, "kind": "DeliveryReceipt",
                        "delivery_id": "d1", "workitem_id": "demo-feature",
                        "sha_verified": False, "remote_sha": "abc123"}
            (outbox / "d1.receipt.yaml").write_text(
                yaml.safe_dump(receipt, allow_unicode=True), encoding="utf-8")
            errs = [e for e in validate_dir(rel) if "released" in e]
            assert errs

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


# ---------------------------------------------------------------------------
# Политика 2026-09-21: DeliveryReceipt требуется ТОЛЬКО если процесс фичи
# (профиль) включает стадию delivery. Оба текущих профиля (full, lean) её
# содержат, поэтому для сегодняшних фич правило латентно — исключение проверяем
# через профиль без delivery, добавленный monkeypatch'ем к тому же PROFILES,
# по которому код резолвит required-стадии (ключ — членство стадии, НЕ имя профиля).
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_released_full_profile_without_receipt_still_complains(tmp_path):
    """delivery ∈ full → расписка обязательна: без неё жалоба остаётся (без регресса)."""
    from ai_ops_kit.checks import feature_blueprint as fb
    assert "delivery" in fb.PROFILES["full"]
    fdir = make_demo(tmp_path / "full-rel")
    bp = yaml.safe_load((fdir / "blueprint.yaml").read_text(encoding="utf-8"))
    bp["feature"]["status"] = "released"
    bp["feature"]["profile"] = "full"
    bp["artifacts"]["discovery"][0]["status"] = "done"
    (fdir / "blueprint.yaml").write_text(yaml.safe_dump(bp, allow_unicode=True),
                                         encoding="utf-8")
    errs = [e for e in validate_dir(fdir) if "DeliveryReceipt" in e]
    assert errs, f"профиль с delivery без расписки обязан жаловаться -> {validate_dir(fdir)}"


@pytest.mark.unit
def test_released_profile_without_delivery_skips_receipt(tmp_path, monkeypatch):
    """delivery ∉ required-стадий профиля → расписку не требуем, ложной «докажи доставку» нет."""
    from ai_ops_kit.checks import feature_blueprint as fb
    monkeypatch.setitem(fb.PROFILES, "noship", ["discovery", "definition", "release"])
    assert "delivery" not in fb.PROFILES["noship"]

    fdir = tmp_path / "noship-feat"
    (fdir / "discovery").mkdir(parents=True)
    (fdir / "definition").mkdir()
    (fdir / "release").mkdir()
    (fdir / "discovery" / "problem.md").write_text("# Problem\n", encoding="utf-8")
    (fdir / "definition" / "prd.md").write_text("# PRD\n", encoding="utf-8")
    (fdir / "release" / "notes.md").write_text("# Release\n", encoding="utf-8")
    bp = {
        "schema_version": 1, "kind": "feature-blueprint",
        "feature": {"id": "noship-feat", "name": "NoShip", "status": "released",
                    "current_stage": "release", "profile": "noship"},
        "artifacts": {
            "discovery": [{"path": "discovery/problem.md", "status": "done"}],
            "definition": [{"path": "definition/prd.md", "status": "done"}],
            "release": [{"path": "release/notes.md", "status": "done"}],
        },
    }
    (fdir / "blueprint.yaml").write_text(yaml.safe_dump(bp, allow_unicode=True),
                                         encoding="utf-8")
    errors, advisories = fb.validate_dir_full(fdir)
    joined = " ".join(errors + advisories)
    assert "DeliveryReceipt" not in joined, f"расписку потребовали у фичи без delivery -> {joined}"
    assert "доказательства поставки" not in joined, joined
    assert errors == [], f"фича без delivery валидна, но получила ошибки -> {errors}"


@pytest.mark.unit
def test_released_delivery_staged_with_outbox_receipt_passes(tmp_path):
    """Страж outbox-фикса: delivery ∈ профиля + валидная outbox-расписка → без жалоб."""
    fdir = make_demo(tmp_path / "ob-rel")
    bp = yaml.safe_load((fdir / "blueprint.yaml").read_text(encoding="utf-8"))
    bp["feature"]["status"] = "released"
    bp["artifacts"]["discovery"][0]["status"] = "done"
    (fdir / "blueprint.yaml").write_text(yaml.safe_dump(bp, allow_unicode=True),
                                         encoding="utf-8")
    outbox = fdir / "delivery-outbox"
    outbox.mkdir()
    receipt = {"schema_version": 1, "kind": "DeliveryReceipt",
               "delivery_id": "d1", "workitem_id": "demo-feature",
               "sha_verified": True, "remote_sha": "abc123"}
    (outbox / "d1.receipt.yaml").write_text(yaml.safe_dump(receipt, allow_unicode=True),
                                            encoding="utf-8")
    errs = [e for e in validate_dir(fdir) if "released" in e or "DeliveryReceipt" in e]
    assert not errs, f"честно доставленная фича с outbox-распиской всё равно валится -> {errs}"
