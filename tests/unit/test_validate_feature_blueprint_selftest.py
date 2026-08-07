"""Селфтест validate_feature_blueprint, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_feature_blueprint import (  # noqa: F401 — имена, которые использует тело
    Path,
    make_demo,
    tempfile,
    validate_dir,
    yaml,
)


@pytest.mark.slow
def test_validate_feature_blueprint_selftest():
    ok = True

    def expect(name, errs, want_errors):
        nonlocal ok
        good = bool(errs) == want_errors
        ok = ok and good
        print(f"{'PASS' if good else 'FAIL'} {name}" + ("" if good else f" -> {errs}"))

    with tempfile.TemporaryDirectory() as td:
        expect("валидный blueprint", validate_dir(make_demo(Path(td) / "a")), False)
        expect("отсутствующий файл достигнутой стадии -> fail",
               validate_dir(make_demo(Path(td) / "b", break_file=True)), True)
        expect("неизвестная стадия -> fail",
               validate_dir(make_demo(Path(td) / "c", break_stage=True)), True)
        # lean-профиль: current_stage=delivery, стадий ux/architecture в blueprint нет — валидно
        fdir = make_demo(Path(td) / "d")
        bp = yaml.safe_load((fdir / "blueprint.yaml").read_text(encoding="utf-8"))
        bp["feature"]["profile"] = "lean"
        bp["feature"]["current_stage"] = "delivery"
        (fdir / "delivery").mkdir()
        (fdir / "delivery" / "task-plan.md").write_text("# Plan\n", encoding="utf-8")
        bp["artifacts"]["delivery"] = [{"path": "delivery/task-plan.md", "status": "draft"}]
        (fdir / "blueprint.yaml").write_text(yaml.safe_dump(bp, allow_unicode=True), encoding="utf-8")
        expect("lean: delivery без ux/architecture -> валидно", validate_dir(fdir), False)
        bp["feature"]["profile"] = "full"
        (fdir / "blueprint.yaml").write_text(yaml.safe_dump(bp, allow_unicode=True), encoding="utf-8")
        expect("full: те же данные -> fail (ux/architecture достигнуты без артефактов)",
               validate_dir(fdir), True)
        # finding обкатки 6: released без единого done-артефакта -> fail (reality/blueprint дрейф)
        rel = make_demo(Path(td) / "r")
        bpr = yaml.safe_load((rel / "blueprint.yaml").read_text(encoding="utf-8"))
        bpr["feature"]["status"] = "released"
        for entries in bpr["artifacts"].values():
            for e in entries:
                e["status"] = "draft"   # ничего не done
        (rel / "blueprint.yaml").write_text(yaml.safe_dump(bpr, allow_unicode=True), encoding="utf-8")
        expect("released без done-артефактов -> fail (finding 6)", validate_dir(rel), True)
        # v3.27.4 WP5: released с done-артефактом, но без DeliveryReceipt -> fail
        bpr["artifacts"]["discovery"][0]["status"] = "done"
        (rel / "blueprint.yaml").write_text(yaml.safe_dump(bpr, allow_unicode=True), encoding="utf-8")
        errs_rel = [e for e in validate_dir(rel) if "released" in e]
        expect("released с done-артефактом, но без DeliveryReceipt -> fail (WP5)", errs_rel, True)
        # v3.27.4 WP5: released с done-артефактом И SHA-verified DeliveryReceipt -> ок
        receipt = {"schema_version": 1, "kind": "DeliveryReceipt", "delivery_id": "d1",
                   "workitem_id": "demo-feature", "sha_verified": True, "remote_sha": "abc123"}
        (rel / "delivery-receipt.yaml").write_text(yaml.safe_dump(receipt, allow_unicode=True), encoding="utf-8")
        errs_rel2 = [e for e in validate_dir(rel) if "released" in e]
        expect("released с done-артефактом И SHA-verified DeliveryReceipt -> ок (WP5)", errs_rel2, False)
        # v3.27.4 WP5: released с done-артефактом И DeliveryReceipt, но sha_verified=false -> fail
        receipt["sha_verified"] = False
        (rel / "delivery-receipt.yaml").write_text(yaml.safe_dump(receipt, allow_unicode=True), encoding="utf-8")
        errs_rel3 = [e for e in validate_dir(rel) if "released" in e]
        expect("released с DeliveryReceipt, но sha_verified=false -> fail (WP5)", errs_rel3, True)

    assert ok, "перенесённый селфтест validate_feature_blueprint: см. строки FAIL в выводе"
