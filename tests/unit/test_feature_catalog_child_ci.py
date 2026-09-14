"""Каталог фич проведён в контур дочки (W4c) — генерируется из ЕЁ реестра, без раздувания поставки.

W4b доставил ДВИЖОК каталога (`ai_ops_kit/checks/feature_catalog.render_catalog`); в дочке его пока
никто не звал. W4c это чинит: доставляемый child-CI workflow `ai-ops-feature-catalog.yml` зовёт
генерацию ИЗ КЛОНА кита над реестром фич дочки и пишет её `docs/feature-catalog.md`. Новых
доставляемых Python-файлов работа не добавляет — генератор зовётся из клона (обёртка devtools/ в
поставку не едет), как child-валидаторы в ai-ops-validate.yml.

Тесты ПОВЕДЕНЧЕСКИЕ: зовут CLI и функции доставки, а не читают их исходники.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

from ai_ops_kit.devtools import feature_catalog_cli as cli

KIT = Path(__file__).resolve().parents[2]
TEMPLATE = "ai-ops-feature-catalog.yml"

pytestmark = pytest.mark.unit


def _child_registry(tmp_path: Path) -> Path:
    """Минимальный валидный реестр фич дочки на диске."""
    reg = tmp_path / "feature-registry.yaml"
    reg.write_text(yaml.safe_dump({
        "schema_version": 1,
        "registry_type": "feature-registry",
        "features": [{
            "id": "checkout-flow",
            "name": "Оформление заказа",
            "description": {"what": "Пользователь оформляет заказ.",
                            "who": "Покупатель продукта.",
                            "verify": "POST /checkout с корзиной → 200 и созданный заказ."},
            "surfaces": [{"kind": "route", "ref": "src/shop/routes.py:44|checkout",
                          "confidence": "verified", "extractor": "none"}],
            "status": "active",
            "owner": "team-shop",
        }],
    }, allow_unicode=True), encoding="utf-8")
    return reg


# ─── CLI child-mode: генерация каталога ДОЧКИ из ЕЁ реестра (зов из клона в CI это и делает) ──────

def test_cli_writes_child_catalog_from_child_registry(tmp_path):
    """--out + --regen-cmd собирают каталог ДОЧКИ из её реестра в её файл, а не в док кита."""
    reg = _child_registry(tmp_path)
    out = tmp_path / "docs" / "feature-catalog.md"

    rc = cli.main([str(reg), "--write", "--out", str(out),
                   "--regen-cmd", "REGEN-BY-CHILD-WORKFLOW"])

    assert rc == 0
    assert out.is_file(), "каталог дочки не записан по --out"
    text = out.read_text(encoding="utf-8")
    # фича дочки видна аналитику: id + что/для кого/как проверить
    assert "checkout-flow" in text
    assert "Что делает:" in text and "Для кого:" in text and "Как проверить:" in text
    assert "POST /checkout" in text
    # шапка подписана командой перегенерации ДОЧКИ, а не devtools-обёрткой кита
    assert "REGEN-BY-CHILD-WORKFLOW" in text


def test_cli_out_check_detects_staleness_then_agrees_after_write(tmp_path):
    """--check против файла дочки краснеет на устаревшем каталоге и зеленеет после --write."""
    reg = _child_registry(tmp_path)
    out = tmp_path / "docs" / "feature-catalog.md"
    out.parent.mkdir(parents=True)
    out.write_text("устаревшее содержимое\n", encoding="utf-8")

    stale = cli.main([str(reg), "--check", "--out", str(out), "--regen-cmd", "C"])
    assert stale == 1, "устаревший каталог дочки не распознан"

    assert cli.main([str(reg), "--write", "--out", str(out), "--regen-cmd", "C"]) == 0
    assert cli.main([str(reg), "--check", "--out", str(out), "--regen-cmd", "C"]) == 0


def test_missing_child_registry_yields_honest_stub_not_crash(tmp_path):
    """Нет реестра фич — не ошибка: честная заглушка, код 0, а не падение."""
    out = tmp_path / "docs" / "feature-catalog.md"

    rc = cli.main([str(tmp_path / "no-such-registry.yaml"), "--write", "--out", str(out)])

    assert rc == 0
    assert "Фичи ещё не заведены" in out.read_text(encoding="utf-8")


def test_default_mode_unchanged_targets_kit_doc(tmp_path):
    """Без --out/--regen-cmd поведение прежнее: --check сверяет committed-док САМОГО кита (зелёный).

    Гарантия, что добавленные флаги аддитивны и не тронули генерацию собственного дока кита.
    """
    assert cli.main(["--check"]) == 0


# ─── доставка шаблона: зарегистрирован, валиден, зовёт генерацию ИЗ КЛОНА, доезжает до дочки ──────

def _installer(root: Path):
    """Загрузить installer с REPO_ROOT = root (как в test_ci_template_delivery)."""
    import os
    old = os.getcwd()
    os.chdir(root)
    try:
        spec = importlib.util.spec_from_file_location(
            f"ai_ops_inst_fc_{abs(hash(str(root)))}", KIT / "installer" / "ai_ops.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        os.chdir(old)


def test_template_is_registered_for_delivery_and_unconditional():
    """Шаблон в наборе доставки CI и НЕ условный: каталог фич применим к любому продукту.

    Мутация: убрать имя из CI_TEMPLATES -> файл не доставляется вообще, дочка каталог не получает.
    """
    inst = _installer(KIT)
    assert TEMPLATE in inst.CI_TEMPLATES, "шаблон не в наборе доставки — до дочки не доедет"
    assert TEMPLATE not in inst.CONDITIONAL_CI_TEMPLATES, "каталог применим к любому продукту, а не условно"


def test_template_generates_from_clone_over_child_registry():
    """Генерация зовётся ИЗ КЛОНА кита ($RUNNER_TEMP) через поставляемый рендер, над реестром ДОЧКИ,
    и пишет её собственный docs/feature-catalog.md — без доставки нового Python-файла (как validate)."""
    src = (KIT / "templates" / "ci" / TEMPLATE).read_text(encoding="utf-8")
    doc = yaml.safe_load(src)
    assert doc["name"] == "ai-ops-feature-catalog"
    # клон кита в $RUNNER_TEMP (не /tmp) — тот же приём, что в ai-ops-validate.yml
    assert "$RUNNER_TEMP" in src and "git clone" in src
    # генерация зовётся из клона: PYTHONPATH на клон + модуль-обёртка каталога
    assert 'PYTHONPATH="$RUNNER_TEMP"/ai-ops-kit' in src
    assert "ai_ops_kit.devtools.feature_catalog_cli" in src
    # пишет ФАЙЛ ДОЧКИ, а не док кита
    assert "--out docs/feature-catalog.md" in src
    # читает СОБСТВЕННЫЙ реестр дочки — ЕДИНЫЙ путь, тот же, что у контура охвата
    assert "registry/features.yaml" in src
    # PR — сверка/генерация без коммита; push в main — коммит обновления
    assert "github.event_name == 'pull_request'" in src
    assert "github.event_name == 'push'" in src
    assert "git commit" in src


def test_template_delivered_to_any_served_child(tmp_path):
    """Безусловная доставка: workflow доезжает до дочки (даже без реестра — там он честно скипает)."""
    inst = _installer(tmp_path)
    served = tmp_path / "served"
    (served / ".github" / "workflows").mkdir(parents=True)
    (served / ".ai" / "runtime").mkdir(parents=True)

    inst._ci_setup().sync_ci_workflows(served)

    assert (served / ".github" / "workflows" / TEMPLATE).is_file(), \
        "workflow каталога фич не доставлен дочке"


def test_template_skips_honestly_without_a_registry():
    """Без реестра фич шаг генерации выключен (if по steps.reg.outputs.path), а шаг поиска говорит,
    что каталог не генерируется — это skip, а не падение."""
    src = (KIT / "templates" / "ci" / TEMPLATE).read_text(encoding="utf-8")
    assert "steps.reg.outputs.path != ''" in src, "генерация не гейтится наличием реестра"
    assert "не генерируется (это не ошибка)" in src, "нет честного сообщения о пропуске без реестра"
